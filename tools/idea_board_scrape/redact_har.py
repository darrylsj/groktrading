#!/usr/bin/env python3
"""Redact secrets from a HAR file. Usage: redact_har.py IN.har OUT_REDACTED.har

Fail-closed. Destination filename must contain REDACTED. Unsupported content
encodings are refused (they are not passed through). Base64 utf-8 bodies are
decoded, scrubbed, and stored as text.

Strips or scrubs:
  - secret headers (cookie, authorization, x-api-key, signature, …)
  - token-bearing Referer / Location / redirectURL / page title URLs
  - query params and postData.params whose names look secret
  - form bodies and JSON values for secret-ish keys, plus email addresses
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
import urllib.parse
from pathlib import Path

SECRET_HEADERS = {
    "cookie",
    "set-cookie",
    "authorization",
    "proxy-authorization",
    "x-csrf-token",
    "x-wp-nonce",
    "x-xsrf-token",
    "x-api-key",
    "api-key",
    "signature",
    "signature-input",
    "signature-agent",
}
URL_HEADERS = {"referer", "referrer", "location", "content-location"}
SECRET_PARAM_RE = re.compile(
    r"(token|nonce|password|passwd|pwd|secret|api[_-]?key|apikey|session|sessid|"
    r"auth|bearer|email|distinct_id|device_id|credential)",
    re.I,
)
REDACT = "[REDACTED]"
SUPPORTED_ENCODINGS = {"", "identity", "utf-8", "utf8", "base64"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JSON_KV_RE = re.compile(
    r"("
    r'"(?:[^"]*(?:token|nonce|password|passwd|secret|api_?key|apikey|session|auth|email|'
    r'distinct_id|device_id)[^"]*)"'
    r"\s*:\s*"
    r")"
    r"("
    r'"(?:\\.|[^"\\])*"|\d+(?:\.\d+)?|true|false|null'
    r")",
    re.I,
)
BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]{6,}")


class RedactError(ValueError):
    """HAR could not be redacted without leaving a possible secret."""


def scrub_text(text: str | None) -> str | None:
    if not text:
        return text
    text = JSON_KV_RE.sub(lambda match: match.group(1) + f'"{REDACT}"', text)
    text = BEARER_RE.sub(lambda match: match.group(1) + REDACT, text)
    return EMAIL_RE.sub(REDACT, text)


def scrub_url(url: str) -> str:
    if not url:
        return url
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return REDACT
    if parts.username or parts.password:
        parts = parts._replace(netloc=parts.hostname or "")
    query = parts.query
    if query:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
        cleaned = [(key, REDACT if SECRET_PARAM_RE.search(key) else value) for key, value in pairs]
        query = urllib.parse.urlencode(cleaned)
    fragment = ""
    if parts.fragment and SECRET_PARAM_RE.search(parts.fragment):
        fragment = REDACT
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


def _header_name(header: dict) -> str:
    return str(header.get("name") or "").lower()


def header_is_secret(name: str) -> bool:
    lowered = name.lower()
    if lowered in URL_HEADERS:
        return False
    if lowered in SECRET_HEADERS:
        return True
    return SECRET_PARAM_RE.search(lowered) is not None


def scrub_headers(headers: list | None) -> list | None:
    for header in headers or []:
        name = _header_name(header)
        if name in URL_HEADERS:
            header["value"] = scrub_url(str(header.get("value") or ""))
        elif header_is_secret(name):
            header["value"] = REDACT
    return headers


def scrub_form(text: str) -> str:
    pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
    if not pairs:
        return scrub_text(text) or ""
    cleaned = []
    for key, value in pairs:
        if SECRET_PARAM_RE.search(key):
            cleaned.append((key, REDACT))
        else:
            cleaned.append((key, scrub_text(value) or ""))
    return urllib.parse.urlencode(cleaned)


def scrub_body_text(text: str, mime: str) -> str:
    mime_l = (mime or "").lower()
    stripped = text.lstrip()
    is_json = "json" in mime_l or stripped.startswith(("{", "["))
    if not is_json and (
        "application/x-www-form-urlencoded" in mime_l or ("=" in text and "&" in text)
    ):
        return scrub_form(text)
    return scrub_text(text) or ""


def _decode_content_text(content: dict) -> str | None:
    if "text" not in content or content.get("text") is None:
        return None
    encoding = str(content.get("encoding") or "").strip().lower()
    if encoding not in SUPPORTED_ENCODINGS:
        raise RedactError(f"unsupported HAR content encoding: {encoding or 'unknown'}")
    text = content.get("text")
    if not isinstance(text, str):
        raise RedactError("HAR content.text must be a string")
    if encoding == "base64":
        try:
            raw = base64.b64decode(text, validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise RedactError("base64 HAR body is not utf-8 text; refusing to keep it") from exc
        content["encoding"] = ""
        return decoded
    return text


def _scrub_post(request: dict) -> None:
    post = request.get("postData") or {}
    if not post:
        return
    mime = str(post.get("mimeType") or "")
    encoding = str(post.get("encoding") or "").strip().lower()
    if encoding and encoding not in SUPPORTED_ENCODINGS:
        raise RedactError(f"unsupported HAR postData encoding: {encoding}")
    if post.get("text"):
        if encoding == "base64":
            decoded = _decode_content_text({"encoding": "base64", "text": post["text"]})
            post["encoding"] = ""
            post["text"] = scrub_body_text(decoded or "", mime)
        else:
            post["text"] = scrub_body_text(str(post["text"]), mime)
    for param in post.get("params") or []:
        if SECRET_PARAM_RE.search(str(param.get("name") or "")):
            param["value"] = REDACT
        elif isinstance(param.get("value"), str):
            param["value"] = scrub_text(param["value"])


def _scrub_pages(har: dict) -> None:
    log = har.get("log") or {}
    for page in log.get("pages") or []:
        title = page.get("title")
        if isinstance(title, str):
            page["title"] = scrub_url(title) if "://" in title else (scrub_text(title) or "")
        comment = page.get("comment")
        if isinstance(comment, str):
            page["comment"] = scrub_text(comment)
        page.pop("cookies", None)
        if isinstance(page.get("id"), str) and SECRET_PARAM_RE.search(page["id"]):
            page["id"] = REDACT


def _assert_redacted_destination(dst: Path) -> None:
    if "REDACTED" not in dst.name.upper():
        raise RedactError(
            "refusing to write a raw HAR name; destination filename must contain REDACTED"
        )


def redact_har(src: Path, dst: Path) -> int:
    """Redact ``src`` into ``dst``. Raises ``RedactError`` instead of leaking."""
    _assert_redacted_destination(dst)
    har = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(har, dict) or "log" not in har:
        raise RedactError("HAR missing log object")
    _scrub_pages(har)
    count = 0
    for entry in (har.get("log") or {}).get("entries") or []:
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        request["url"] = scrub_url(str(request.get("url") or ""))
        scrub_headers(request.get("headers"))
        scrub_headers(response.get("headers"))
        for query in request.get("queryString") or []:
            if SECRET_PARAM_RE.search(str(query.get("name") or "")):
                query["value"] = REDACT
            elif isinstance(query.get("value"), str):
                query["value"] = scrub_text(query["value"])
        request["cookies"] = []
        response["cookies"] = []
        response["redirectURL"] = scrub_url(str(response.get("redirectURL") or ""))
        _scrub_post(request)
        content = response.get("content") or {}
        if content:
            mime = str(content.get("mimeType") or "")
            decoded = _decode_content_text(content)
            if decoded is not None:
                content["text"] = scrub_body_text(decoded, mime)
        count += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(har, indent=1), encoding="utf-8")
    return count


def main(src: str, dst: str) -> None:
    try:
        count = redact_har(Path(src), Path(dst))
    except RedactError as exc:
        print(f"redact failed closed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"redacted {count} entries -> {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: redact_har.py IN.har OUT_REDACTED.har", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
