"""Offline smoke for Helsinki host companions. No live network. No secrets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from groktrading.feeds.quote_subscribe import TradierQuoteInterest
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


def test_companions_are_executable_and_secret_free() -> None:
    for relative in COMPANION_SCRIPTS:
        path = ROOT / relative
        assert path.is_file()
        assert path.stat().st_mode & 0o111, relative
        text = path.read_text(encoding="utf-8")
        assert "Never places orders" in text or "never places orders" in text.lower()
        assert "sk-" not in text
        assert "AKIA" not in text
        assert "ghp_" not in text


def test_helsinki_http_bearer_is_runtime_env_only() -> None:
    text = (ROOT / "scripts" / "helsinki_http.py").read_text(encoding="utf-8")
    assert "Authorization Bearer is runtime env only" in text or "runtime env only" in text
    assert 'f"Bearer {token}"' in text
    assert helsinki_http.uw_token({"UW_API_KEY": "  "}) == ""
    headers = helsinki_http.authorization_headers("runtime-only")
    assert headers["Authorization"] == "Bearer runtime-only"


def test_argparse_help_needs_no_secrets_or_network() -> None:
    for module in (
        flow_ledger_companion,
        flow_alerts_companion,
        tide_companion,
        screener_companion,
        quote_interest_companion,
    ):
        parser = module.build_parser()
        help_text = parser.format_help()
        collapsed = " ".join(help_text.lower().split())
        assert "places orders" in collapsed
        assert "never places orders" in module.NEVER_ORDERS_NOTE.lower()
        assert "YOUR_" not in help_text


def test_flow_alerts_companion_defaults_are_closed() -> None:
    assert flow_alerts_companion.EMIT_SIT_MATCH is False
    parser = flow_alerts_companion.build_parser()
    args = parser.parse_args([])
    assert args.webhook_firehose is False


def test_quote_interest_refresh_offline(tmp_path: Path) -> None:
    ledger = FlowLedger(tmp_path / "uw_flow.sqlite")
    now = datetime(2026, 9, 9, 14, 30, tzinfo=UTC)
    ledger.append_row(
        {
            "executed_at": "2026-09-09T14:29:50Z",
            "ticker": "SPY",
            "option_chain": "SPY260909C00600000",
            "price": "1.25",
            "ask": "1.26",
            "type": "call",
        },
        source="flow-alerts",
        ingested_at=now,
    )
    interest = TradierQuoteInterest(bound=8, idle_ttl_seconds=900)
    doc = quote_interest_companion.refresh(ledger, interest, now=now, env={})
    assert doc["places_orders"] is False
    assert doc["emits_sit_match"] is False
    assert doc["live_http"] is False
    assert doc["live_socket"] is False
    assert "never places orders" in str(doc["note"]).lower()


def test_quote_interest_once_writes_state(tmp_path: Path) -> None:
    ledger = tmp_path / "uw_flow.sqlite"
    FlowLedger(ledger)
    state = tmp_path / "quote_interest.json"
    assert quote_interest_companion.main(
        ["--ledger", str(ledger), "--state", str(state), "--once"]
    ) == 0
    assert state.is_file()
    text = state.read_text(encoding="utf-8")
    assert "tradier_quote_interest" in text
    assert "ws_tape.py" in text
