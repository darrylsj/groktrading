"""READ-ONLY WebSocket producer/consumer stats from Helsinki health files.

Hard rules:

- Does **not** open a socket or subscribe to any stream.
- Does **not** unmute ``sit_match``.
- Does **not** resume ``shortlist_opportunity``.
- Extracts health counters only. Does **not** copy prints, NBBO, or P&L
  from ``live_tape.json`` (host-owned shape; unknown keys are ignored).

CI must not claim Helsinki files exist. Missing paths are
``present=false`` with an ``empty_reason``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dashboard.config import (
    NEW_WS_SUBSCRIPTIONS,
    OPPORTUNITY_WEBHOOK_RESUME,
    PLACES_ORDERS,
    SIT_MATCH_STAYS_OFF,
    WS_STATS_KIND,
    WS_STATS_SCHEMA,
    DashboardError,
)

FINNHUB_NOT_NBBO = (
    "Finnhub is stock last prints only. Not option NBBO. "
    "Never gate option limits on Finnhub ticks."
)
READ_ONLY_NOTE = (
    "READ-ONLY snapshot. No new WebSocket subscriptions. "
    "sit_match stays OFF. shortlist_opportunity stays paused."
)


def _load_json(path: Path | None) -> tuple[Mapping[str, Any] | None, str | None]:
    if path is None:
        return None, "no_input"
    target = Path(path)
    if not target.is_file():
        return None, "file_missing"
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return None, "empty_file"
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DashboardError("tape_invalid_json", f"invalid JSON: {target}") from exc
    if not isinstance(doc, Mapping):
        return None, "unknown_shape"
    return doc, None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "connected", "ok", "1", "yes"}:
            return True
        if lowered in {"false", "disconnected", "stale", "0", "no"}:
            return False
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    return None


def _symbol_list(value: object) -> list[str]:
    if isinstance(value, str):
        token = value.strip().upper()
        return [token] if token.isalpha() or token.isalnum() else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, Mapping):
            raw = item.get("symbol") or item.get("ticker")
        else:
            raw = item
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        # Underlyings only — refuse OCC-shaped tokens so we do not leak
        # option series from a mis-shaped tape into the health snapshot.
        if len(symbol) > 6 and symbol.isalnum() and any(ch.isdigit() for ch in symbol):
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _freshness(doc: Mapping[str, Any]) -> dict[str, Any]:
    nested = doc.get("freshness")
    src = nested if isinstance(nested, Mapping) else doc
    stale = _as_bool(src.get("stale"))
    connected = _as_bool(doc.get("connected") if "connected" in doc else doc.get("connection"))
    last_event = src.get("last_event_ts") or src.get("last_event") or doc.get("as_of")
    ttl = src.get("freshness_ttl_seconds") or src.get("ttl_seconds") or src.get("freshness_ttl")
    ttl_n = None
    if isinstance(ttl, (int, float)) and ttl == ttl and ttl not in {float("inf"), float("-inf")}:
        ttl_n = float(ttl)
    return {
        "last_event_ts": str(last_event) if last_event not in (None, "") else None,
        "stale": stale,
        "ttl_seconds": ttl_n,
        "connected": connected,
        "detail": src.get("detail") or doc.get("detail") or doc.get("note"),
    }


def _finnhub_snapshot(path: Path | None) -> dict[str, Any]:
    doc, empty = _load_json(path)
    snap: dict[str, Any] = {
        "present": False,
        "empty_reason": empty,
        "path_provided": path is not None,
        "connected": None,
        "freshness": None,
        "symbols": [],
        "note": FINNHUB_NOT_NBBO,
    }
    if doc is None:
        return snap
    snap["present"] = True
    snap["empty_reason"] = None
    connected = _as_bool(doc.get("connected") if "connected" in doc else doc.get("connection"))
    snap["connected"] = connected
    snap["freshness"] = _freshness(doc)
    symbols = _symbol_list(doc.get("symbols") if "symbols" in doc else doc.get("watchlist"))
    snap["symbols"] = symbols
    return snap


def _flow_http(value: object) -> dict[str, Any] | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {}
    for key, raw in value.items():
        count = _as_int(raw)
        if count is not None:
            out[str(key)] = count
    return out or None


def _error_codes(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, int):
        return [f"count:{value}"]
    if not isinstance(value, list):
        return []
    codes: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            codes.append(item.strip())
        elif isinstance(item, Mapping):
            reason = item.get("reason") or item.get("code") or item.get("error")
            if reason not in (None, ""):
                codes.append(str(reason).strip())
    return codes


def _candidate_count(value: object) -> int | None:
    """Count only. Never copy OCC / premium / bid-ask off the tape."""
    if isinstance(value, list):
        return len(value)
    return _as_int(value)


def _live_tape_snapshot(path: Path | None) -> dict[str, Any]:
    doc, empty = _load_json(path)
    snap: dict[str, Any] = {
        "present": False,
        "empty_reason": empty,
        "path_provided": path is not None,
        "flow_n": None,
        "flow_http": None,
        "errors": [],
        "candidates": None,
        "keys_found": [],
        "note": (
            "Host-owned live_tape.json. Health counters only. "
            "Prints / NBBO / P&L are not copied. Unknown shapes stay empty."
        ),
    }
    if doc is None:
        return snap
    keys = ("flow_n", "flow_http", "errors", "candidates")
    found = [key for key in keys if key in doc]
    snap["keys_found"] = found
    if not found:
        snap["empty_reason"] = "unknown_shape"
        return snap
    snap["present"] = True
    snap["empty_reason"] = None
    if "flow_n" in doc:
        snap["flow_n"] = _as_int(doc.get("flow_n"))
    if "flow_http" in doc:
        snap["flow_http"] = _flow_http(doc.get("flow_http"))
    if "errors" in doc:
        snap["errors"] = _error_codes(doc.get("errors"))
    if "candidates" in doc:
        snap["candidates"] = _candidate_count(doc.get("candidates"))
    return snap


def build_ws_stats(
    *,
    finnhub_tape: Path | None = None,
    live_tape: Path | None = None,
) -> dict[str, Any]:
    """READ-ONLY health snapshot. Never opens a WebSocket."""
    finnhub = _finnhub_snapshot(finnhub_tape)
    live = _live_tape_snapshot(live_tape)
    missing: list[str] = []
    if not finnhub["present"]:
        missing.append("finnhub_tape")
    if not live["present"]:
        missing.append("live_tape")
    return {
        "kind": WS_STATS_KIND,
        "schema": WS_STATS_SCHEMA,
        "read_only": True,
        "new_subscriptions": NEW_WS_SUBSCRIPTIONS,
        "sit_match_unmute": False,
        "sit_match_stays_off": SIT_MATCH_STAYS_OFF,
        "opportunity_webhook_resume": OPPORTUNITY_WEBHOOK_RESUME,
        "places_orders": PLACES_ORDERS,
        "note": READ_ONLY_NOTE,
        "finnhub_tape": finnhub,
        "live_tape": live,
        "missing": missing,
    }
