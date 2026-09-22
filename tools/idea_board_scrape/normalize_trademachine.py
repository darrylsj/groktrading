#!/usr/bin/env python3
"""Normalize TradeMachine Today XHR (tm_get_today2_strategy_results) → idea_board.v0_1.

A row is accepted only from host www.trademachine.com (or trademachine.com),
method GET, exact action tm_get_today2_strategy_results, and HTTP 200.
The latest such response wins. Observation time comes from that entry, not
from extract time. HTTP 401 is never AUTHENTICATED.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ACTION = "tm_get_today2_strategy_results"
LEG_ACTION = "tm_get_strategy_result"
TM_HOSTS = frozenset({"www.trademachine.com", "trademachine.com"})
DEFAULT_MAX_AGE = timedelta(hours=12)
FIXED_DEFAULT_HAR = "trademachine_today_20260921_0910_pt_REDACTED.har"
TEMPLATE_LABELS = {
    "credit_the_selloff": "Credit the Sell-Off",
    "etf_14day_credit": "ETF Put Credit Spread",
    "etf_2_days_up_diagonal": "ETF 2-Days-Up Diagonal",
    "fade_the_dip_short_putspread": "Fade the Dip Short Put Spread",
    "sma_200_jumper": "SMA 200 Jumper",
}


@dataclass
class TmExtract:
    rows: list[dict]
    endpoint: str
    observed_at: datetime
    http_status: int
    login_health: str
    legs_by_key: dict[str, list[dict]] = field(default_factory=dict)


def _pt_stamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise SystemExit("TradeMachine observation time must be timezone-aware")
    return dt.astimezone(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def _status(row: dict) -> str:
    if int(row.get("isActive") or 0) == 1:
        return "Active"
    return "Near Active"


def _status_rank(status: str) -> int:
    if status == "Active":
        return 0
    if status == "Near Active":
        return 1
    return 2


def _query(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _started(entry: dict, index: int) -> tuple[datetime, int] | None:
    raw = str(entry.get("startedDateTime") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC), index


def _json_body(entry: dict) -> object | None:
    text = ((entry.get("response") or {}).get("content") or {}).get("text") or ""
    if not str(text).strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _is_board_request(entry: dict) -> bool:
    request = entry.get("request") or {}
    url = str(request.get("url") or "")
    if _host(url) not in TM_HOSTS:
        return False
    if str(request.get("method") or "").upper() != "GET":
        return False
    action = (_query(url).get("action") or [""])[0]
    return action == ACTION


def _is_leg_request(entry: dict) -> bool:
    request = entry.get("request") or {}
    url = str(request.get("url") or "")
    if _host(url) not in TM_HOSTS:
        return False
    if str(request.get("method") or "").upper() != "GET":
        return False
    query = _query(url)
    if (query.get("action") or [""])[0] != LEG_ACTION:
        return False
    return "attach_live_option_quotes" in query


def _map_leg(row: dict) -> dict | None:
    """Map an Open_ tradeList row. Closing marks are not the idea."""
    description = str(row.get("description") or "")
    if not description.startswith("Open_"):
        return None
    try:
        size = float(row.get("size"))
    except (TypeError, ValueError):
        return None
    if size == 0:
        return None
    right_raw = str(row.get("type") or "").strip().lower()
    right = {"call": "C", "put": "P"}.get(right_raw)
    price = row.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        display_price = None
    else:
        display_price = price
    return {
        "side": "LONG" if size > 0 else "SHORT",
        "expiry": None,
        "strike": row.get("strike"),
        "right": right,
        "display_price": display_price,
        "expiration_label": row.get("expiration"),
    }


def _legs_from_body(body: object) -> list[dict]:
    if not isinstance(body, dict):
        return []
    portfolio = body.get("portfolio") if isinstance(body.get("portfolio"), dict) else body
    trade_list = portfolio.get("tradeList") if isinstance(portfolio, dict) else None
    if not isinstance(trade_list, list):
        return []
    legs = []
    for row in trade_list:
        if not isinstance(row, dict):
            continue
        mapped = _map_leg(row)
        if mapped is not None:
            legs.append(mapped)
    return legs


def rows_from_har(
    har_path: Path,
    *,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
    allow_stale: bool = False,
) -> TmExtract:
    """Return the latest valid Today-board response and any joined Open_ legs."""
    if har_path.name == FIXED_DEFAULT_HAR and not allow_stale:
        raise SystemExit(
            "refusing fixed default HAR "
            f"{FIXED_DEFAULT_HAR}; pass a fresh capture (no baked-in HAR)"
        )
    har = json.loads(har_path.read_text(encoding="utf-8"))
    entries = (har.get("log") or {}).get("entries") or []
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise SystemExit("now must be timezone-aware")

    board_hits: list[tuple[tuple[datetime, int], dict, list]] = []
    saw_401 = False
    leg_hits: list[tuple[tuple[datetime, int], str, str, list[dict]]] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        started = _started(entry, index)
        status = int((entry.get("response") or {}).get("status") or 0)
        request = entry.get("request") or {}
        url = str(request.get("url") or "")
        if _is_board_request(entry):
            if status == 401:
                saw_401 = True
                continue
            if status != 200 or started is None:
                continue
            body = _json_body(entry)
            if not isinstance(body, list):
                continue
            board_hits.append((started, entry, body))
        elif _is_leg_request(entry) and status == 200 and started is not None:
            query = _query(url)
            share_key = (query.get("share_key") or query.get("shareKey") or [""])[0]
            ticker = (query.get("ticker") or [""])[0].upper()
            leg_hits.append((started, share_key, ticker, _legs_from_body(_json_body(entry))))

    if not board_hits:
        if saw_401:
            raise SystemExit(
                "TradeMachine NOT_AUTHENTICATED: HTTP 401 is not an authenticated board "
                f"(empty 401 arrays are not AUTHENTICATED) in {har_path}"
            )
        raise SystemExit(
            "no GET 200 tm_get_today2_strategy_results on www.trademachine.com "
            f"with a timezone-aware startedDateTime in {har_path}"
        )

    board_hits.sort(key=lambda item: item[0])
    started, _entry, rows = board_hits[-1]
    observed_at = started[0]
    age = clock - observed_at
    if age > max_age and not allow_stale:
        raise SystemExit(
            "TradeMachine HAR is stale: observation "
            f"{_pt_stamp(observed_at)} is older than {max_age}. "
            "Pass a fresh capture. There is no fixed default HAR."
        )
    if not allow_stale and age < timedelta(0) and abs(age) > timedelta(minutes=5):
        raise SystemExit("TradeMachine observation time is in the future")

    legs_by_key: dict[str, list[dict]] = {}
    leg_hits.sort(key=lambda item: item[0])
    for _when, share_key, ticker, legs in leg_hits:
        if share_key:
            legs_by_key[f"share:{share_key}"] = legs
        if ticker:
            legs_by_key[f"ticker:{ticker}"] = legs

    if rows:
        login_health = "AUTHENTICATED"
    else:
        login_health = "UNKNOWN"
    endpoint = f"GET https://www.trademachine.com/wp-admin/admin-ajax.php?action={ACTION}"
    return TmExtract(
        rows=rows,
        endpoint=endpoint,
        observed_at=observed_at,
        http_status=200,
        login_health=login_health,
        legs_by_key=legs_by_key,
    )


def rows_from_json(path: Path) -> tuple[list[dict], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, f"file:{path.name}"
    if isinstance(data, dict) and isinstance(data.get("ideas"), list):
        return [], f"already_normalized:{path.name}"
    raise SystemExit(f"unsupported JSON shape in {path}")


def _legs_for_row(row: dict, legs_by_key: dict[str, list[dict]]) -> list[dict]:
    share = str(row.get("shareKey") or row.get("share_key") or "")
    ticker = str(row.get("ticker") or "").upper()
    if share and f"share:{share}" in legs_by_key:
        return list(legs_by_key[f"share:{share}"])
    if ticker and f"ticker:{ticker}" in legs_by_key:
        return list(legs_by_key[f"ticker:{ticker}"])
    return []


def normalize(
    rows: list[dict],
    *,
    endpoint: str,
    observed_at: datetime,
    login_health: str,
    legs_by_key: dict[str, list[dict]] | None = None,
    har_note: str | None = None,
) -> dict:
    joined = legs_by_key or {}
    ideas = []
    for row in rows:
        template = row.get("templateType") or ""
        legs = _legs_for_row(row, joined)
        status = _status(row)
        ideas.append(
            {
                "ticker": row.get("ticker"),
                "strategy": TEMPLATE_LABELS.get(template, template or None),
                "status": status,
                "direction": None,
                "legs": legs,
                "entry": {"display": None, "mid": None},
                "ui_fields": {
                    "templateType": template,
                    "isActive": row.get("isActive"),
                    "triggeredToday": row.get("triggeredToday"),
                    "returnPercent": row.get("returnPercent"),
                    "winRate": row.get("winRate"),
                    "numWins": row.get("numWins"),
                    "numLosses": row.get("numLosses"),
                    "shareKey": row.get("shareKey"),
                    "source_endpoint": endpoint,
                    "legs_source": (
                        "tm_get_strategy_result+attach_live_option_quotes"
                        if legs
                        else "absent"
                    ),
                    "legs_missing": not legs,
                    "legs_expected": status == "Active",
                    "empty_legs_expected": status != "Active" and not legs,
                },
            }
        )
    ideas.sort(key=lambda idea: _status_rank(str(idea.get("status"))))
    active = sum(1 for idea in ideas if idea.get("status") == "Active")
    near_active = sum(1 for idea in ideas if idea.get("status") == "Near Active")
    notes = [
        "Normalized from TradeMachine Today XHR (exact tm_get_today2_strategy_results).",
        "Active rows are listed first. Trade only Active. Near Active is watch-only.",
        "as_of_pt is the source response time, not the extract time.",
        "Shadow/paper only — scraper does not place orders.",
        "no_invented_prices: entry.mid stays null. ISO expiry is not inferred from labels.",
        "Empty Near Active legs are expected (Show Options is an Active control).",
        "Empty Active legs mean the Show Options payload was absent, not a complete contract.",
    ]
    if login_health != "AUTHENTICATED":
        notes.append("Empty HTTP 200 array is not treated as AUTHENTICATED.")
    if har_note:
        notes.append(har_note)
    return {
        "schema": "idea_board.v0_1",
        "source": "trademachine",
        "as_of_pt": _pt_stamp(observed_at),
        "source_url": "https://www.trademachine.com/",
        "login_health": login_health,
        "mode": "n/a",
        "board": "Today",
        "ideas": ideas,
        "counts": {
            "ideas": len(ideas),
            "active": active,
            "near_active": near_active,
            "with_legs": sum(1 for idea in ideas if idea["legs"]),
        },
        "screenshots": [],
        "notes": notes,
        "no_invented_prices": True,
        "provenance": {
            "capture": "xhr_tm_get_today2_strategy_results",
            "observed_at_pt": _pt_stamp(observed_at),
            "observed_at_utc": observed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endpoint": endpoint,
            "http_status": 200,
            "execution_realm": "shadow",
            "authorizes_live_orders": False,
            "live_order_gate": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--har", type=Path, help="HAR containing tm_get_today2_strategy_results")
    parser.add_argument(
        "--json",
        type=Path,
        dest="json_path",
        help="Raw JSON array from that endpoint",
    )
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()
    if args.har:
        extracted = rows_from_har(args.har, allow_stale=args.allow_stale)
        board = normalize(
            extracted.rows,
            endpoint=extracted.endpoint,
            observed_at=extracted.observed_at,
            login_health=extracted.login_health,
            legs_by_key=extracted.legs_by_key,
            har_note=f"Source HAR: {args.har.name}",
        )
    elif args.json_path:
        rows, endpoint = rows_from_json(args.json_path)
        if not rows:
            print("input already normalized; copy manually", file=sys.stderr)
            raise SystemExit(2)
        board = normalize(
            rows,
            endpoint=endpoint,
            observed_at=datetime.now(UTC),
            login_health="UNKNOWN",
            har_note=f"Source JSON: {args.json_path.name}",
        )
    else:
        parser.error("need --har or --json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "ideas": board["counts"]["ideas"],
                "active": board["counts"]["active"],
                "with_legs": board["counts"]["with_legs"],
                "as_of_pt": board["as_of_pt"],
                "login_health": board["login_health"],
            }
        )
    )


if __name__ == "__main__":
    main()
