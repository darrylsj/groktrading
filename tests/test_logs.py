"""Guards for committed, secret-free persistent logs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "logs" / "trades.jsonl"
CHANGELOG = ROOT / "CHANGELOG.md"

SEED_TRADE_IDS = (
    "2026-08-25-AMZN-265c",
    "2026-08-25-DRAM-57c",
    "2026-08-26-NVDA-225c",
    "2026-08-27-AAPL-312.5c",
    "2026-09-03-SPCX-145p",
)


def test_changelog_is_keep_a_changelog() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n")
    assert "https://keepachangelog.com/" in text
    assert "## [Unreleased]" in text
    assert "America/Los_Angeles" in text


def test_trades_jsonl_is_recorded_rows_only() -> None:
    raw = TRADES.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    assert [row["trade_id"] for row in rows] == list(SEED_TRADE_IDS)
    for row in rows:
        assert row["invented"] is False
        assert row["qty"] == 1
        assert "token" not in row
        assert "secret" not in row
        assert "api_key" not in row
