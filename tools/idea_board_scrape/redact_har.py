#!/usr/bin/env python3
"""Redact secrets from a HAR file. Usage: redact_har.py IN.har OUT_REDACTED.har

Strips values (keeps names, so endpoint/auth-style triage still works) for:
  - request/response headers: cookie, set-cookie, authorization, proxy-authorization,
    x-csrf-token, x-wp-nonce, signature, signature-input, signature-agent
  - cookie arrays
  - query params + URL params whose name looks secret-ish
  - request/response body JSON values for secret-ish keys, plus email addresses
"""

from __future__ import annotations

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
    "signature",
    "signature-input",
    "signature-agent",
}
SECRET_PARAM_RE = re.compile(
    r"(token|nonce|password|passwd|pwd|secret|api[_-]?key|apikey|session|sessid|"
    r"auth|bearer|email|distinct_id|device_id|credential)",
    re.I,
)
REDACT = "[REDACTED]"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JSON_KV_RE = re.compile(
    r'("(?:[^"]*(?:token|nonce|password|passwd|secret|api_?key|session|auth|email|'
    r'distinct_id|device_id)[^"]*)"\s*:\s*)'
    r'("(?:\\.|[^"\\])*"|\d+(?:\.\d+)?|true|false|null)',
    re.I,
)


def scrub_text(text: str | None) -> str | None:
    if not text:
        return text
    text = JSON_KV_RE.sub(lambda match: match.group(1) + f'"{REDACT}"', text)
    return EMAIL_RE.sub(REDACT, text)


def scrub_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    cleaned = [(key, REDACT if SECRET_PARAM_RE.search(key) else value) for key, value in pairs]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(cleaned), parts.fragment)
    )


def scrub_headers(headers: list | None) -> list | None:
    for header in headers or []:
        if header.get("name", "").lower() in SECRET_HEADERS:
            header["value"] = REDACT
    return headers


def redact_har(src: Path, dst: Path) -> int:
    har = json.loads(src.read_text(encoding="utf-8"))
    count = 0
    for entry in har["log"]["entries"]:
        request = entry.get("request", {})
        response = entry.get("response", {})
        request["url"] = scrub_url(request.get("url", ""))
        scrub_headers(request.get("headers"))
        scrub_headers(response.get("headers"))
        for query in request.get("queryString") or []:
            if SECRET_PARAM_RE.search(query.get("name", "")):
                query["value"] = REDACT
        request["cookies"] = []
        response["cookies"] = []
        post = request.get("postData") or {}
        if post.get("text"):
            post["text"] = scrub_text(post["text"])
        content = response.get("content") or {}
        if content.get("text"):
            content["text"] = scrub_text(content["text"])
        count += 1
    dst.write_text(json.dumps(har, indent=1), encoding="utf-8")
    return count


def main(src: str, dst: str) -> None:
    count = redact_har(Path(src), Path(dst))
    print(f"redacted {count} entries -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
