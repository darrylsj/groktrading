#!/usr/bin/env python3
"""Get-ideas pipeline: TradeMachine XHR + Options AI DOM boards → idea_board.v0_1.

Trade Machine: explicit ``--from-har`` only. No fixed default HAR.
Options AI HAR→ideas is disabled until a Confirmed idea endpoint exists.
Pass a validated DOM QuickStrike / Strategy Builder board with ``--from-board``.

``--source both`` requires one valid board per product. HAR and board inputs
are both kept. The shadow pointer is written only after every source succeeds.

Shadow metadata is not a live-order boundary. Adapters must require
paper/shadow provenance. This CLI never calls live_order_gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.idea_board_scrape.idea_card_map import board_to_idea_cards
from tools.idea_board_scrape.normalize_trademachine import normalize as tm_normalize
from tools.idea_board_scrape.normalize_trademachine import rows_from_har as tm_rows_from_har
from tools.idea_board_scrape.paper_lift import PAPER_API_BASE

ROOT = Path(__file__).resolve().parents[2]
BOARD_DIR = ROOT / "evidence" / "idea_boards"
LEDGER = BOARD_DIR / "idea_board_ledger.jsonl"
SHADOW = ROOT / "state" / "idea_board_latest.json"
PT = ZoneInfo("America/Los_Angeles")
OAI_HOSTS = frozenset({"trade.options.ai", "www.trade.options.ai"})
QUOTE_ONLY_MARKERS = ("expire-strikes", "chain-details", "/quotes")


@dataclass
class Job:
    source: str
    har: Path | None = None
    board: Path | None = None


def _stamp_files(now: datetime) -> str:
    return now.astimezone(PT).strftime("%Y%m%d_%H%M_pt")


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def refuse_options_ai_har(har_path: Path) -> None:
    """Never publish Options AI ideas from a HAR heuristic or chain XHR."""
    har = json.loads(har_path.read_text(encoding="utf-8"))
    saw_click = False
    saw_chain = False
    for entry in (har.get("log") or {}).get("entries") or []:
        request = entry.get("request") or {}
        url = str(request.get("url") or "")
        host = _host(url)
        path = urllib.parse.urlsplit(url).path.lower()
        if "clickoptions" in host or "clickoptions" in url.lower():
            saw_click = True
        if any(marker in path for marker in QUOTE_ONLY_MARKERS):
            saw_chain = True
    if saw_click:
        raise SystemExit(
            "options_ai: rejected ClickOptions / wrong host. "
            "Do not map api.clickoptions.ai into Options AI idea cards."
        )
    chain = ""
    if saw_chain:
        chain = (
            " Chain XHR (expire-strikes, chain-details, quotes) is quotes-only "
            "and was not mapped into idea cards."
        )
    raise SystemExit(
        "options_ai: HAR→ideas publication is disabled until a Confirmed idea endpoint exists. "
        "Refusing to invent Available/AUTHENTICATED/paper from JSON."
        + chain
        + " Pass a validated DOM QuickStrike or Strategy Builder board via --from-board."
    )


def validate_options_ai_dom_board(board: dict) -> dict:
    """Accept only an already-validated DOM QuickStrike or Strategy Builder board."""
    if not str(board.get("schema", "")).startswith("idea_board"):
        raise SystemExit("options_ai: not an idea_board JSON")
    if board.get("source") != "options_ai":
        raise SystemExit("options_ai: board source is not options_ai")
    url = str(board.get("source_url") or "")
    host = _host(url)
    if "clickoptions" in host or "clickoptions" in url.lower():
        raise SystemExit("options_ai: rejected ClickOptions / wrong host")
    if host not in OAI_HOSTS:
        raise SystemExit("options_ai: DOM board source_url must be trade.options.ai")
    board_name = str(board.get("board") or "")
    if re.search(r"quickstrike|strategy builder", board_name, re.I) is None:
        raise SystemExit(
            "options_ai: only validated DOM QuickStrike/Strategy Builder boards are accepted"
        )
    if board.get("mode") != "paper":
        raise SystemExit(
            "options_ai: mode must already be paper on the DOM board (not invented, and not live)"
        )
    if board.get("login_health") not in {"AUTHENTICATED", "NOT_AUTHENTICATED", "UNKNOWN"}:
        raise SystemExit("options_ai: login_health must already be present on the DOM board")
    ideas = board.get("ideas")
    if not isinstance(ideas, list) or not ideas:
        raise SystemExit("options_ai: DOM board has no ideas")
    for idea in ideas:
        if not isinstance(idea, dict):
            raise SystemExit("options_ai: idea is not an object")
        if not idea.get("ticker") or not idea.get("strategy") or not idea.get("status"):
            raise SystemExit(
                "options_ai: idea missing ticker/strategy/status; refusing to invent Available"
            )
        if "legs" not in idea:
            raise SystemExit(
                "options_ai: idea missing legs field (use [] when the DOM showed none)"
            )
    if board.get("no_invented_prices") is not True:
        raise SystemExit("options_ai: no_invented_prices must be true")
    out = json.loads(json.dumps(board))
    for idea in out["ideas"]:
        _apply_compare_metrics(idea)
    capture = "dom_quickstrike" if "quickstrike" in board_name.lower() else "dom_strategy_builder"
    provenance = dict(out.get("provenance") or {})
    provenance.setdefault("capture", capture)
    provenance["har_heuristic"] = False
    provenance["chain_xhr_mapped"] = False
    provenance["compare_metrics_invented"] = False
    provenance["expected_move_is_not_a_probability"] = True
    provenance["execution_realm"] = "shadow"
    provenance["authorizes_live_orders"] = False
    provenance["live_order_gate"] = False
    out["provenance"] = provenance
    return out


def _apply_compare_metrics(idea: dict) -> None:
    """Keep max risk / max gain / PoP only when the DOM already has them.

    Chain quotes and Expected Move are not those fields. Missing stays null.
    """
    ui = idea.get("ui_fields")
    if not isinstance(ui, dict):
        ui = {}
        idea["ui_fields"] = ui
    for key in ("max_risk", "max_gain", "pop"):
        if idea.get(key) is None and ui.get(key) is not None:
            idea[key] = ui.get(key)
        elif key not in idea:
            idea[key] = None
    present = all(idea.get(key) is not None for key in ("max_risk", "max_gain", "pop"))
    idea["compare_metrics_present"] = present
    idea["compare_metrics_source"] = "dom" if present else "absent"


def build_board(
    source: str,
    har: Path | None,
    board_path: Path | None,
    *,
    now: datetime,
    allow_stale: bool,
) -> dict:
    if source == "options_ai" and har is not None:
        refuse_options_ai_har(har)
    if board_path is not None:
        loaded = json.loads(board_path.read_text(encoding="utf-8"))
        if source == "options_ai":
            board = validate_options_ai_dom_board(loaded)
        else:
            if not str(loaded.get("schema", "")).startswith("idea_board"):
                raise SystemExit(f"not an idea_board JSON: {board_path}")
            if loaded.get("source") not in {None, source}:
                raise SystemExit(f"{board_path} source is {loaded.get('source')}, not {source}")
            board = loaded
        board["_origin"] = str(board_path)
        return board
    if har is None:
        raise SystemExit(f"{source}: need --from-har or --from-board")
    if source != "trademachine":
        raise SystemExit(f"unknown source {source}")
    extracted = tm_rows_from_har(har, now=now, allow_stale=allow_stale)
    if extracted.login_health != "AUTHENTICATED":
        raise SystemExit(
            "TradeMachine board is not AUTHENTICATED "
            f"(login_health={extracted.login_health}); refusing empty or anonymous publish"
        )
    board = tm_normalize(
        extracted.rows,
        endpoint=extracted.endpoint,
        observed_at=extracted.observed_at,
        login_health=extracted.login_health,
        legs_by_key=extracted.legs_by_key,
        har_note=f"Source HAR name: {har.name}",
    )
    board["_origin"] = str(har)
    return board


def _source_health(board: dict) -> dict:
    ideas = board.get("ideas") or []
    with_legs = 0
    missing = 0
    for idea in ideas:
        legs = idea.get("legs") or []
        if legs:
            with_legs += 1
        else:
            missing += 1
    ok = board.get("login_health") == "AUTHENTICATED" and bool(ideas)
    if board.get("source") == "options_ai":
        ok = ok and board.get("mode") == "paper"
    return {
        "ok": ok,
        "login_health": board.get("login_health"),
        "mode": board.get("mode"),
        "ideas": len(ideas),
        "with_legs": with_legs,
        "legs_missing": missing,
        "observed_at_pt": board.get("as_of_pt"),
        "capture": (board.get("provenance") or {}).get("capture"),
        "path": board.get("_path"),
    }


def _write_shadow(boards: list[dict]) -> None:
    health = {str(board.get("source")): _source_health(board) for board in boards}
    payload = {
        "schema": "idea_board_shadow.v0_1",
        "as_of_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT"),
        "sources": [board.get("source") for board in boards],
        "source_health": health,
        "boards": [
            {
                "source": board.get("source"),
                "board": board.get("board"),
                "login_health": board.get("login_health"),
                "counts": board.get("counts"),
                "path": board.get("_path"),
                "idea_cards": board.get("_idea_cards_path"),
                "tickers": [
                    idea.get("ticker") for idea in (board.get("ideas") or []) if idea.get("ticker")
                ],
            }
            for board in boards
        ],
        "desk_use": "shadow_only_continual15_shortlist_candidate_feed",
        "no_live_orders_from_scraper": True,
        "order_boundary": {
            "shadow_metadata_is_not_a_live_order_authorization": True,
            "adapter_must_require_execution_realm": ["shadow", "paper"],
            "wired_to_live_order_gate": False,
            "paper_api_base": PAPER_API_BASE,
            "live_submit": False,
        },
    }
    SHADOW.parent.mkdir(parents=True, exist_ok=True)
    temporary = SHADOW.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, SHADOW)


def _persist_one(board: dict, *, now: datetime) -> dict:
    source = str(board.get("source") or "unknown")
    origin = board.get("_origin")
    if origin and Path(str(origin)).suffix == ".json" and Path(str(origin)).is_file():
        out = Path(str(origin))
    else:
        out = BOARD_DIR / f"{source}_{_stamp_files(now)}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        stored = {key: value for key, value in board.items() if not str(key).startswith("_")}
        out.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    try:
        rel = str(out.relative_to(ROOT))
    except ValueError:
        rel = str(out)
    board["_path"] = rel
    cards = board_to_idea_cards(
        {key: value for key, value in board.items() if not str(key).startswith("_")}
    )
    cards_path = out.with_name(out.stem + "_idea_cards.json")
    cards_path.write_text(json.dumps(cards, indent=2) + "\n", encoding="utf-8")
    try:
        board["_idea_cards_path"] = str(cards_path.relative_to(ROOT))
    except ValueError:
        board["_idea_cards_path"] = str(cards_path)
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
            "Shadow/paper provenance only. This file does not authorize live_order_gate.",
            "",
            "| ticker | strategy | status | legs |",
            "|---|---|---|---|",
        ]
        for idea in board.get("ideas") or []:
            lines.append(
                f"| {idea.get('ticker')} | {idea.get('strategy')} | {idea.get('status')} | "
                f"{len(idea.get('legs') or [])} |"
            )
        markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return board


def _append_ledger(boards: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        for board in boards:
            event = {
                "ts_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT"),
                "event": "get_ideas",
                "source": board.get("source"),
                "board": board.get("board"),
                "path": board.get("_path"),
                "counts": board.get("counts"),
                "login_health": board.get("login_health"),
                "mode": "shadow_paper_only",
                "authorizes_live_orders": False,
            }
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")


def _named_har_source(path: Path) -> str | None:
    name = path.name.lower()
    if "option" in name:
        return "options_ai"
    if "trade" in name or "tm_" in name or "today" in name:
        return "trademachine"
    return None


def build_jobs(source: str, hars: list[Path], boards: list[Path]) -> list[Job]:
    jobs: list[Job] = []
    for har in hars:
        named = _named_har_source(har)
        if source == "both":
            if named is None:
                raise SystemExit(
                    f"cannot infer source from HAR name {har.name}; "
                    "use a trademachine/today or options_ai filename"
                )
            chosen = named
        elif named is not None and named != source:
            raise SystemExit(f"{har.name} looks like {named}, not --source {source}")
        else:
            chosen = source
        jobs.append(Job(chosen, har=har))
    for board_path in boards:
        loaded = json.loads(board_path.read_text(encoding="utf-8"))
        inferred = str(loaded.get("source") or "")
        if inferred not in {"trademachine", "options_ai"}:
            raise SystemExit(f"{board_path} missing source trademachine|options_ai")
        if source != "both" and inferred != source:
            raise SystemExit(f"{board_path} is {inferred}, not --source {source}")
        jobs.append(Job(inferred, board=board_path))
    if not jobs:
        raise SystemExit("pass --from-har and/or --from-board (no fixed default HAR)")
    if source == "both":
        counts = {name: 0 for name in ("trademachine", "options_ai")}
        for job in jobs:
            if job.source not in counts:
                raise SystemExit(f"unexpected source {job.source}")
            counts[job.source] += 1
        if counts["trademachine"] != 1 or counts["options_ai"] != 1:
            raise SystemExit(
                "--source both requires exactly one trademachine input and one options_ai input"
            )
    return jobs


def run_inputs(
    *,
    source: str,
    hars: list[Path],
    boards: list[Path],
    write_shadow: bool,
    now: datetime | None = None,
    allow_stale: bool = False,
) -> dict:
    """Build every source first. Persist boards, ledger, and shadow only if all succeed."""
    clock = now or datetime.now(UTC)
    jobs = build_jobs(source, hars, boards)
    built = [
        build_board(job.source, job.har, job.board, now=clock, allow_stale=allow_stale)
        for job in jobs
    ]
    if source == "both":
        health = {str(board.get("source")): _source_health(board) for board in built}
        bad = [name for name, item in health.items() if not item["ok"]]
        if bad:
            raise SystemExit(
                "--source both requires one valid board per product; not ok: " + ", ".join(bad)
            )
    persisted = [_persist_one(board, now=clock) for board in built]
    _append_ledger(persisted)
    if write_shadow:
        _write_shadow(persisted)
    return {
        "ok": True,
        "boards": persisted,
        "source_health": {str(board.get("source")): _source_health(board) for board in persisted},
        "ledger": str(LEDGER),
        "shadow": str(SHADOW) if write_shadow else None,
        "no_live_orders_from_scraper": True,
        "wired_to_live_order_gate": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["trademachine", "options_ai", "both"], default="both")
    parser.add_argument("--from-har", type=Path, action="append", default=[])
    parser.add_argument("--from-board", type=Path, action="append", default=[])
    parser.add_argument("--no-shadow", action="store_true")
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Allow a TradeMachine HAR older than 12 hours. Does not select a default file.",
    )
    args = parser.parse_args()
    try:
        summary = run_inputs(
            source=args.source,
            hars=list(args.from_har),
            boards=list(args.from_board),
            write_shadow=not args.no_shadow,
            allow_stale=args.allow_stale,
        )
    except SystemExit:
        raise
    public = {
        "ok": summary["ok"],
        "boards": [
            {
                "source": board.get("source"),
                "path": board.get("_path"),
                "idea_cards": board.get("_idea_cards_path"),
                "counts": board.get("counts"),
                "login_health": board.get("login_health"),
                "as_of_pt": board.get("as_of_pt"),
            }
            for board in summary["boards"]
        ],
        "source_health": summary["source_health"],
        "shadow": summary["shadow"],
        "no_live_orders_from_scraper": True,
        "wired_to_live_order_gate": False,
    }
    print(json.dumps(public, indent=2))


if __name__ == "__main__":
    main()
