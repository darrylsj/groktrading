"""Shadow-rank Trade Machine and Options AI boards.

Never places orders. Scores are signal strength, vendor hit rate when the
board already has one, and confluence. Options AI HAR heuristics stay off.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
DESK = Path(__file__).resolve().parents[2]
BOARD_DIR = DESK / "evidence" / "idea_boards"
STATE_OUT = DESK / "state" / "shadow_open_rank_latest.json"
LEDGER = DESK / "evidence" / "idea_shadow_rank" / "rank_ledger.jsonl"
EVIDENCE_DIR = DESK / "evidence" / "idea_shadow_rank"
GEX_PATH = DESK / "state" / "gex_shadow_qqq.json"


def _now_pt() -> datetime:
    return datetime.now(PT)


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_board(source: str, board_dir: Path = BOARD_DIR) -> Path | None:
    paths = sorted(board_dir.glob(f"{source}_*_pt.json"), key=lambda path: path.stat().st_mtime)
    return paths[-1] if paths else None


def _load_gex_tickers(path: Path = GEX_PATH) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    out = {"QQQ", "SPY", "IWM"}
    if payload.get("ticker"):
        out.add(str(payload["ticker"]).upper())
    return out


def _tm_signal(idea: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    ui = idea.get("ui_fields") or {}
    status = str(idea.get("status") or "").lower()
    score = 0.0
    if ui.get("isActive") in (1, True, "1") or status == "active":
        score += 28
        reasons.append("TM Active")
    elif "near" in status:
        score += 16
        reasons.append("TM Near Active")
    else:
        score += 6
        reasons.append(f"TM status={idea.get('status')}")
    if ui.get("triggeredToday") in (True, 1, "1"):
        score += 10
        reasons.append("triggeredToday")
    if (idea.get("entry") or {}).get("mid") is not None:
        score += 2
        reasons.append("has mid")
    return min(40.0, score), reasons


def _tm_hit(idea: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    ui = idea.get("ui_fields") or {}
    win_rate = _f(ui.get("winRate"))
    wins = _f(ui.get("numWins")) or 0.0
    losses = _f(ui.get("numLosses")) or 0.0
    sample_n = wins + losses
    if win_rate is None:
        reasons.append("no winRate → prior 8")
        return 8.0, reasons
    if win_rate > 1.5:
        win_rate = win_rate / 100.0
    base = max(0.0, min(1.0, win_rate)) * 30.0
    sample = min(10.0, math.sqrt(max(sample_n, 0.0)) * 1.5)
    reasons.append(f"winRate={win_rate:.2%} n={int(sample_n)} sample_bonus={sample:.1f}")
    ret = _f(ui.get("returnPercent"))
    if ret is not None and ret > 0 and sample_n >= 10:
        base = min(30.0, base + 2.0)
        reasons.append("seasoned positive return%")
    return min(40.0, base + sample), reasons


def _oai_signal(idea: dict) -> tuple[float, list[str]]:
    reasons = ["OAI DOM prior (HAR heuristic off)"]
    score = 12.0
    status = str(idea.get("status") or "").lower()
    if status in {"available", "active"}:
        score += 6
        reasons.append(f"status={idea.get('status')}")
    strategy = str(idea.get("strategy") or "").lower()
    if any(key in strategy for key in ("spread", "butterfly", "condor", "collar")):
        score += 10
        reasons.append("defined-risk structure")
    elif "secured put" in strategy or "cash secured" in strategy:
        score += 8
        reasons.append("cash-secured put")
    elif strategy in {"call", "put"} or "long call" in strategy or "long put" in strategy:
        score += 2
        reasons.append("outright directional (lower)")
    direction = str(idea.get("direction") or idea.get("dir") or "").lower()
    if direction in {"bullish", "bearish", "neutral"}:
        score += 4 if direction != "neutral" else 3
        reasons.append(f"dir={direction}")
    if idea.get("compare_metrics_present") is True:
        score += 4
        reasons.append("DOM compare metrics present")
    return min(40.0, score), reasons


def _oai_hit(idea: dict) -> tuple[float, list[str]]:
    if idea.get("compare_metrics_present") is True and idea.get("pop") is not None:
        return 10.0, ["PoP present on DOM card; not a vendor win rate"]
    return 6.0, ["OAI has no winRate on board → prior 6 (not evidence)"]


def _confluence(
    idea: dict,
    source: str,
    tickers_by_source: dict[str, set[str]],
    gex: set[str],
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    ticker = str(idea.get("ticker") or "").upper()
    other = "options_ai" if source == "trademachine" else "trademachine"
    if ticker and ticker in tickers_by_source.get(other, set()):
        score += 12
        reasons.append(f"also on {other}")
    if ticker in {"SPY", "QQQ", "IWM", "DIA"}:
        score += 4
        reasons.append("broad ETF")
    if ticker in gex or (ticker in {"XLK", "SMH", "QQQ"} and "QQQ" in gex):
        score += 4
        reasons.append("near GEX shadow map")
    if not reasons:
        reasons.append("no multi-source confluence")
    return min(20.0, score), reasons


def _tier(total: float) -> str:
    if total >= 70:
        return "A"
    if total >= 50:
        return "B"
    if total >= 35:
        return "C"
    return "D"


def score_idea(
    idea: dict,
    source: str,
    tickers_by_source: dict[str, set[str]],
    gex: set[str],
) -> dict[str, Any]:
    if source == "trademachine":
        signal, signal_reasons = _tm_signal(idea)
        hit, hit_reasons = _tm_hit(idea)
    else:
        signal, signal_reasons = _oai_signal(idea)
        hit, hit_reasons = _oai_hit(idea)
    confluence, confluence_reasons = _confluence(idea, source, tickers_by_source, gex)
    total = round(signal + hit + confluence, 1)
    ui = idea.get("ui_fields") if isinstance(idea.get("ui_fields"), dict) else {}
    return {
        "source": source,
        "ticker": str(idea.get("ticker") or "").upper(),
        "strategy": idea.get("strategy"),
        "status": idea.get("status"),
        "direction": idea.get("direction") or idea.get("dir"),
        "score": total,
        "tier": _tier(total),
        "components": {
            "signal_strength": round(signal, 1),
            "historical_hit": round(hit, 1),
            "confluence": round(confluence, 1),
        },
        "reasons": signal_reasons + hit_reasons + confluence_reasons,
        "vendor": {
            "winRate": ui.get("winRate"),
            "numWins": ui.get("numWins"),
            "numLosses": ui.get("numLosses"),
            "returnPercent": ui.get("returnPercent"),
            "triggeredToday": ui.get("triggeredToday"),
            "isActive": ui.get("isActive"),
        },
        "entry": idea.get("entry"),
        "legs": idea.get("legs") or [],
        "max_risk": idea.get("max_risk"),
        "max_gain": idea.get("max_gain"),
        "pop": idea.get("pop"),
        "compare_metrics_present": idea.get("compare_metrics_present") is True,
        "shadow_only": True,
        "no_live_orders": True,
    }


def build_slate(
    tm_board: dict[str, Any] | None,
    oai_board: dict[str, Any] | None,
    *,
    top_n: int = 10,
    gex: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    ideas_raw: list[tuple[str, dict]] = []
    tickers_by_source: dict[str, set[str]] = {"trademachine": set(), "options_ai": set()}
    boards: dict[str, Any] = {}
    for source, board in (("trademachine", tm_board), ("options_ai", oai_board)):
        if not board:
            continue
        boards[source] = {
            "as_of_pt": board.get("as_of_pt"),
            "login_health": board.get("login_health"),
            "n_ideas": len(board.get("ideas") or []),
        }
        for idea in board.get("ideas") or []:
            ticker = str(idea.get("ticker") or "").upper()
            if ticker:
                tickers_by_source[source].add(ticker)
            ideas_raw.append((source, idea))
    gex_tickers = set() if gex is None else set(gex)
    scored = [
        score_idea(idea, source, tickers_by_source, gex_tickers) for source, idea in ideas_raw
    ]
    scored.sort(key=lambda row: (-row["score"], row["source"], row["ticker"]))
    stamp = (now or _now_pt()).astimezone(PT)
    return {
        "schema": "shadow_open_rank.v0_1",
        "as_of_pt": stamp.strftime("%Y-%m-%d %H:%M:%S PT"),
        "session_target": "next_RTH_open",
        "shadow_only": True,
        "no_live_orders": True,
        "boards": boards,
        "gex_tickers_considered": sorted(gex_tickers),
        "counts": {
            "scored": len(scored),
            "tier_A": sum(1 for row in scored if row["tier"] == "A"),
            "tier_B": sum(1 for row in scored if row["tier"] == "B"),
            "tier_C": sum(1 for row in scored if row["tier"] == "C"),
            "tier_D": sum(1 for row in scored if row["tier"] == "D"),
        },
        "top_n": scored[:top_n],
        "top_tier_A": [row for row in scored if row["tier"] == "A"],
        "all_ranked": scored,
        "notes": [
            "Shadow only — never submits broker orders.",
            "Options AI HAR→ideas is off. Compare metrics count only when the DOM has them.",
            "Trade Machine Active outranks Near Active. Empty Near Active legs are not filled in.",
            "Continual15 may read the slate as shortlist fuel only.",
        ],
    }


def write_outputs(slate: dict[str, Any], desk: Path = DESK) -> tuple[Path, Path]:
    evidence = desk / "evidence" / "idea_shadow_rank"
    evidence.mkdir(parents=True, exist_ok=True)
    state = desk / "state" / "shadow_open_rank_latest.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    stamp = _now_pt().strftime("%Y%m%d_%H%M_pt")
    card = evidence / f"open_rank_{stamp}.json"
    card.write_text(json.dumps(slate, indent=2) + "\n", encoding="utf-8")
    slim = {key: value for key, value in slate.items() if key != "all_ranked"}
    slim["all_ranked_path"] = str(card.relative_to(desk))
    state.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    ledger = evidence / "rank_ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "ts_pt": slate["as_of_pt"],
                    "card": str(card.relative_to(desk)),
                    "counts": slate["counts"],
                    "shadow_only": True,
                }
            )
            + "\n"
        )
    md_path = evidence / f"open_rank_{stamp}.md"
    lines = [
        f"# Shadow open rank — {slate['as_of_pt']}",
        "",
        "**SHADOW ONLY — no live orders.**",
        "",
        f"Scored {slate['counts']['scored']} ideas.",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return card, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow-rank TM+OAI boards (never orders)")
    parser.add_argument("--tm", type=Path)
    parser.add_argument("--oai", type=Path)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()
    tm_path = args.tm or _latest_board("trademachine")
    oai_path = args.oai or _latest_board("options_ai")
    if not tm_path and not oai_path:
        raise SystemExit("no trademachine_* or options_ai_* boards under evidence/idea_boards")
    tm_board = json.loads(tm_path.read_text(encoding="utf-8")) if tm_path else None
    oai_board = json.loads(oai_path.read_text(encoding="utf-8")) if oai_path else None
    slate = build_slate(tm_board, oai_board, top_n=args.top, gex=_load_gex_tickers())
    card, md_path = write_outputs(slate)
    print(json.dumps({"ok": True, "card": str(card), "md": str(md_path), "shadow_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
