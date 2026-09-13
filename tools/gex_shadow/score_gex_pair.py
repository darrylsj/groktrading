"""Paired GEX shadow scorer: decision-time ask → later bid, ~60 minutes.

Reads scorecard / candidate records that already have a decision ask, a GEX
tag (agree / fight / na), and an optional later bid mark. Computes one-lot
ask→bid dollars for the baseline set vs the agree-only subset.

Rules:
- Never invent marks. Missing marks are unscored; coverage is reported.
- Deduplicate OCC (first record wins).
- ``live_gate`` is always false. This is a shadow research scorer only.
- Fixture / synthetic marks must set ``invented`` false and may set
  ``fixture`` true so they are never mistaken for live NBBO.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from groktrading.quote_gate import normalize_occ
from groktrading.timeutil import as_utc

LIVE_GATE = False
DEFAULT_HORIZON_MIN = 60
CONTRACT_MULTIPLIER = Decimal("100")
GEX_TAGS = frozenset({"agree", "fight", "na"})
SCORE_NOTE = (
    "Shadow GEX pair score. live_gate=false always. Missing marks are unscored. "
    "Marks are never invented. Kill if this becomes a live gate."
)


class ScoreError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class PairRecord:
    occ: str
    decision_ask: Decimal | None
    gex: str
    mark_bid: Decimal | None
    decision_ts: datetime | None
    mark_ts: datetime | None
    invented: bool
    fixture: bool
    skip_reason: str | None = None

    @property
    def scored(self) -> bool:
        return (
            self.skip_reason is None
            and not self.invented
            and self.decision_ask is not None
            and self.mark_bid is not None
        )

    def one_lot_usd(self) -> Decimal | None:
        if not self.scored or self.decision_ask is None or self.mark_bid is None:
            return None
        return (self.mark_bid - self.decision_ask) * CONTRACT_MULTIPLIER


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Mapping):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _parse_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return as_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return as_utc(parsed)


def _dig(raw: Mapping[str, Any], *paths: str) -> object:
    for path in paths:
        cur: object = raw
        ok = True
        for key in path.split("."):
            if not isinstance(cur, Mapping) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return cur
    return None


def _norm_gex(value: object) -> str:
    text = str(value or "na").strip().lower()
    if text in GEX_TAGS:
        return text
    return "na"


def parse_pair_record(raw: Mapping[str, Any]) -> PairRecord | None:
    occ_raw = _dig(
        raw, "occ", "option_symbol", "symbol", "candidate.occ", "candidate.option_symbol"
    )
    occ = normalize_occ(str(occ_raw or ""))
    if not occ:
        return None
    ask = _parse_decimal(
        _dig(raw, "decision_ask", "ask", "entry_ask", "proposed_limit", "decision.ask")
    )
    bid = _parse_decimal(
        _dig(raw, "mark_bid", "later_bid", "bid_60m", "horizon_bid", "mark.bid")
    )
    gex = _norm_gex(_dig(raw, "gex", "gex_tag", "gex_label") or "na")
    invented = _parse_bool(raw.get("invented"), default=False)
    fixture = _parse_bool(raw.get("fixture"), default=False)
    skip: str | None = None
    if invented:
        skip = "invented_mark"
    elif ask is None:
        skip = "missing_decision_ask"
    elif bid is None:
        skip = "missing_mark"
    return PairRecord(
        occ=occ,
        decision_ask=ask,
        gex=gex,
        mark_bid=bid,
        decision_ts=_parse_dt(
            _dig(raw, "decision_ts", "decision_time", "written_at", "decision.ts")
        ),
        mark_ts=_parse_dt(_dig(raw, "mark_ts", "mark_time", "later_ts", "mark.ts")),
        invented=invented,
        fixture=fixture,
        skip_reason=skip,
    )


def load_records(path: Path | str) -> list[Mapping[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped[0] in "{[":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, list):
            return [row for row in doc if isinstance(row, Mapping)]
        if isinstance(doc, Mapping):
            for key in ("records", "candidates", "lines", "rows"):
                inner = doc.get(key)
                if isinstance(inner, list):
                    return [row for row in inner if isinstance(row, Mapping)]
            return [doc]
    rows: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        parsed = json.loads(item)
        if isinstance(parsed, Mapping):
            rows.append(parsed)
    return rows


def dedupe_occ(records: Iterable[PairRecord]) -> tuple[list[PairRecord], int]:
    seen: set[str] = set()
    out: list[PairRecord] = []
    dropped = 0
    for rec in records:
        if rec.occ in seen:
            dropped += 1
            continue
        seen.add(rec.occ)
        out.append(rec)
    return out, dropped


def _subset_stats(rows: Sequence[PairRecord]) -> dict[str, Any]:
    scored = [row for row in rows if row.scored]
    pnls = [row.one_lot_usd() for row in scored]
    values = [p for p in pnls if p is not None]
    n = len(values)
    hits = sum(1 for p in values if p > 0)
    total = sum(values, start=Decimal("0")) if values else Decimal("0")
    mean = (total / Decimal(n)) if n else None
    return {
        "n_scored": n,
        "hits": hits,
        "hit_rate": str(Decimal(hits) / Decimal(n)) if n else None,
        "one_lot_usd_sum": str(total) if n else None,
        "one_lot_usd_mean": str(mean) if mean is not None else None,
    }


def score_gex_pairs(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    horizon_min: int = DEFAULT_HORIZON_MIN,
) -> dict[str, Any]:
    parsed = [rec for rec in (parse_pair_record(row) for row in raw_rows) if rec is not None]
    unique, dropped = dedupe_occ(parsed)
    scored = [row for row in unique if row.scored]
    missing_mark = sum(1 for row in unique if row.skip_reason == "missing_mark")
    missing_ask = sum(1 for row in unique if row.skip_reason == "missing_decision_ask")
    invented = sum(1 for row in unique if row.skip_reason == "invented_mark")
    universe = len(unique)
    coverage = (Decimal(len(scored)) / Decimal(universe)) if universe else None
    agree = [row for row in unique if row.gex == "agree"]
    return {
        "kind": "gex_shadow_pair_score",
        "live_gate": LIVE_GATE,
        "horizon_min": horizon_min,
        "invented": False,
        "places_orders": False,
        "note": SCORE_NOTE,
        "baseline": _subset_stats(unique),
        "agree_only": _subset_stats(agree),
        "coverage": {
            "unique_occ": universe,
            "scored": len(scored),
            "unscored_missing_mark": missing_mark,
            "unscored_missing_ask": missing_ask,
            "unscored_invented": invented,
            "duplicate_occ_dropped": dropped,
            "coverage_ratio": str(coverage) if coverage is not None else None,
        },
        "fixture_rows": sum(1 for row in unique if row.fixture),
    }


def score_gex_pairs_document(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    horizon_min: int = DEFAULT_HORIZON_MIN,
) -> dict[str, Any]:
    return score_gex_pairs(raw_rows, horizon_min=horizon_min)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gex_shadow",
        description=(
            "Shadow GEX 60-minute paired scorer. Never invents marks. live_gate=false."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        help="JSONL or JSON array of scorecard / candidate records.",
    )
    parser.add_argument(
        "--horizon-min",
        type=int,
        default=DEFAULT_HORIZON_MIN,
        help="Mark horizon in minutes (default 60). Labels the score; marks are not invented.",
    )
    parser.add_argument("--out", default=None, help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.horizon_min <= 0:
        print(
            json.dumps(
                {
                    "kind": "gex_shadow_error",
                    "allowed": False,
                    "reasons": ["horizon_min_invalid"],
                    "live_gate": LIVE_GATE,
                    "places_orders": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    try:
        rows = load_records(args.input)
        doc = score_gex_pairs(rows, horizon_min=args.horizon_min)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "kind": "gex_shadow_error",
                    "allowed": False,
                    "reasons": ["input_unreadable"],
                    "note": str(exc),
                    "live_gate": LIVE_GATE,
                    "places_orders": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except ScoreError as exc:
        print(
            json.dumps(
                {
                    "kind": "gex_shadow_error",
                    "allowed": False,
                    "reasons": [exc.code],
                    "note": str(exc),
                    "live_gate": LIVE_GATE,
                    "places_orders": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    text = json.dumps(doc, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
