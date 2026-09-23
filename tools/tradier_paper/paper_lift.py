"""Plan one-lot Tradier sandbox lifts from a shadow rank. Default is dry-run.

Trade Machine Near Active is watch-only. Options AI stays off unless
``--allow-oai`` and the DOM card already has max risk, max gain, and PoP.
This module does not call ``live_order_gate`` and does not use the live host.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tools.tradier_paper.client import PAPER_API_BASE, TradierPaperClient
from tools.tradier_paper.occ import legs_to_occs

PT = ZoneInfo("America/Los_Angeles")
DESK = Path(__file__).resolve().parents[2]
OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
BROAD_ETF = {"IWM", "SPY", "QQQ"}


def _now() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def _occ_of(value: object) -> str | None:
    if isinstance(value, str) and OCC_RE.fullmatch(value.replace("-", "").replace(" ", "")):
        return value.replace("-", "").replace(" ", "").upper()
    return None


def occ_from_idea(idea: dict[str, Any]) -> str | None:
    for key in ("occ", "option_symbol", "symbol_occ"):
        found = _occ_of(idea.get(key))
        if found:
            return found
    for leg in idea.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        found = _occ_of(leg.get("occ") or leg.get("option_symbol"))
        if found:
            return found
    mapped = legs_to_occs(str(idea.get("ticker") or ""), list(idea.get("legs") or []))
    bto = [row for row in mapped if row.get("side") == "buy_to_open" and row.get("occ")]
    if len(mapped) == 1 and bto:
        return str(bto[0]["occ"])
    return None


def refuse_long_put(ticker: str, occ: str | None, side: str) -> str | None:
    if side != "buy_to_open" or not occ:
        return None
    if ticker.upper() not in BROAD_ETF:
        return None
    if occ[-9] == "P":
        return "refuse_long_put_on_broad_etf"
    return None


def plan_one(
    row: dict[str, Any],
    *,
    allow_oai: bool,
) -> dict[str, Any]:
    source = str(row.get("source") or "")
    status = str(row.get("status") or "")
    item: dict[str, Any] = {
        "ticker": row.get("ticker"),
        "source": source,
        "tier": row.get("tier"),
        "score": row.get("score"),
        "strategy": row.get("strategy"),
        "status": status,
        "places_orders": False,
        "api_base": PAPER_API_BASE,
        "shadow_only_rank": True,
    }
    if source == "options_ai" and not allow_oai:
        item["action"] = "skip"
        item["reason"] = "options_ai_dom_until_confirmed"
        return item
    if source == "options_ai" and row.get("compare_metrics_present") is not True:
        item["action"] = "skip"
        item["reason"] = "compare_metrics_absent"
        return item
    if source == "trademachine" and status.lower() != "active":
        item["action"] = "skip"
        item["reason"] = "near_active_watch_only" if "near" in status.lower() else "not_active"
        return item
    occ = occ_from_idea(row)
    item["occ"] = occ
    if not occ:
        item["action"] = "skip_no_occ"
        item["reason"] = "no resolvable OCC — do not invent legs"
        return item
    blocked = refuse_long_put(str(row.get("ticker") or ""), occ, "buy_to_open")
    if blocked:
        item["action"] = "skip"
        item["reason"] = blocked
        return item
    item["action"] = "dry_run"
    item["reason"] = "paper_lift_dry_run"
    return item


def select_rows(rank: dict[str, Any], *, top: int, sources: set[str]) -> list[dict[str, Any]]:
    rows = []
    for row in rank.get("top_n") or rank.get("all_ranked") or []:
        if row.get("source") not in sources:
            continue
        if row.get("tier") not in {"A", "B"}:
            continue
        rows.append(row)
        if len(rows) >= top:
            break
    return rows


def run_plan(
    rank: dict[str, Any],
    *,
    top: int = 3,
    allow_oai: bool = False,
    submit: bool = False,
    client: TradierPaperClient | None = None,
    ask_by_occ: dict[str, float] | None = None,
) -> dict[str, Any]:
    sources = {"trademachine"}
    if allow_oai:
        sources.add("options_ai")
    results = []
    for row in select_rows(rank, top=top, sources=sources):
        item = plan_one(row, allow_oai=allow_oai)
        if item["action"] != "dry_run":
            results.append(item)
            continue
        occ = str(item["occ"])
        ask = None if ask_by_occ is None else ask_by_occ.get(occ)
        if ask is None and client is not None and submit:
            quoted = client.quote(occ)
            quote = (quoted.get("quotes") or {}).get("quote")
            if isinstance(quote, list):
                quote = quote[0] if quote else {}
            ask = quote.get("ask") if isinstance(quote, dict) else None
        if ask is None:
            item["action"] = "skip_no_ask"
            item["reason"] = "no ask supplied; refusing to invent a limit"
            results.append(item)
            continue
        if client is None or not submit:
            item["limit"] = ask
            item["places_orders"] = False
            results.append(item)
            continue
        placed = client.place_option(
            option_symbol=occ,
            side="buy_to_open",
            quantity=1,
            order_type="limit",
            price=float(ask),
            submit=True,
        )
        item["action"] = "submit"
        item["places_orders"] = placed["places_orders"]
        item["base"] = placed["base"]
        item["reason"] = "sandbox_submit"
        results.append(item)
    return {
        "as_of_pt": _now(),
        "submit": bool(submit),
        "api_base": PAPER_API_BASE,
        "places_orders": any(row.get("places_orders") for row in results),
        "results": results,
        "note": "Default is dry-run. --submit posts to sandbox.tradier.com/v1 only.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank", type=Path, required=True)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--allow-oai", action="store_true")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="POST one-lot limits to the sandbox. Default is dry-run.",
    )
    args = parser.parse_args()
    rank = json.loads(args.rank.read_text(encoding="utf-8"))
    client = TradierPaperClient() if args.submit else None
    payload = run_plan(
        rank,
        top=args.top,
        allow_oai=args.allow_oai,
        submit=args.submit,
        client=client,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
