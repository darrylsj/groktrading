"""Deterministic replay scorecard over the hot flow ledger.

Reads ``flow_ledger`` (and optional shadow marks) and counts:

- **first_print** — first time an OCC appears (by ``executed_at``, then ingest)
- **already_run** — later prints of the same OCC, or OCC in an optional set
- **stale_filtered** — rows that fail ``sit_match`` freshness at ``now``

Does **not** invent PnL, fills, or edge. ``pnl`` is always null.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from groktrading.feeds.shadow_marks import ShadowMark, ShadowMarkBook
from groktrading.flow_ledger import FlowLedger, FlowRow
from groktrading.sit_match import evaluate_sit_match_freshness
from groktrading.timeutil import as_utc

SCORECARD_NOTE = (
    "Deterministic first-print / already-run / stale-filtered counts. "
    "No invented PnL."
)


@dataclass(frozen=True)
class ReplayScorecard:
    stored: int
    first_print: int
    already_run: int
    stale_filtered: int
    marks_present: bool
    marked_rows: int
    unique_occ: int
    as_of: datetime

    def document(self) -> dict[str, Any]:
        return {
            "source": "flow_ledger_replay_scorecard",
            "note": SCORECARD_NOTE,
            "as_of": self.as_of.isoformat(),
            "stored": self.stored,
            "first_print": self.first_print,
            "already_run": self.already_run,
            "stale_filtered": self.stale_filtered,
            "unique_occ": self.unique_occ,
            "marks_present": self.marks_present,
            "marked_rows": self.marked_rows,
            "pnl": None,
            "places_orders": False,
        }


def _row_sort_key(row: FlowRow) -> tuple[datetime, datetime, int]:
    return (row.executed_at, row.ingested_at, row.row_id or 0)


def scorecard(
    ledger: FlowLedger,
    *,
    now: datetime,
    already_run_occs: Iterable[str] | None = None,
    marks: Iterable[ShadowMark] | None = None,
    mark_book: ShadowMarkBook | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 10_000,
) -> ReplayScorecard:
    """Classify stored rows. ``already_run_occs`` treats those OCC as already-run
    even on first appearance (session fact / skip-already-run).
    """
    stamp = as_utc(now)
    prior = {str(x).strip().upper() for x in (already_run_occs or ()) if str(x).strip()}
    rows = sorted(ledger.iter_recent(limit=limit), key=_row_sort_key)
    seen_occ: set[str] = set()
    first = 0
    already = 0
    stale = 0
    for row in rows:
        occ = row.occ.upper()
        if occ in prior or occ in seen_occ:
            already += 1
        else:
            first += 1
        seen_occ.add(occ)
        gate = evaluate_sit_match_freshness(row.executed_at, stamp, env=env)
        if not gate.allow:
            stale += 1
    mark_rows = 0
    marks_present = False
    if marks is not None:
        mark_list = list(marks)
        marks_present = True
        mark_rows = len(mark_list)
    elif mark_book is not None:
        mark_list = list(mark_book.iter_recent(limit=limit))
        marks_present = True
        mark_rows = len(mark_list)
    return ReplayScorecard(
        stored=len(rows),
        first_print=first,
        already_run=already,
        stale_filtered=stale,
        marks_present=marks_present,
        marked_rows=mark_rows,
        unique_occ=len(seen_occ),
        as_of=stamp,
    )
