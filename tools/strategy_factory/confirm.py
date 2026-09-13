"""Allowlisted confirmations. Never invent prices or call a broker."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from groktrading.timeutil import UTC, as_utc
from tools.strategy_factory.config import CONFIRMATION_SOURCES, FactoryError

# Structured price / P&L keys are refused. Prose notes may cite an already
# observed print; this tool does not invent or fetch a quote.
PRICE_FIELD_NAMES = frozenset(
    {
        "ask",
        "bid",
        "decision_ask",
        "fill",
        "fill_price",
        "invented_price",
        "last",
        "limit",
        "mark",
        "mark_bid",
        "mid",
        "nbbo",
        "p_l",
        "pl",
        "pnl",
        "premium",
        "price",
    }
)

_HYP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def assert_hyp_id(hyp_id: str) -> str:
    text = hyp_id.strip()
    if not _HYP_ID.fullmatch(text):
        raise FactoryError(
            "bad_hyp_id",
            "hyp id must be 1–80 chars of A-Za-z0-9._- and start alphanumeric",
        )
    return text


def isoformat(now: datetime) -> str:
    return as_utc(now).isoformat()


def parse_now(raw: str | datetime | None) -> datetime:
    if raw is None:
        return datetime.now(tz=UTC)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raise FactoryError("now_naive", "--now must be timezone-aware ISO-8601")
        return as_utc(raw)
    text = str(raw).strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise FactoryError("now_naive", "--now must be timezone-aware ISO-8601")
    return as_utc(parsed)


def assert_no_invented_prices(payload: Mapping[str, Any]) -> None:
    for key in payload:
        norm = str(key).strip().lower().replace("-", "_")
        if norm in PRICE_FIELD_NAMES:
            raise FactoryError(
                "invented_price_forbidden",
                f"refusing price field {key!r}; cite an existing source, do not invent quotes",
            )


@dataclass(frozen=True)
class Confirmation:
    source: str
    note: str
    confirmed_at: str
    evidence_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "note": self.note,
            "confirmed_at": self.confirmed_at,
            "evidence_ref": self.evidence_ref,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Confirmation:
        assert_no_invented_prices(raw)
        source = str(raw.get("source", "")).strip()
        if source not in CONFIRMATION_SOURCES:
            raise FactoryError("unknown_source", f"confirmation source not allowlisted: {source}")
        note = str(raw.get("note", "")).strip()
        confirmed_at = str(raw.get("confirmed_at", "")).strip()
        if not confirmed_at:
            raise FactoryError("confirm_invalid", "confirmation requires confirmed_at")
        evidence_ref = str(raw.get("evidence_ref", "") or "").strip()
        return cls(
            source=source,
            note=note,
            confirmed_at=confirmed_at,
            evidence_ref=evidence_ref,
        )


def parse_confirmation(
    *,
    source: str,
    note: str = "",
    evidence_ref: str = "",
    now: datetime | str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Confirmation:
    payload = dict(extra or {})
    payload.update(
        {
            "source": source,
            "note": note,
            "evidence_ref": evidence_ref,
            "confirmed_at": isoformat(parse_now(now)),
        }
    )
    return Confirmation.from_dict(payload)


def unique_sources(confirmations: list[Confirmation]) -> frozenset[str]:
    return frozenset(item.source for item in confirmations)
