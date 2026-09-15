"""READ-ONLY book and open-order snapshots.

Never invents prices, marks, or P&L. Copies only identity / qty / side /
status plus already-named fill or limit fields. Bid / ask / mid / mark
are not treated as a book. Missing files are reported holes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dashboard.config import (
    BOOK_KIND,
    BOOK_SCHEMA,
    LIVE_GATE,
    ORDERS_KIND,
    ORDERS_SCHEMA,
    PLACES_ORDERS,
    DashboardError,
)
from groktrading.quote_gate import normalize_occ
from groktrading.sit_match import parse_executed_at

# Broker-cited fields only. Never derive a mid/mark from bid+ask.
_CITED_PRICE_KEYS = (
    "limit",
    "limit_price",
    "avg_fill",
    "avg_fill_price",
    "cost_basis",
    "fill_price",
)
_QTY_KEYS = ("qty", "quantity", "open_qty", "filled_qty")
_SIDE_KEYS = ("side", "action", "order_side")
_STATUS_KEYS = ("status", "state", "order_status")
_ID_KEYS = ("id", "order_id", "tag", "signal_id")
_BOOK_LIST_KEYS = ("positions", "lots", "holdings", "rows")
_ORDER_LIST_KEYS = ("orders", "open_orders", "working_orders", "rows")


def _named(value: object) -> str:
    return str(value or "").strip()


def _load_json(path: Path | None) -> tuple[Mapping[str, Any] | list[Any] | None, str | None]:
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
        raise DashboardError("book_invalid_json", f"invalid JSON: {target}") from exc
    if isinstance(doc, (Mapping, list)):
        return doc, None
    return None, "unknown_shape"


def _extract_occ(row: Mapping[str, Any]) -> str | None:
    raw = row.get("occ") or row.get("option_symbol") or row.get("symbol")
    text = _named(raw)
    if not text:
        return None
    occ = normalize_occ(text)
    if len(occ) < 5 or not occ.isalnum():
        return None
    # Underlyings (SPY) are allowed on a book; OCC-shaped tokens stay as-is.
    return occ


def _as_qty(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return text
    return None


def _cited_prices(row: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _CITED_PRICE_KEYS:
        raw = row.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"none", "null", "nan"}:
            out[key] = text
    return out


def _first_named(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = _named(row.get(key))
        if text:
            return text
    return None


def _row_time(row: Mapping[str, Any]) -> str | None:
    for key in ("executed_at", "updated_at", "as_of", "created_at", "submitted_at"):
        parsed = parse_executed_at(row.get(key))
        if parsed is not None:
            return parsed.isoformat().replace("+00:00", "Z")
    return None


def _position_snapshot(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("invented") is True:
        return None
    occ = _extract_occ(row)
    qty = None
    for key in _QTY_KEYS:
        qty = _as_qty(row.get(key))
        if qty is not None:
            break
    if occ is None and qty is None:
        return None
    snap: dict[str, Any] = {
        "occ": occ,
        "qty": qty,
        "side": (_first_named(row, _SIDE_KEYS) or "").lower() or None,
        "status": _first_named(row, _STATUS_KEYS),
        "invented": False,
    }
    underlying = _named(row.get("underlying")).upper()
    if underlying:
        snap["underlying"] = underlying
    when = _row_time(row)
    if when:
        snap["as_of"] = when
    snap.update(_cited_prices(row))
    return snap


def _order_snapshot(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("invented") is True:
        return None
    occ = _extract_occ(row)
    qty = None
    for key in _QTY_KEYS:
        qty = _as_qty(row.get(key))
        if qty is not None:
            break
    side = _first_named(row, _SIDE_KEYS)
    status = _first_named(row, _STATUS_KEYS)
    if occ is None and qty is None and not side and not status:
        return None
    snap: dict[str, Any] = {
        "occ": occ,
        "qty": qty,
        "side": (side or "").lower() or None,
        "status": status,
        "invented": False,
    }
    order_id = _first_named(row, _ID_KEYS)
    if order_id:
        snap["id"] = order_id
    when = _row_time(row)
    if when:
        snap["as_of"] = when
    snap.update(_cited_prices(row))
    return snap


def _list_from(doc: Mapping[str, Any] | list[Any] | None, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, Mapping)]
    if not isinstance(doc, Mapping):
        return []
    for key in keys:
        nested = doc.get(key)
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, Mapping)]
    account = doc.get("account")
    if isinstance(account, Mapping):
        for key in keys:
            nested = account.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, Mapping)]
    return []


def _cited_cash(doc: Mapping[str, Any] | list[Any] | None) -> str | None:
    if not isinstance(doc, Mapping):
        return None
    for key in ("cash", "cash_available", "cash_balance"):
        raw = doc.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        text = str(raw).strip()
        if text and text.lower() not in {"none", "null", "nan"}:
            return text
    return None


def _empty_book(empty_reason: str | None) -> dict[str, Any]:
    return {
        "kind": BOOK_KIND,
        "schema": BOOK_SCHEMA,
        "present": False,
        "empty_reason": empty_reason,
        "positions": [],
        "cash": None,
        "source": None,
        "pnl": None,
        "invented": False,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "note": (
            "Book unknown on this host. Not invented. "
            "Positions are copied only when a local book file or live_tape "
            "positions list is present."
        ),
    }


def _empty_orders(empty_reason: str | None) -> dict[str, Any]:
    return {
        "kind": ORDERS_KIND,
        "schema": ORDERS_SCHEMA,
        "present": False,
        "empty_reason": empty_reason,
        "orders": [],
        "source": None,
        "invented": False,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "note": (
            "Open orders unknown on this host. Not invented. "
            "Copied only when a local orders file or live_tape open_orders "
            "list is present. This refresh never places orders."
        ),
    }


def build_book(
    book: Path | None = None,
    *,
    live_tape: Path | None = None,
) -> dict[str, Any]:
    """Snapshot positions. Missing inputs are holes, not invented lots."""
    doc, empty = _load_json(book)
    source = "book"
    if doc is None and live_tape is not None:
        tape, tape_empty = _load_json(live_tape)
        rows = _list_from(tape, _BOOK_LIST_KEYS)
        if rows:
            doc = {"positions": rows, **(tape if isinstance(tape, Mapping) else {})}
            empty = None
            source = "live_tape"
        elif tape is None:
            if empty == "no_input":
                empty = tape_empty
        else:
            empty = "unknown_shape"
    if doc is None:
        return _empty_book(empty)
    rows = _list_from(doc, _BOOK_LIST_KEYS)
    if not rows and isinstance(doc, Mapping) and _extract_occ(doc):
        rows = [doc]
    positions = [snap for row in rows if (snap := _position_snapshot(row))]
    if not positions and not _cited_cash(doc):
        hole = _empty_book("unknown_shape")
        hole["source"] = source
        return hole
    return {
        "kind": BOOK_KIND,
        "schema": BOOK_SCHEMA,
        "present": True,
        "empty_reason": None,
        "positions": positions,
        "cash": _cited_cash(doc),
        "source": source,
        "pnl": None,
        "invented": False,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "note": (
            "READ-ONLY cited book. P&L is always null here. "
            "Bid/ask/mid/mark are not copied as prices."
        ),
    }


def build_open_orders(
    open_orders: Path | None = None,
    *,
    live_tape: Path | None = None,
) -> dict[str, Any]:
    """Snapshot working orders. Missing inputs are holes, not invented tickets."""
    doc, empty = _load_json(open_orders)
    source = "open_orders"
    if doc is None and live_tape is not None:
        tape, tape_empty = _load_json(live_tape)
        rows = _list_from(tape, _ORDER_LIST_KEYS)
        if rows:
            doc = {"orders": rows}
            empty = None
            source = "live_tape"
        elif tape is None:
            if empty == "no_input":
                empty = tape_empty
        else:
            empty = "unknown_shape"
    if doc is None:
        return _empty_orders(empty)
    rows = _list_from(doc, _ORDER_LIST_KEYS)
    if not rows and isinstance(doc, Mapping) and (
        _extract_occ(doc) or _first_named(doc, _SIDE_KEYS) or _first_named(doc, _STATUS_KEYS)
    ):
        rows = [doc]
    orders = [snap for row in rows if (snap := _order_snapshot(row))]
    if not orders:
        hole = _empty_orders("unknown_shape")
        hole["source"] = source
        return hole
    return {
        "kind": ORDERS_KIND,
        "schema": ORDERS_SCHEMA,
        "present": True,
        "empty_reason": None,
        "orders": orders,
        "source": source,
        "invented": False,
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "note": (
            "READ-ONLY cited open orders. This refresh never places, "
            "cancels, or replaces tickets."
        ),
    }
