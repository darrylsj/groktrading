"""Guards for the public OpenAI / Claude audit packs and $25k YOLO framing."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
WEBSOCKETS = ROOT / "docs" / "WEBSOCKETS.md"
AUDIT = ROOT / "docs" / "OPENAI_AUDIT_BRIEF.md"
CLAUDE_AUDIT = ROOT / "docs" / "CLAUDE_AUDIT.md"
LICENSE = ROOT / "LICENSE"


def test_readme_leads_with_public_audit_and_yolo_mandate() -> None:
    text = README.read_text(encoding="utf-8")
    assert text.startswith("# GrokTrading\n")
    head = text[:2500]
    for needle in (
        "Public reference package",
        "external audit",
        "not financial advice",
        "operator-gated",
        "signals-only",
        "YOLO",
        "capital expansion",
        "$25,000",
        "Planning capital ≠ current broker equity",
        "docs/OPENAI_AUDIT_BRIEF.md",
        "docs/CLAUDE_AUDIT.md",
        "docs/WEBSOCKETS.md",
        "docs/SAFETY.md",
        "docs/ARCHITECTURE.md",
    ):
        assert needle in head, needle
    assert "Live orders are never placed by default" in text
    for needle in (
        "Helsinki sensor farm",
        "always-on listen",
        "Grok Bot only",
        "Box Trading Desk Archive",
        "SIT_MATCH_MAX_AGE_SEC",
        "position truth",
        "Grok Update Computer does not rebuild Helsinki",
        "flow_ledger",
        "account_events",
        "flow-alerts",
        "tide_state",
        "UW_WS_URL",
        "wire companion units",
    ):
        assert needle in text, needle
    # Primary frame is $25k; ~$600 must not be the lead sentence.
    assert "Tradier live cash on the order of **$600**" not in text


def test_websockets_doc_covers_auditor_topics() -> None:
    text = WEBSOCKETS.read_text(encoding="utf-8")
    for needle in (
        "Finnhub",
        "option NBBO",
        "trading-desk-tape",
        "feeds/",
        "never place live orders",
        "fresh Tradier production",
        "sit_match",
        "executed_at",
        "SIT_MATCH_MAX_AGE_SEC",
        "in_position",
        "cash_up",
        "entry_cutoff_only_no_flatten",
        "day_win_target",
        "auto_flatten: false",
        "backoff",
        "fail-closed",
        "HMAC",
        "digest",
        "weekend",
        "sequenceDiagram",
        "preview",
        "position truth",
        "account_events",
        "flow_ledger",
        "flow-alerts",
        "UW_WS_URL",
        "quote interest",
        "shadow marks",
        "replay scorecard",
    ):
        assert needle in text, needle


def test_openai_audit_brief_states_scope_and_ask() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    for needle in (
        "What to review",
        "What NOT to change",
        "overnight",
        "12:30",
        "No hard concurrent-position caps",
        "No daily-loser circuit breaker",
        "capital expansion",
        "$25k",
        "YOLO",
        "preserve capital",
        "SAFETY.md",
        "WEBSOCKETS.md",
        "ARCHITECTURE.md",
        "OPENING15_DECISION_PROTOCOL.md",
        "TUESDAY_EXECUTION_READINESS.md",
        "Not financial advice",
    ):
        assert needle in text, needle


def test_claude_audit_brief_states_scope_and_ask() -> None:
    text = CLAUDE_AUDIT.read_text(encoding="utf-8")
    for needle in (
        "What this repo is / is not",
        "public reference",
        "signals-only",
        "YOLO",
        "$25,000",
        "capital expansion",
        "not capital preservation",
        "Helsinki",
        "Grok Bot",
        "Opening15",
        "Codex CLI",
        "ChatGPT Pro",
        "WebSocket never places orders",
        "Overnight long options",
        "12:30 PT",
        "NEW-ENTRY CUTOFF ONLY",
        "≥20%",
        "Matching ask",
        "outside the broker",
        "15:55 ET",
        "baseline",
        "expanded",
        "Unusual Whales",
        "Tradier",
        "Finnhub",
        "pytest",
        "Schwab",
        "holdings-first",
        "preserve capital",
        "OPENAI_AUDIT_BRIEF.md",
        "WEBSOCKETS.md",
        "SAFETY.md",
        "OPENING15_EXPERIMENT.md",
        "TUESDAY_EXECUTION_READINESS.md",
        "OPENING15_DECISION_PROTOCOL.md",
        "GROK_RESEARCH_HANDOFF.md",
        "Not financial advice",
    ):
        assert needle in text, needle


def test_license_is_mit_for_public_github() -> None:
    text = LICENSE.read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "WITHOUT WARRANTY" in text


def test_forbidden_live_account_id_not_in_tracked_docs() -> None:
    """Do not publish the live production account number.

    The literal is assembled so this test file is not itself a leak.
    """
    forbidden = "6YB" + "72238"
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    leaked: list[str] = []
    for line in raw.splitlines():
        path = ROOT / line
        if path.suffix in {".png", ".jpg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if forbidden in text:
            leaked.append(line)
    assert leaked == []
