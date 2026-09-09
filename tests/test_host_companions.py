"""Offline smoke for Helsinki urllib host companions. No live UW. No secrets."""

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from groktrading.flow_ledger import FlowLedger
from groktrading.timeutil import UTC
from scripts_loader import (
    flow_alerts_companion,
    flow_ledger_companion,
    helsinki_http,
    quote_interest_companion,
    screener_companion,
    tide_companion,
)

ROOT = Path(__file__).resolve().parents[1]
COMPANION_SCRIPTS = (
    "scripts/helsinki_http.py",
    "scripts/flow_ledger_companion.py",
    "scripts/flow_alerts_companion.py",
    "scripts/tide_companion.py",
    "scripts/screener_companion.py",
    "scripts/quote_interest_companion.py",
)


def test_companions_are_secret_free_urllib() -> None:
    http_text = (ROOT / "scripts" / "helsinki_http.py").read_text(encoding="utf-8")
    assert "class UrllibHttp" in http_text
    assert "import httpx" not in http_text
    assert "httpx" not in http_text
    assert "urllib.request" in http_text
    for relative in COMPANION_SCRIPTS:
        path = ROOT / relative
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text
        assert "AKIA" not in text
        assert "ghp_" not in text
        assert "import httpx" not in text
        lowered = text.lower()
        assert any(
            needle in lowered
            for needle in (
                "never places orders",
                "never orders",
                "does not place orders",
                "no_orders",
                "never logs tokens",
            )
        ), relative
    for relative in COMPANION_SCRIPTS[1:]:
        path = ROOT / relative
        assert path.stat().st_mode & 0o111, relative


def test_helsinki_http_is_urllib_not_httpx() -> None:
    assert hasattr(helsinki_http, "UrllibHttp")
    assert not hasattr(helsinki_http, "HelsinkiHttp")
    client = helsinki_http.UrllibHttp(timeout=2.0)
    assert client.timeout == 2.0


def test_flow_ledger_bearer_is_runtime_env_only(monkeypatch: Any) -> None:
    monkeypatch.setenv("UW_API_KEY", "runtime-only")
    headers = flow_ledger_companion._uw_headers()
    assert headers["Authorization"] == "Bearer runtime-only"
    assert headers["Accept"] == "application/json"
    monkeypatch.setenv("UW_API_KEY", "   ")
    try:
        flow_ledger_companion._uw_headers()
    except SystemExit as exc:
        assert "UW_API_KEY" in str(exc)
    else:
        raise AssertionError("blank UW_API_KEY must fail closed")


def test_missing_uw_key_fails_closed_without_loop(monkeypatch: Any) -> None:
    monkeypatch.delenv("UW_API_KEY", raising=False)
    assert flow_alerts_companion.main() == 2
    assert tide_companion.main() == 2
    assert screener_companion.main() == 2


def test_flow_alerts_companion_defaults_are_closed() -> None:
    text = (ROOT / "scripts" / "flow_alerts_companion.py").read_text(encoding="utf-8")
    assert "emit_sit_match=False" in text
    assert "No Grok webhook" in text or "no_webhook" in text


def test_quote_interest_one_pass_writes_state(tmp_path: Path, monkeypatch: Any) -> None:
    ledger = tmp_path / "uw_flow.sqlite"
    FlowLedger(ledger)
    state = tmp_path / "quote_interest.json"
    monkeypatch.setenv("FLOW_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("QUOTE_INTEREST_STATE_PATH", str(state))
    monkeypatch.setenv("QUOTE_INTEREST_POLL_SEC", "15")

    def _stop(_interval: float) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(quote_interest_companion.time, "sleep", _stop)
    try:
        quote_interest_companion.main()
    except SystemExit as exc:
        assert exc.code in (0, None)
    assert state.is_file()
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert doc.get("mode") == "host_companion"
    assert "ws_tape.py" in (ROOT / "scripts" / "quote_interest_companion.py").read_text(
        encoding="utf-8"
    )


def test_quote_interest_seed_helpers() -> None:
    assert quote_interest_companion._seed_symbols({}) == []
    assert quote_interest_companion._seed_symbols({"QUOTE_INTEREST_SEED": "spy, qqq"}) == [
        "SPY",
        "QQQ",
    ]
    assert quote_interest_companion._env_float("MISSING", 9.0) == 9.0
    now = datetime(2026, 9, 9, 14, 30, tzinfo=UTC)
    assert now.tzinfo is UTC


def _serve_redirect() -> tuple[HTTPServer, list[str | None]]:
    sink_auth: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/from":
                self.send_response(302)
                self.send_header("Location", "/sink")
                self.end_headers()
                return
            if self.path == "/sink":
                sink_auth.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"followed":true}')
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, sink_auth


def test_urllib_redirect_does_not_resend_authorization() -> None:
    server, sink_auth = _serve_redirect()
    try:
        url = f"http://127.0.0.1:{server.server_port}/from"
        headers = {"Authorization": "Bearer test-token-not-production"}
        status, body = helsinki_http.UrllibHttp(timeout=2.0).get_json(url, headers)
        assert status == 302
        assert body in ({}, None)
        ledger_status, ledger_body = flow_ledger_companion._get_json(url, headers)
        assert ledger_status == 302
        assert ledger_body in ({}, None)
        assert sink_auth == []
    finally:
        server.shutdown()
        server.server_close()
