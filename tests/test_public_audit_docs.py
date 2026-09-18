"""Documentation contracts for onboarding, operator policy, and audit packs."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CURRENT_POLICY = ROOT / "docs" / "CURRENT_POLICY.md"
WEBSOCKETS = ROOT / "docs" / "WEBSOCKETS.md"
PLANES = ROOT / "docs" / "REALTIME_PLANES.md"
PLANES_AUDIT = ROOT / "docs" / "astra_realtime_planes_audit_20260912.md"
STO_UNLOCK = ROOT / "docs" / "STO_UNLOCK_PLAN.md"
AUDIT = ROOT / "docs" / "OPENAI_AUDIT_BRIEF.md"
CLAUDE_AUDIT = ROOT / "docs" / "CLAUDE_AUDIT.md"
LICENSE = ROOT / "LICENSE"


def test_readme_explains_workflow_and_implementation_boundaries() -> None:
    text = README.read_text(encoding="utf-8")
    assert text.startswith("# GrokTrading\n")
    assert text.find("Continual15") < text.find("Opening15")
    # Keep the entry point useful without requiring historical incident prose.
    for needle in (
        "## How a trade works",
        "## What is implemented",
        "## Try it locally",
        "signals_only",
        "operator-gated",
        "Live orders are never placed by default",
        "not financial advice",
        "StaticSkipLLM",
        "groktrading.gate.evaluate_gate",
        "tools/live_order_gate",
        "two different gate layers",
        "matching_ask_tolerance=0",
        "SIT_MATCH_MAX_AGE_SEC=60",
        "SOFT 180s",
        "capital expansion",
        "$25,000",
        "Planning capital ≠ current broker equity",
        "docs/CURRENT_POLICY.md",
        "docs/LIVE_ORDER_GATE.md",
        "docs/SAFETY.md",
        "docs/OBSERVED_DEPLOYMENT.md",
        "docs/STRATEGY_FACTORY.md",
        "docs/SHADOW_BETS.md",
        "docs/OPENAI_AUDIT_BRIEF.md",
        "docs/CLAUDE_AUDIT.md",
    ):
        assert needle in text, needle


def test_current_policy_preserves_dated_operator_card() -> None:
    text = CURRENT_POLICY.read_text(encoding="utf-8")
    for needle in (
        "2026-09-17 PT",
        "≥20%",
        "80%",
        "NEW-ENTRY CUTOFF ONLY",
        "Overnight long options: ALLOWED",
        "CRON_TZ=America/New_York",
        "KEEP_PAUSED",
        "HARD ±$0.02",
        "SOFT 180s",
        "60s",
        "META / NET / MU / AMD",
        "1.25",
        "0.50",
        "UW MCP: DEFERRED",
        "SCORE-ONLY",
        "stale_event>30s",
        "QQQ260911P00717000",
        "not in `logs/trades.jsonl`",
        "STO_UNLOCK_PLAN.md",
        "2026-09-19 is Saturday",
        "09:00 through 15:55 ET",
    ):
        assert needle in text.replace("**", ""), needle


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
        "print_age_sec",
        "emitted_at",
        "prepare_sit_match_outbound",
        "SIT_MATCH_MAX_AGE_SEC",
        "SIT_MATCH_MIN_INTERVAL_SEC",
        "SIT_MATCH_WEBHOOK",
        "sit_match_webhook_muted",
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
        "REALTIME_PLANES",
        "deprecated as hunt bus",
        "shortlist.json",
        "three planes",
        "issue_types[]=ETF",
        "dashboard/",
        "READ-ONLY",
        "DASHBOARD.md",
        "LIVE_BOARD_REFRESH.md",
    ):
        assert needle in text, needle


def test_sto_unlock_plan_is_linked_from_readme_and_policy() -> None:
    """Keep the current hold visible; detailed history belongs in the plan."""
    readme = README.read_text(encoding="utf-8")
    for needle in (
        "docs/STO_UNLOCK_PLAN.md",
        "still refused",
        "Naked STO stays refused",
        "KEEP_PAUSED",
    ):
        assert needle in readme, needle
    policy = CURRENT_POLICY.read_text(encoding="utf-8")
    assert "Fri 2026-09-19 I4 review" in policy
    assert "intended review date needs operator confirmation" in policy
    text = STO_UNLOCK.read_text(encoding="utf-8")
    for needle in (
        "2026-09-12",
        "Tue 2026-09-15 RTH",
        "Wed 2026-09-16",
        "Fri 2026-09-19 I4 review",
        "Did not unlock",
        "defined-risk I4",
        "Naked STO",
        "allowlist",
        "live_order_gate",
        "no raw POST",
        "≤3 RTH days",
        "reconcile-book",
        "Wheel",
        "PASS-WITH-FIXES",
        "cash floor",
        "WebSocket",
        "tools/i4_credit_paper",
        "gpt-6-astra",
        "gate still single-leg submit",
        "confirmed fills (not ack=closed)",
        "American / physical",
        "deterministic lifecycle test",
        "Trading Bot on Wed open checklist PASS",
        "pause blocks new entries, preserves exits",
        "do not keep a forever ban",
    ):
        assert needle in text, needle
    assert "forever ban" in text.lower()
    stub = (ROOT / "tools" / "i4_credit_paper" / "README.md").read_text(encoding="utf-8")
    assert "STO_UNLOCK_PLAN.md" in stub
    assert "Not an executor" in stub


def test_realtime_planes_doc_states_design() -> None:
    text = PLANES.read_text(encoding="utf-8")
    for needle in (
        "Three-plane",
        "Hot sensor",
        "Thin ranker",
        "Continual15",
        "shortlist.json",
        "/opt/trading-desk/state/shortlist.json",
        "SIT_MATCH_MAX_AGE_SEC",
        "SIT_MATCH_MIN_INTERVAL_SEC",
        "not the trading latency target",
        "not the realtime design",
        "Do **not** raise",
        "SIT_MATCH_WEBHOOK",
        "emit_sit_match",
        "Merge ≠ Helsinki restart",
        "5–15s",
        "META",
        "SPCX",
        "INTC",
        "in_position",
        "login_dead",
        "not auto-enabled",
        "issue_types[]=ETF",
        "`sit_match` stays OFF",
        "SHORTLIST_OPP_MAX_AGE_SEC",
        "TOP1_ONLY",
        "Continual15 + `shortlist.json`",
        "/opt/trading-desk/bin/shortlist_opportunity_webhook.py",
        "yes_latency_fix_wake",
        "dashboard/",
        "DASHBOARD.md",
        "LIVE_BOARD_REFRESH.md",
        "does **not** unmute `sit_match`",
    ):
        assert needle in text, needle
    audit = PLANES_AUDIT.read_text(encoding="utf-8")
    for needle in (
        "## A)",
        "## B)",
        "## C)",
        "## D)",
        "## E)",
        "## F)",
        "421.74",
        "460.56",
        "PR #34",
        "PR #35",
        "PR #36",
        "Weekend-muted",
        "shortlist + Continual15",
        "shortlist_stale",
        "America/New_York",
        "invented=false",
    ):
        assert needle in audit, needle


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


def test_dashboard_doc_states_hard_rules() -> None:
    text = (ROOT / "docs" / "DASHBOARD.md").read_text(encoding="utf-8")
    for needle in (
        "uw_opportunity_refuses.jsonl",
        "ws_stats",
        "finnhub_tape.json",
        "flow_n",
        "READ-ONLY",
        "No new WebSocket subscriptions",
        "sit_match",
        "shortlist_opportunity",
        "darrylsj/trading-desk-live-board",
        "Vercel",
        "WEBSOCKETS.md",
        "REALTIME_PLANES.md",
        "Never invent",
        "live_order_gate",
        "tests/fixtures/dashboard",
    ):
        assert needle in text, needle
    readme = (ROOT / "dashboard" / "README.md").read_text(encoding="utf-8")
    assert "No new WebSocket subscriptions" in readme
    assert "sit_match` stays OFF" in readme


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
