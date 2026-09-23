"""Synthetic leaks must not survive redact_har. Raw HARs stay out of git."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest

from tools.idea_board_scrape.redact_har import RedactError, redact_har

ROOT = Path(__file__).resolve().parents[1]


def _har(entry: dict, pages: list | None = None) -> dict:
    return {
        "log": {
            "version": "1.2",
            "pages": pages
            or [
                {
                    "id": "page_1",
                    "title": "https://trade.options.ai/cb?access_token=LEAKME",
                }
            ],
            "entries": [entry],
        }
    }


def _write(path: Path, har: dict) -> None:
    path.write_text(json.dumps(har), encoding="utf-8")


def test_redact_strips_cookie_token_query_and_page_title(tmp_path: Path) -> None:
    src = tmp_path / "raw.har"
    dst = tmp_path / "tm_REDACTED.har"
    body = json.dumps([{"ticker": "BAC", "token": "super-secret-token"}])
    _write(
        src,
        _har(
            {
                "request": {
                    "method": "GET",
                    "url": (
                        "https://www.trademachine.com/wp-admin/admin-ajax.php"
                        "?action=tm_get_today2_strategy_results&token=raw-token"
                    ),
                    "headers": [{"name": "Cookie", "value": "session=raw"}],
                    "cookies": [{"name": "session", "value": "raw"}],
                    "queryString": [{"name": "token", "value": "raw-token"}],
                },
                "response": {
                    "status": 200,
                    "headers": [{"name": "Content-Type", "value": "application/json"}],
                    "cookies": [],
                    "content": {"text": body},
                    "redirectURL": "",
                },
            }
        ),
    )
    assert redact_har(src, dst) == 1
    text = dst.read_text(encoding="utf-8")
    assert "raw-token" not in text
    assert "super-secret-token" not in text
    assert "LEAKME" not in text
    assert "session=raw" not in text


def test_synthetic_header_form_redirect_and_base64_leaks(tmp_path: Path) -> None:
    src = tmp_path / "in.har"
    dst = tmp_path / "out_REDACTED.har"
    encoded = base64.b64encode(b'{"api_key":"base64-secret-value"}').decode("ascii")
    _write(
        src,
        _har(
            {
                "request": {
                    "method": "POST",
                    "url": "https://api.options.ai/ideas",
                    "headers": [
                        {"name": "X-API-Key", "value": "header-secret-value"},
                        {
                            "name": "Referer",
                            "value": "https://trade.options.ai/back?token=referer-secret",
                        },
                    ],
                    "cookies": [],
                    "postData": {
                        "mimeType": "application/x-www-form-urlencoded",
                        "text": "password=form-secret&ticker=AAPL",
                        "params": [{"name": "api_key", "value": "param-secret"}],
                    },
                },
                "response": {
                    "status": 302,
                    "headers": [
                        {
                            "name": "Location",
                            "value": "https://trade.options.ai/cb?access_token=location-secret",
                        }
                    ],
                    "cookies": [],
                    "redirectURL": "https://trade.options.ai/cb?token=redirect-secret",
                    "content": {
                        "encoding": "base64",
                        "mimeType": "application/json",
                        "text": encoded,
                    },
                },
            }
        ),
    )
    redact_har(src, dst)
    text = dst.read_text(encoding="utf-8")
    for leak in (
        "header-secret-value",
        "referer-secret",
        "form-secret",
        "param-secret",
        "location-secret",
        "redirect-secret",
        "base64-secret-value",
        "LEAKME",
    ):
        assert leak not in text, leak
    har = json.loads(text)
    content = har["log"]["entries"][0]["response"]["content"]
    assert content.get("encoding") in {None, ""}
    assert "base64-secret-value" not in content.get("text", "")


def test_unsupported_encoding_fails_closed(tmp_path: Path) -> None:
    src = tmp_path / "in.har"
    dst = tmp_path / "out_REDACTED.har"
    _write(
        src,
        _har(
            {
                "request": {
                    "method": "GET",
                    "url": "https://www.trademachine.com/x",
                    "headers": [],
                },
                "response": {
                    "status": 200,
                    "content": {"encoding": "gzip", "text": "not-really-gzip-but-secret"},
                },
            }
        ),
    )
    with pytest.raises(RedactError, match="unsupported HAR content encoding"):
        redact_har(src, dst)
    assert not dst.exists()


def test_raw_destination_name_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "in.har"
    dst = tmp_path / "raw.har"
    _write(src, _har({"request": {"url": "https://example.test"}, "response": {}}))
    with pytest.raises(RedactError, match="raw HAR"):
        redact_har(src, dst)


def test_git_tree_has_no_har_files() -> None:
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    leaked = [line for line in raw.splitlines() if line.endswith(".har")]
    assert leaked == []
