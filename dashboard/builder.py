"""Assemble the desk board document and write static HTML/JSON."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from dashboard.book import build_book, build_open_orders
from dashboard.config import (
    BOARD_JSON_NAME,
    BOARD_NOTE,
    HARD_RULES,
    I1_MAX_AGE_SEC,
    INVENTED,
    KIND,
    LIVE_GATE,
    LIVE_JSON_NAME,
    NEW_WS_SUBSCRIPTIONS,
    OPPORTUNITY_WEBHOOK_RESUME,
    PLACES_ORDERS,
    SCHEMA_ID,
    SIBLING_SITE_HOST,
    SIBLING_SITE_REPO,
    SIT_MATCH_STAYS_OFF,
    UNLOCK_I1,
    DashboardError,
)
from dashboard.funnel import build_funnel
from dashboard.html import render_html
from dashboard.ws_stats import build_ws_stats
from groktrading.io_atomic import write_json_atomic
from groktrading.sit_match import parse_executed_at
from groktrading.timeutil import UTC, as_utc, session_date_pt


def parse_now(raw: str | datetime | None) -> datetime:
    if raw is None:
        return datetime.now(tz=UTC)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raise DashboardError("now_naive", "--now must be timezone-aware ISO-8601")
        return as_utc(raw)
    parsed = parse_executed_at(raw)
    if parsed is None:
        raise DashboardError("now_naive", "--now must be timezone-aware ISO-8601")
    return parsed


def session_key(now: datetime, session: str | date | None) -> str:
    if session is None or (isinstance(session, str) and not session.strip()):
        return session_date_pt(now).isoformat()
    if isinstance(session, date) and not isinstance(session, datetime):
        return session.isoformat()
    text = str(session).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise DashboardError("bad_session", "session must be YYYY-MM-DD") from exc


def isoformat(now: datetime) -> str:
    return as_utc(now).isoformat().replace("+00:00", "Z")


def build_board(
    *,
    refuses: Path | None = None,
    shortlist: Path | None = None,
    shadow_summary: Path | None = None,
    finnhub_tape: Path | None = None,
    live_tape: Path | None = None,
    book: Path | None = None,
    open_orders: Path | None = None,
    session: str | date | None = None,
    now: str | datetime | None = None,
    include_ws_stats: bool = True,
) -> dict[str, Any]:
    """Build a secret-free desk board. Never invents prices / P&L / OCCs."""
    stamp = parse_now(now)
    funnel = build_funnel(
        refuses,
        shortlist=shortlist,
        shadow_summary=shadow_summary,
    )
    ws_stats = (
        build_ws_stats(
            finnhub_tape=finnhub_tape,
            live_tape=live_tape,
            shortlist=shortlist,
        )
        if include_ws_stats
        else None
    )
    return {
        "schema": SCHEMA_ID,
        "kind": KIND,
        "generated_at": isoformat(stamp),
        "session": session_key(stamp, session),
        "live_gate": LIVE_GATE,
        "places_orders": PLACES_ORDERS,
        "invented": INVENTED,
        "unlock_i1": UNLOCK_I1,
        "i1_max_age_sec": I1_MAX_AGE_SEC,
        "sit_match": False,
        "sit_match_stays_off": SIT_MATCH_STAYS_OFF,
        "new_ws_subscriptions": NEW_WS_SUBSCRIPTIONS,
        "opportunity_webhook_resume": OPPORTUNITY_WEBHOOK_RESUME,
        "hard_rules": list(HARD_RULES),
        "note": BOARD_NOTE,
        "book": build_book(book, live_tape=live_tape),
        "open_orders": build_open_orders(open_orders, live_tape=live_tape),
        "funnel": funnel,
        "ws_stats": ws_stats,
        "sibling_site": {
            "repo": SIBLING_SITE_REPO,
            "host": SIBLING_SITE_HOST,
            "pattern": "static HTML + live.json",
            "consumes": ["live.json", "board.json", "index.html"],
        },
        "docs": [
            "docs/DASHBOARD.md",
            "docs/LIVE_BOARD_REFRESH.md",
            "docs/WEBSOCKETS.md",
            "docs/REALTIME_PLANES.md",
        ],
    }


def write_board(
    board: dict[str, Any],
    *,
    out_json: Path | None = None,
    out_html: Path | None = None,
    out_dir: Path | None = None,
) -> dict[str, str]:
    """Write static JSON + HTML. Redacts secret-shaped keys on JSON."""
    written: dict[str, str] = {}
    json_path = out_json
    html_path = out_html
    if out_dir is not None:
        dest = Path(out_dir)
        dest.mkdir(parents=True, exist_ok=True)
        json_path = json_path or dest / BOARD_JSON_NAME
        html_path = html_path or dest / "index.html"
        live_path = dest / LIVE_JSON_NAME
        write_json_atomic(live_path, board, redact=True)
        written["live_json"] = str(live_path.resolve())
    if json_path is None and html_path is None:
        raise DashboardError("no_output", "pass --out, --html, or --out-dir")
    if json_path is not None:
        write_json_atomic(Path(json_path), board, redact=True)
        written["board_json"] = str(Path(json_path).resolve())
    if html_path is not None:
        target = Path(html_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_html(board), encoding="utf-8")
        written["index_html"] = str(target.resolve())
    return written
