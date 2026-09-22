"""Append resolved live trades to Aria's shared ledger on Helsinki.

Contract: /opt/shared-intel/GROK_ONBOARDING.md
- Grok writes grok/ only (data). Aria never writes there.
- Aria tips never lift alone — this module only emits closed-trade facts.
- pnl_usd is fill-based (exit-entry)*100*qty for long options; never invented marks.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
SSH_KEY = Path(os.environ.get("HELSINKI_SSH_KEY", "/home/box/.ssh/id_ed25519_helsinki"))
SSH_HOST = os.environ.get("HELSINKI_SSH_HOST", "helsinki")
REMOTE_GROK = "/opt/shared-intel/grok"
REMOTE_TRADES = f"{REMOTE_GROK}/trades.jsonl"
REMOTE_POSITIONS = f"{REMOTE_GROK}/positions_open.json"
REMOTE_EQUITY = f"{REMOTE_GROK}/daily_equity.jsonl"
REMOTE_HEARTBEAT = f"{REMOTE_GROK}/heartbeat.json"

# Locked setup vocabulary — keep names stable so Aria can rank strategies.
SETUP_VOCAB = frozenset(
    {
        "continual15_shortlist",
        "uw_ask_flow",
        "idea_board_tm",
        "idea_board_oai",
        "overnight_carry",
        "operator_manual",
        "take_gain_protect",
        "premium_floor",
        "aria_tip_intersect",  # tip contributed but never sole lift
        "unknown",
    }
)

EXIT_MAP = {
    "take_gain": "take_gain",
    "take_gain_protect": "take_gain",
    "protect_hit": "take_gain",
    "stop": "stop",
    "premium_floor": "stop",
    "flatten": "flatten",
    "operator_flatten": "flatten",
    "darryl_judgment": "flatten",
    "darryl_judgment_no_overnight": "flatten",
    "expired": "expired",
    "dead_thesis": "dead_thesis",
    "dead_thesis_exit": "dead_thesis",
}


def map_exit_reason(raw: str | None) -> str:
    s = (raw or "flatten").strip().lower().replace(" ", "_")
    return EXIT_MAP.get(s, "flatten" if "flat" in s or "operator" in s or "darryl" in s else (
        "dead_thesis" if "dead" in s or "thesis" in s else (
            "take_gain" if "gain" in s or "protect" in s else (
                "stop" if "floor" in s or "stop" in s else "flatten"
            )
        )
    ))


def _pt_now() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M PT")


def _ssh(
    argv: list[str], *, input_bytes: bytes | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[bytes]:
    base = [
        "ssh",
        "-i",
        str(SSH_KEY),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        f"root@{SSH_HOST}",
    ]
    return subprocess.run(
        base + argv,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _remote_flock_append(remote_path: str, line: str) -> dict[str, Any]:
    """Append one JSONL line under flock on Helsinki via durable helper script."""
    payload = line if line.endswith('\n') else line + '\n'
    proc = _ssh(
        ["python3", f"{REMOTE_GROK}/_append_jsonl.py", remote_path, "a"],
        input_bytes=payload.encode("utf-8"),
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:500],
            "path": remote_path,
        }
    detail = proc.stdout.decode("utf-8", "replace").strip()
    return {"ok": True, "path": remote_path, "detail": detail}


def _remote_write_json(remote_path: str, obj: Any) -> dict[str, Any]:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + '\n'
    proc = _ssh(
        ["python3", f"{REMOTE_GROK}/_append_jsonl.py", remote_path, "w"],
        input_bytes=raw.encode("utf-8"),
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:500],
            "path": remote_path,
        }
    return {"ok": True, "path": remote_path}



def append_shared_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Append one resolved trade to /opt/shared-intel/grok/trades.jsonl on Helsinki.

    Required for Aria synthesizer: pnl_usd, ticker, entry_price, exit_price, size, exit_reason.
    Strongly wanted: setup (stable name from SETUP_VOCAB).
    """
    row = dict(trade)
    row.setdefault("schema", "shared-intel.trade.v1")
    row.setdefault("instrument", "option")
    # Book label only. The live account id stays in host env, never in git.
    row.setdefault("book", os.environ.get("TRADIER_BOOK_LABEL", "tradier_live"))
    # normalize PnL aliases → pnl_usd (Aria scoreboard)
    if row.get("pnl_usd") is None:
        for alt in ("realized", "pnl", "close_pl"):
            if row.get(alt) is not None:
                row["pnl_usd"] = float(row[alt])
                break
    setup = str(row.get("setup") or "unknown")
    if setup not in SETUP_VOCAB:
        row["setup_raw"] = setup
        sl = setup.lower()
        if "continual" in sl or "shortlist" in sl:
            row["setup"] = "continual15_shortlist"
        elif "overnight" in sl or "carry" in sl:
            row["setup"] = "overnight_carry"
        elif "operator" in sl or "darryl" in sl or "manual" in sl:
            row["setup"] = "operator_manual"
        elif "gain" in sl or "protect" in sl:
            row["setup"] = "take_gain_protect"
        elif "floor" in sl or "premium" in sl:
            row["setup"] = "premium_floor"
        elif "uw" in sl or "flow" in sl:
            row["setup"] = "uw_ask_flow"
        elif "idea" in sl and "tm" in sl:
            row["setup"] = "idea_board_tm"
        elif "idea" in sl or "oai" in sl:
            row["setup"] = "idea_board_oai"
        else:
            row["setup"] = "unknown"
    row["exit_reason"] = map_exit_reason(str(row.get("exit_reason") or ""))
    tod = row.get("time_of_day_bucket")
    if tod:
        row["time_of_day_bucket"] = tod
    row.setdefault("aria_tip", False)
    row.setdefault("emitted_pt", _pt_now())
    row["invented"] = False
    row["secrets"] = False
    # Validate minimum scoreboard fields — refuse to emit invented PnL
    required = (
        "ticker",
        "occ_symbol",
        "entry_price",
        "exit_price",
        "size",
        "pnl_usd",
        "exit_reason",
    )
    missing = [key for key in required if key not in row or row[key] is None]
    if missing:
        return {"ok": False, "error": f"missing_required:{missing}", "row": row}
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    local = os.environ.get("SHARED_INTEL_LOCAL_TRADES", "").strip()
    if local:
        path = Path(local)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        result = {"ok": True, "path": str(path), "local": True}
    else:
        result = _remote_flock_append(REMOTE_TRADES, line)
    result["trade_id"] = row.get("trade_id")
    result["pnl_usd"] = row.get("pnl_usd")
    result["setup"] = row.get("setup")
    _mirror_local_line(line)
    if not local:
        write_heartbeat({"last_trade_id": row.get("trade_id"), "last_pnl_usd": row.get("pnl_usd")})
    return result


def _mirror_local_line(line: str) -> None:
    """Best-effort evidence mirror. Does not create /home/box on a fresh machine."""
    override = os.environ.get("SHARED_INTEL_MIRROR_PATH", "").strip()
    if override:
        dest = Path(override)
    else:
        pack = Path("/home/box/agent-data/projects/trading-desk/evidence")
        if not pack.is_dir():
            return
        dest = pack / "shared_intel_trades_mirror.jsonl"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as handle:
            handle.write(line if line.endswith("\n") else line + "\n")
    except OSError:
        return


def write_positions_open(positions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "schema": "shared-intel.positions_open.v1",
        "as_of_pt": _pt_now(),
        "positions": positions or [],
        "invented": False,
        "secrets": False,
    }
    return _remote_write_json(REMOTE_POSITIONS, payload)


def write_daily_equity(
    *,
    date_pt: str,
    equity: float,
    realized_pnl: float,
    cash: float | None = None,
) -> dict[str, Any]:
    row = {
        "schema": "shared-intel.daily_equity.v1",
        "date_pt": date_pt,
        "equity": equity,
        "realized_pnl": realized_pnl,
        "cash": cash,
        "emitted_pt": _pt_now(),
        "invented": False,
        "secrets": False,
    }
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    return _remote_flock_append(REMOTE_EQUITY, line)


def write_heartbeat(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "schema": "shared-intel.heartbeat.v1",
        "agent": "grok_trading_bot",
        "last_write_pt": _pt_now(),
        "trades_path": REMOTE_TRADES,
        "invented": False,
        "secrets": False,
    }
    if extra:
        payload.update(extra)
    return _remote_write_json(REMOTE_HEARTBEAT, payload)
