"""Paper recorder and reconciler.

Production Tradier NBBO is pricing truth. Sandbox fills are delayed
artifacts. Records are tagged with signal_id and require preview-before-order.
The paper JSON ledger is same-session (one PT date) so a file does not mix
two paper days. That is not a live flatten: overnight long options remain
allowed on the live card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from groktrading.io_atomic import write_json_atomic
from groktrading.models import PaperFillArtifact
from groktrading.timeutil import session_date_pt


@dataclass
class PaperLedger:
    path: Path
    session: date
    artifacts: list[PaperFillArtifact] = field(default_factory=list)

    def record(self, artifact: PaperFillArtifact, now: datetime) -> None:
        if session_date_pt(now) != self.session:
            raise ValueError("paper ledger is same-day only; open a new ledger next session")
        if not artifact.previewed:
            raise ValueError("preview-before-order is required")
        if not artifact.signal_id:
            raise ValueError("signal_id is required")
        self.artifacts.append(artifact)
        self._persist(now)

    def reconcile(self, artifact: PaperFillArtifact) -> dict[str, Any]:
        """Compare sandbox fill vs production NBBO. Does not invent P&L."""
        fill = artifact.sandbox_fill_price
        truth = artifact.production_nbbo_ask
        delta: Decimal | None
        if fill is None:
            delta = None
            note = "no_sandbox_fill_yet"
        else:
            delta = fill - truth
            note = "sandbox_fill_minus_production_ask"
        return {
            "signal_id": artifact.signal_id,
            "option_symbol": artifact.option_symbol,
            "production_nbbo_bid": str(artifact.production_nbbo_bid),
            "production_nbbo_ask": str(artifact.production_nbbo_ask),
            "sandbox_fill_price": None if fill is None else str(fill),
            "sandbox_minus_production_ask": None if delta is None else str(delta),
            "note": note,
            "disclaimer": "Not P&L. Sandbox data is delayed; production NBBO is pricing truth.",
        }

    def mark_terminal(self, signal_id: str, now: datetime) -> None:
        found = False
        updated: list[PaperFillArtifact] = []
        for row in self.artifacts:
            if row.signal_id == signal_id:
                updated.append(row.model_copy(update={"terminal": True}))
                found = True
            else:
                updated.append(row)
        if not found:
            raise KeyError(signal_id)
        self.artifacts = updated
        self._persist(now)

    def _persist(self, now: datetime) -> None:
        if session_date_pt(now) != self.session:
            raise ValueError("cannot persist paper state across sessions")
        payload = {
            "session_date_pt": self.session.isoformat(),
            "as_of": now.isoformat(),
            "same_day_only": True,
            "artifacts": [a.model_dump(mode="json") for a in self.artifacts],
        }
        write_json_atomic(self.path, payload)
