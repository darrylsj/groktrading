#!/usr/bin/env python3
"""Normalize TradeMachine Today XHR (tm_get_today2_strategy_results) → idea_board.v0_1."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ACTION = "tm_get_today2_strategy_results"
TEMPLATE_LABELS = {
    "credit_the_selloff": "Credit the Sell-Off",
    "etf_14day_credit": "ETF Put Credit Spread",
    "etf_2_days_up_diagonal": "ETF 2-Days-Up Diagonal",
    "fade_the_dip_short_putspread": "Fade the Dip Short Put Spread",
    "sma_200_jumper": "SMA 200 Jumper",
}


def _pt_stamp() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def _status(row: dict) -> str:
    if int(row.get("isActive") or 0) == 1:
        return "Active"
    return "Near Active"


def rows_from_har(har_path: Path) -> tuple[list[dict], str]:
    har = json.loads(har_path.read_text(encoding="utf-8"))
    best = None
    endpoint = f"GET /wp-admin/admin-ajax.php?action={ACTION}"
    for entry in har.get("log", {}).get("entries", []):
        url = (entry.get("request") or {}).get("url") or ""
        if ACTION not in url:
            continue
        text = ((entry.get("response") or {}).get("content") or {}).get("text") or ""
        if not text.strip().startswith("["):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list) and (best is None or len(data) >= len(best)):
            best = data
    if best is None:
        raise SystemExit(f"no {ACTION} JSON array in {har_path}")
    return best, endpoint


def rows_from_json(path: Path) -> tuple[list[dict], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, f"file:{path.name}"
    if isinstance(data, dict) and isinstance(data.get("ideas"), list):
        return [], f"already_normalized:{path.name}"
    raise SystemExit(f"unsupported JSON shape in {path}")


def normalize(rows: list[dict], *, endpoint: str, har_note: str | None = None) -> dict:
    ideas = []
    for row in rows:
        template = row.get("templateType") or ""
        ideas.append(
            {
                "ticker": row.get("ticker"),
                "strategy": TEMPLATE_LABELS.get(template, template or None),
                "status": _status(row),
                "direction": None,
                "legs": [],
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
                },
            }
        )
    active = sum(1 for idea in ideas if idea.get("status") == "Active")
    notes = [
        "Normalized from TradeMachine Today XHR (tm_get_today2_strategy_results).",
        "Shadow/paper only — scraper does not place orders.",
        "no_invented_prices: legs/entry left null unless attach_live_option_quotes "
        "payload is supplied separately.",
    ]
    if har_note:
        notes.append(har_note)
    return {
        "schema": "idea_board.v0_1",
        "source": "trademachine",
        "as_of_pt": _pt_stamp(),
        "source_url": "https://www.trademachine.com/",
        "login_health": "AUTHENTICATED",
        "mode": "n/a",
        "board": "Today",
        "ideas": ideas,
        "counts": {"ideas": len(ideas), "active": active},
        "screenshots": [],
        "notes": notes,
        "no_invented_prices": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--har",
        type=Path,
        help="HAR containing tm_get_today2_strategy_results",
    )
    parser.add_argument(
        "--json",
        type=Path,
        dest="json_path",
        help="Raw JSON array from that endpoint",
    )
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    if args.har:
        rows, endpoint = rows_from_har(args.har)
        note = f"Source HAR: {args.har.as_posix()}"
    elif args.json_path:
        rows, endpoint = rows_from_json(args.json_path)
        if not rows:
            print("input already normalized; copy manually", file=sys.stderr)
            sys.exit(2)
        note = f"Source JSON: {args.json_path.as_posix()}"
    else:
        parser.error("need --har or --json")
    board = normalize(rows, endpoint=endpoint, har_note=note)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "ideas": board["counts"]["ideas"],
                "active": board["counts"]["active"],
            }
        )
    )


if __name__ == "__main__":
    main()
