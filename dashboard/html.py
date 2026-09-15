"""Static HTML for darrylsj/trading-desk-live-board (Vercel).

The builder inlines the board JSON. No fetch, no credentials, no sockets.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any


def _esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _yes_no(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "—"


def _cell(value: object) -> str:
    if value is None or value == "":
        return "<td class=\"empty\">—</td>"
    if isinstance(value, bool):
        return f"<td>{_esc(_yes_no(value))}</td>"
    return f"<td>{_esc(value)}</td>"


def _reason_rows(reasons: Mapping[str, Any]) -> str:
    if not reasons:
        return "<tr><td colspan=\"2\" class=\"empty\">no refuse rows in evidence</td></tr>"
    parts: list[str] = []
    for name, count in reasons.items():
        parts.append(f"<tr><td>{_esc(name)}</td>{_cell(count)}</tr>")
    return "".join(parts)


def _occ_list(occs: list[Any]) -> str:
    if not occs:
        return "<p class=\"empty\">No evidence OCCs. None invented.</p>"
    items = "".join(f"<li><code>{_esc(occ)}</code></li>" for occ in occs)
    return f"<ol class=\"occs\">{items}</ol>"


def _funnel_section(funnel: Mapping[str, Any]) -> str:
    present = funnel.get("present")
    empty = funnel.get("empty_reason")
    status = "evidence present" if present else f"not present ({empty or 'no_input'})"
    raw_reasons = funnel.get("refuse_reasons")
    reasons = raw_reasons if isinstance(raw_reasons, Mapping) else {}
    last = funnel.get("last_occs") if isinstance(funnel.get("last_occs"), list) else []
    raw_shortlist = funnel.get("shortlist")
    shortlist = raw_shortlist if isinstance(raw_shortlist, Mapping) else {}
    raw_shadow = funnel.get("shadow_summary")
    shadow = raw_shadow if isinstance(raw_shadow, Mapping) else {}
    posture = funnel.get("posture") if isinstance(funnel.get("posture"), Mapping) else {}
    shortlist_occs = (
        shortlist.get("candidate_occs") if isinstance(shortlist.get("candidate_occs"), list) else []
    )
    shortlist_status = (
        "present" if shortlist.get("present") else f"not present ({shortlist.get('empty_reason')})"
    )
    shadow_status = (
        "present" if shadow.get("present") else f"not present ({shadow.get('empty_reason')})"
    )
    return f"""
<section id="funnel">
  <h2>Opportunity-process funnel</h2>
  <p class="lede">Refuse evidence only. Hunt while the opportunity timer is paused:
  <strong>{_esc(posture.get("hunt"))}</strong>. sit_match stays
  <strong>{_esc(_yes_no(posture.get("sit_match")))}</strong>.</p>
  <p>Refuses file: <strong>{_esc(status)}</strong> · rows={_esc(funnel.get("rows"))}
  · skipped invented={_esc(funnel.get("skipped_invented"))}
  · skipped no OCC={_esc(funnel.get("skipped_no_occ"))}</p>
  <h3>Refuse reasons</h3>
  <table>
    <thead><tr><th>Reason</th><th>Count</th></tr></thead>
    <tbody>{_reason_rows(reasons)}</tbody>
  </table>
  <h3>Last OCCs (from evidence, most recent last)</h3>
  {_occ_list(last)}
  <h3>Shortlist hook</h3>
  <p>{_esc(shortlist_status)} · ranked_at={_esc(shortlist.get("ranked_at") or "—")}
  · emit_sit_match={_esc(_yes_no(shortlist.get("emit_sit_match")))}</p>
  {_occ_list(shortlist_occs)}
  <h3>Shadow summary hook</h3>
  <p>{_esc(shadow_status)}
  · opened={_esc(shadow.get("opened") if shadow.get("opened") is not None else "—")}
  · marked={_esc(shadow.get("marked") if shadow.get("marked") is not None else "—")}
  · unmarked={_esc(shadow.get("unmarked") if shadow.get("unmarked") is not None else "—")}
  · pnl={_esc(shadow.get("pnl") if shadow.get("pnl") is not None else "null")}
  (never invented)</p>
</section>
"""


def _ws_section(ws: Mapping[str, Any] | None) -> str:
    if ws is None:
        return """
<section id="ws-stats">
  <h2>WebSocket producer / consumer stats</h2>
  <p class="empty">Omitted by request. Default is a READ-ONLY snapshot section.</p>
</section>
"""
    finnhub = ws.get("finnhub_tape") if isinstance(ws.get("finnhub_tape"), Mapping) else {}
    live = ws.get("live_tape") if isinstance(ws.get("live_tape"), Mapping) else {}
    freshness = finnhub.get("freshness") if isinstance(finnhub.get("freshness"), Mapping) else {}
    symbols = finnhub.get("symbols") if isinstance(finnhub.get("symbols"), list) else []
    symbol_txt = ", ".join(str(s) for s in symbols) if symbols else "—"
    finnhub_status = (
        "present" if finnhub.get("present") else f"not present ({finnhub.get('empty_reason')})"
    )
    live_status = (
        "present" if live.get("present") else f"not present ({live.get('empty_reason')})"
    )
    errors = live.get("errors") if isinstance(live.get("errors"), list) else []
    error_txt = ", ".join(str(e) for e in errors) if errors else "—"
    flow_http = live.get("flow_http")
    return f"""
<section id="ws-stats">
  <h2>WebSocket producer / consumer stats</h2>
  <p class="lede"><strong>READ-ONLY.</strong> No new subscriptions.
  sit_match unmute={_esc(_yes_no(ws.get("sit_match_unmute")))}.
  opportunity webhook resume={_esc(_yes_no(ws.get("opportunity_webhook_resume")))}.</p>
  <h3>finnhub_tape.json</h3>
  <p>{_esc(finnhub_status)} · connected={_esc(_yes_no(finnhub.get("connected")))}
  · stale={_esc(_yes_no(freshness.get("stale")))}
  · last_event_ts={_esc(freshness.get("last_event_ts") or "—")}
  · symbols={_esc(symbol_txt)}</p>
  <p class="note">{_esc(finnhub.get("note"))}</p>
  <h3>live_tape.json</h3>
  <p>{_esc(live_status)}
  · flow_n={_esc(live.get("flow_n") if live.get("flow_n") is not None else "—")}
  · flow_http={_esc(flow_http if flow_http is not None else "—")}
  · errors={_esc(error_txt)}
  · candidates={_esc(live.get("candidates") if live.get("candidates") is not None else "—")}</p>
  <p class="note">{_esc(live.get("note"))}</p>
</section>
"""


def _rules(rules: list[Any]) -> str:
    items = "".join(f"<li>{_esc(rule)}</li>" for rule in rules)
    return f"<ul class=\"rules\">{items}</ul>"


def render_html(board: Mapping[str, Any]) -> str:
    """Self-contained static page. Safe to host on Vercel with no backend."""
    funnel = board.get("funnel") if isinstance(board.get("funnel"), Mapping) else {}
    ws = board.get("ws_stats") if isinstance(board.get("ws_stats"), Mapping) else None
    sibling = board.get("sibling_site") if isinstance(board.get("sibling_site"), Mapping) else {}
    rules = board.get("hard_rules") if isinstance(board.get("hard_rules"), list) else []
    payload = json.dumps(board, indent=2, sort_keys=True, default=str)
    # Keep JSON parseable inside <script>. Only neutralize </script> breakout.
    safe_payload = payload.replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trading Desk live board</title>
  <meta name="robots" content="noindex">
  <style>
    :root {{
      --ink: #12202b;
      --muted: #5b6b76;
      --line: #d5dde3;
      --bg: #f6f3ee;
      --card: #fffdf8;
      --accent: #1f4d3a;
      --warn: #8a3d12;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0 auto;
      max-width: 52rem;
      padding: 1.5rem 1.25rem 3rem;
      font: 16px/1.5 ui-sans-serif, system-ui, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    h1, h2, h3 {{ font-weight: 650; letter-spacing: -0.02em; }}
    h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1.2rem; margin-top: 2rem; color: var(--accent); }}
    h3 {{ font-size: 1rem; margin-top: 1.1rem; }}
    .lede, .note, .meta {{ color: var(--muted); }}
    .note {{ font-size: 0.92rem; }}
    .banner {{
      border: 1px solid var(--line);
      background: var(--card);
      padding: 0.9rem 1rem;
      border-radius: 8px;
    }}
    .rules {{ margin: 0.4rem 0 0; padding-left: 1.2rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
    }}
    th, td {{
      text-align: left;
      padding: 0.4rem 0.55rem;
      border-bottom: 1px solid var(--line);
      font-variant-numeric: tabular-nums;
    }}
    th {{
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    .empty {{ color: var(--muted); font-style: italic; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92em; }}
    ol.occs {{ padding-left: 1.2rem; }}
    footer {{ margin-top: 2.5rem; color: var(--muted); font-size: 0.9rem; }}
  </style>
</head>
<body>
  <header>
    <h1>Trading Desk live board</h1>
    <p class="meta">session {_esc(board.get("session"))} · generated
    {_esc(board.get("generated_at"))} · schema {_esc(board.get("schema"))}</p>
    <div class="banner">
      <strong>Observational. live_gate={_esc(_yes_no(board.get("live_gate")))}.
      places_orders={_esc(_yes_no(board.get("places_orders")))}.
      invented={_esc(_yes_no(board.get("invented")))}.</strong>
      {_rules(rules)}
    </div>
  </header>
  {_funnel_section(funnel)}
  {_ws_section(ws)}
  <footer>
    <p>Static HTML/JSON for
    <code>{_esc(sibling.get("repo") or "darrylsj/trading-desk-live-board")}</code>
    ({_esc(sibling.get("host") or "Vercel")}). Rebuild from evidence files.
    This page does not fetch Helsinki, open sockets, or place orders.</p>
    <p>Architecture: WEBSOCKETS.md · REALTIME_PLANES.md · DASHBOARD.md</p>
  </footer>
  <script type="application/json" id="board-data">{safe_payload}</script>
</body>
</html>
"""
