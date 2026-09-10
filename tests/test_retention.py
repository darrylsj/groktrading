from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from groktrading.flow_ledger import FlowLedger
from groktrading.retention import (
    RetentionError,
    bound_jsonl,
    retain_hot_window,
)
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _row(extra: str = "") -> dict[str, str]:
    body = {
        "executed_at": "2026-09-09T16:29:40Z",
        "ticker": "NVDA",
        "occ": "NVDA260918P00170000",
        "print": "1.00",
        "nbbo_ask": "1.05",
        "option_type": "put",
    }
    if extra:
        body["k"] = extra
    return body


def test_purge_fail_closed_without_verify_or_confirm() -> None:
    ledger = FlowLedger(":memory:", clock=FrozenClock())
    ledger.append_row(_row("old"), ingested_at=NOW - timedelta(days=10))
    with pytest.raises(RetentionError, match="verified"):
        retain_hot_window(ledger, now=NOW, keep_days=7)


def test_verified_purge_and_jsonl_bound(tmp_path: Path) -> None:
    ledger = FlowLedger(":memory:", clock=FrozenClock())
    ledger.append_row(_row("old"), ingested_at=NOW - timedelta(days=10))
    ledger.append_row(_row("hot"), ingested_at=NOW)
    jsonl = tmp_path / "flow_alerts_material.jsonl"
    jsonl.write_text("".join(f'{{"n":{i}}}\n' for i in range(20)), encoding="utf-8")
    result = retain_hot_window(
        ledger,
        now=NOW,
        keep_days=7,
        verified=True,
        jsonl_paths=[jsonl],
        jsonl_keep_lines=5,
        jsonl_max_bytes=10,
    )
    assert result.purged_rows == 1
    assert result.jsonl[0].trimmed is True
    assert result.jsonl[0].lines_after == 5
    kept = list(ledger.iter_recent(limit=10))
    assert len(kept) == 1
    assert kept[0].raw_digest


def test_bound_jsonl_no_file(tmp_path: Path) -> None:
    missing = tmp_path / "none.jsonl"
    result = bound_jsonl(missing)
    assert result.existed is False
    assert result.trimmed is False


def test_script_dry_run_requires_guard(tmp_path: Path) -> None:
    from scripts_loader import hot_ledger_retain_script

    ledger_path = tmp_path / "uw_flow.sqlite"
    FlowLedger(ledger_path, clock=FrozenClock())
    out = tmp_path / "plan.json"
    rc = hot_ledger_retain_script.main(
        [
            "--ledger",
            str(ledger_path),
            "--state-dir",
            str(tmp_path),
            "--keep-hot-days",
            "7",
            "--dry-run",
            "--json-out",
            str(out),
        ]
    )
    assert rc == 2
    rc_ok = hot_ledger_retain_script.main(
        [
            "--ledger",
            str(ledger_path),
            "--state-dir",
            str(tmp_path),
            "--keep-hot-days",
            "7",
            "--dry-run",
            "--verified",
            "--json-out",
            str(out),
        ]
    )
    assert rc_ok == 0
    text = out.read_text(encoding="utf-8")
    assert "keep_hot_days" in text
    assert "YOUR_" not in text
    assert "token=" not in text.lower()
