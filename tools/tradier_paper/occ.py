"""Build OCC option symbols from idea legs. Does not invent prices."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def to_occ(underlying: str, expiry: str, right: str, strike: float) -> str:
    root = re.sub(r"[^A-Z]", "", underlying.upper())[:6]
    if len(root) < 1:
        raise ValueError("bad underlying")
    parsed = datetime.strptime(expiry[:10], "%Y-%m-%d")
    yymmdd = parsed.strftime("%y%m%d")
    cp = right.upper()[0]
    if cp not in "CP":
        raise ValueError(f"bad right {right}")
    strike_millis = int(round(float(strike) * 1000))
    if strike_millis < 0 or strike_millis > 99_999_999:
        raise ValueError(f"bad strike {strike}")
    return f"{root}{yymmdd}{cp}{strike_millis:08d}"


def legs_to_occs(ticker: str, legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for leg in legs or []:
        expiry = leg.get("expiry") or leg.get("expiration")
        right = leg.get("right") or leg.get("option_type")
        strike = leg.get("strike")
        side = str(leg.get("side") or "").upper()
        if not (expiry and right and strike is not None):
            continue
        if side in {"LONG", "BUY", "BTO"}:
            tradier_side = "buy_to_open"
        elif side in {"SHORT", "SELL", "STO"}:
            tradier_side = "sell_to_open"
        else:
            tradier_side = None
        out.append(
            {
                "occ": to_occ(ticker, str(expiry), str(right), float(strike)),
                "side": tradier_side,
                "leg": leg,
            }
        )
    return out
