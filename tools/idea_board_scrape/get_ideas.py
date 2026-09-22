#!/usr/bin/env python3
"""Get-ideas pipeline: TradeMachine + Options AI → idea_board.v0_1 + ledger + shadow pointer.

Modes:
  --from-har PATH     Normalize a captured HAR (preferred repeatable offline path).
  --from-board PATH   Re-ledger an existing idea_board.v0_1 JSON.
  --source NAME       trademachine | options_ai | both (both requires two --from-har via config).

Live browser pull is intentionally NOT done here (box-desktop: CDP/GUI belongs to computerUse).
Use tools/idea_board_scrape/cdp_har_capture.js via computerUse, then re-run this CLI.

Shadow/paper only. Never places broker orders. Do not wire this path to live Tradier submit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.idea_board_scrape.normalize_trademachine import (
    normalize as tm_normalize,
)
from tools.idea_board_scrape.normalize_trademachine import (
    rows_from_har as tm_rows_from_har,
)

ROOT = Path(__file__).resolve().parents[2]
BOARD_DIR = ROOT / "evidence" / "idea_boards"
LEDGER = BOARD_DIR / "idea_board_ledger.jsonl"
SHADOW = ROOT / "state" / "idea_board_latest.json"
PT = ZoneInfo("America/Los_Angeles")


def _stamp_files() -> str:
    return datetime.now(PT).strftime("%Y%m%d_%H%M_pt")


def _append_ledger(event: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")


def _write_shadow(boards: list[dict]) -> None:
    SHADOW.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "idea_board_shadow.v0_1",
        "as_of_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT"),
        "sources": [board.get("source") for board in boards],
        "boards": [
            {
                "source": board.get("source"),
                "board": board.get("board"),
                "login_health": board.get("login_health"),
                "counts": board.get("counts"),
                "path": board.get("_path"),
                "tickers": [
                    idea.get("ticker")
                    for idea in (board.get("ideas") or [])
                    if idea.get("ticker")
                ],
            }
            for board in boards
        ],
        "desk_use": "shadow_only_continual15_shortlist_candidate_feed",
        "no_live_orders_from_scraper": True,
    }
    SHADOW.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _normalize_options_ai_har(har_path: Path) -> dict:
    """Best-effort Options AI normalize until a confirmed idea endpoint exists.

    2026-09-21 HAR had no dedicated idea XHR; QuickStrike ideas were DOM.
    This heuristic only accepts JSON that already looks like an idea list.
    """
    har = json.loads(har_path.read_text(encoding="utf-8"))
    candidates = []
    for entry in har.get("log", {}).get("entries", []):
        request = entry.get("request") or {}
        url = request.get("url") or ""
        if "clickoptions.ai" in url:
            continue
        text = ((entry.get("response") or {}).get("content") or {}).get("text") or ""
        content_type = ""
        for header in (entry.get("response") or {}).get("headers") or []:
            if header.get("name", "").lower() == "content-type":
                content_type = header.get("value") or ""
        if "json" not in content_type.lower() and not text.strip().startswith(("{", "[")):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        score = 0
        sample = data
        if isinstance(data, dict):
            for key in ("ideas", "strategies", "setups", "trades", "results", "data", "items"):
                if isinstance(data.get(key), list) and data[key]:
                    sample = data[key]
                    score += 5
                    break
        if isinstance(sample, list) and sample and isinstance(sample[0], dict):
            keys = {str(key).lower() for key in sample[0].keys()}
            if keys & {"ticker", "symbol", "underlying", "strategy", "name", "type"}:
                score += 10 + min(len(sample), 50)
                candidates.append((score, url, sample, request.get("method")))
    if not candidates:
        raise SystemExit(
            "options_ai: no idea-like JSON found in HAR yet — finish triage first "
            f"({har_path})"
        )
    candidates.sort(key=lambda item: -item[0])
    score, url, sample, method = candidates[0]
    ideas = []
    for row in sample:
        ticker = row.get("ticker") or row.get("symbol") or row.get("underlying")
        strategy = (
            row.get("strategy") or row.get("name") or row.get("type") or row.get("strategyName")
        )
        status = row.get("status") or row.get("state") or "Available"
        ideas.append(
            {
                "ticker": ticker,
                "strategy": strategy,
                "status": status,
                "direction": row.get("direction") or row.get("bias"),
                "legs": [],
                "entry": {"display": None, "mid": None},
                "ui_fields": {
                    "source_endpoint": f"{method} {url.split('?')[0]}",
                    "raw_keys": sorted(row.keys())[:40],
                },
            }
        )
    active_states = {"active", "near active", "triggered"}
    active = sum(1 for idea in ideas if str(idea.get("status", "")).lower() in active_states)
    return {
        "schema": "idea_board.v0_1",
        "source": "options_ai",
        "as_of_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT"),
        "source_url": "https://trade.options.ai/",
        "login_health": "AUTHENTICATED",
        "mode": "paper",
        "board": "Trade",
        "ideas": ideas,
        "counts": {"ideas": len(ideas), "active": active},
        "screenshots": [],
        "notes": [
            f"Heuristic normalize from HAR {har_path.as_posix()} (score={score}).",
            "Promote endpoints to Confirmed in options_ai_xhr_triage before trusting automation.",
            "Shadow/paper only — scraper does not place orders.",
        ],
        "no_invented_prices": True,
    }


def run_one(source: str, har: Path | None, board_path: Path | None) -> dict:
    stamp = _stamp_files()
    if board_path:
        board = json.loads(board_path.read_text(encoding="utf-8"))
        schema = str(board.get("schema", ""))
        if not schema.startswith("idea_board"):
            raise SystemExit(f"not an idea_board JSON: {board_path}")
        out = board_path
    else:
        if not har:
            raise SystemExit(f"{source}: need --from-har or --from-board")
        if source == "trademachine":
            rows, endpoint = tm_rows_from_har(har)
            board = tm_normalize(rows, endpoint=endpoint, har_note=f"Source HAR: {har.as_posix()}")
        elif source == "options_ai":
            board = _normalize_options_ai_har(har)
        else:
            raise SystemExit(f"unknown source {source}")
        out = BOARD_DIR / f"{source}_{stamp}.json"
        out.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    board = json.loads(out.read_text(encoding="utf-8")) if board_path else board
    board["_path"] = str(out.relative_to(ROOT)) if out.is_absolute() else str(out)
    markdown = out.with_suffix(".md")
    if not markdown.exists():
        lines = [
            f"# {source} ideas — {board.get('as_of_pt')}",
            "",
            f"- login_health: `{board.get('login_health')}`",
            f"- board: `{board.get('board')}`",
            f"- counts: `{board.get('counts')}`",
            f"- json: `{board['_path']}`",
            "",
            "| ticker | strategy | status |",
            "|---|---|---|",
        ]
        for idea in board.get("ideas") or []:
            lines.append(
                f"| {idea.get('ticker')} | {idea.get('strategy')} | {idea.get('status')} |"
            )
        markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _append_ledger(
        {
            "ts_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT"),
            "event": "get_ideas",
            "source": source,
            "board": board.get("board"),
            "path": board["_path"],
            "counts": board.get("counts"),
            "login_health": board.get("login_health"),
            "mode": "shadow_paper_only",
        }
    )
    return board


def _source_for_har(path: Path, forced: str) -> str:
    name = path.name.lower()
    if "option" in name:
        inferred = "options_ai"
    elif "trade" in name or "tm_" in name or "today" in name:
        inferred = "trademachine"
    else:
        inferred = "trademachine" if forced != "options_ai" else "options_ai"
    if forced != "both" and inferred != forced:
        return forced
    return inferred


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["trademachine", "options_ai", "both"], default="both")
    parser.add_argument(
        "--from-har",
        type=Path,
        action="append",
        default=[],
        help="HAR path (repeat; pair with --source or infer from filename)",
    )
    parser.add_argument(
        "--from-board",
        type=Path,
        action="append",
        default=[],
        help="Existing idea_board JSON to re-ledger",
    )
    parser.add_argument("--no-shadow", action="store_true")
    args = parser.parse_args()

    boards: list[dict] = []
    if args.from_board:
        for path in args.from_board:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            boards.append(run_one(loaded.get("source") or "unknown", None, path))
    elif args.from_har:
        for path in args.from_har:
            boards.append(run_one(_source_for_har(path, args.source), path, None))
    else:
        default_tm = BOARD_DIR / "har" / "trademachine_today_20260921_0910_pt_REDACTED.har"
        if args.source in ("trademachine", "both") and default_tm.exists():
            boards.append(run_one("trademachine", default_tm, None))
        har_dir = BOARD_DIR / "har"
        oai_hars = sorted(har_dir.glob("options_ai*_REDACTED.har")) if har_dir.exists() else []
        if args.source in ("options_ai", "both"):
            if oai_hars:
                boards.append(run_one("options_ai", oai_hars[-1], None))
            elif args.source == "options_ai":
                raise SystemExit("no options_ai HAR yet — run computerUse capture first")
            else:
                print("note: options_ai HAR missing — TM only this run", file=sys.stderr)
        if not boards:
            raise SystemExit("nothing to normalize — pass --from-har or capture first")

    if not args.no_shadow:
        _write_shadow(boards)

    summary = {
        "ok": True,
        "boards": [
            {
                "source": board.get("source"),
                "path": board.get("_path"),
                "counts": board.get("counts"),
            }
            for board in boards
        ],
        "ledger": str(LEDGER.relative_to(ROOT)),
        "shadow": None if args.no_shadow else str(SHADOW.relative_to(ROOT)),
        "no_live_orders_from_scraper": True,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
