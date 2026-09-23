"""Tradier sandbox paper client.

Account id and access token come from the environment
(``TRADIER_PAPER_ACCOUNT_ID``, ``TRADIER_PAPER_ACCESS_TOKEN``). They are not
stored in this tree. The only HTTP base is ``https://sandbox.tradier.com/v1``.

``place_option`` is a local dry-run unless ``submit=True`` or ``preview=True``.
Sell-to-open is refused. Quantity is one lot.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

PAPER_API_BASE = "https://sandbox.tradier.com/v1"
LIVE_HOST = "api.tradier.com"
_OCC_ROOT = re.compile(r"^([A-Z]+)")
_ENTRY_SIDES = {"buy_to_open", "sell_to_close", "buy_to_close"}


class PaperConfigError(RuntimeError):
    """Paper target, credential, or order shape is not allowed."""


def paper_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    raw = source if source is not None else os.environ
    return {str(key): str(value) for key, value in raw.items()}


def _assert_base(base: str) -> str:
    cleaned = base.strip().rstrip("/")
    host = (urllib.parse.urlsplit(cleaned).hostname or "").lower()
    if host != "sandbox.tradier.com":
        raise PaperConfigError(
            "paper base must be https://sandbox.tradier.com/v1; never live api.tradier.com"
        )
    if LIVE_HOST in cleaned.lower():
        raise PaperConfigError("REFUSE: live Tradier host in paper client")
    if not cleaned.endswith("/v1"):
        cleaned = cleaned + "/v1"
    if cleaned != PAPER_API_BASE:
        raise PaperConfigError(f"paper base must be {PAPER_API_BASE}")
    return cleaned


class TradierPaperClient:
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        opener: Any = None,
    ) -> None:
        loaded = paper_env(env)
        account = loaded.get("TRADIER_PAPER_ACCOUNT_ID", "").strip()
        base = loaded.get("TRADIER_PAPER_API_BASE", PAPER_API_BASE)
        token = loaded.get("TRADIER_PAPER_ACCESS_TOKEN", "").strip()
        live_account = loaded.get("TRADIER_LIVE_ACCOUNT_ID", "").strip()
        if not account:
            raise PaperConfigError("missing TRADIER_PAPER_ACCOUNT_ID")
        if live_account and account == live_account:
            raise PaperConfigError("REFUSE: paper account matches TRADIER_LIVE_ACCOUNT_ID")
        if LIVE_HOST in account.lower():
            raise PaperConfigError("REFUSE: live Tradier host in paper account")
        self.account = account
        self.base = _assert_base(base)
        self.token = token
        self._opener = opener or urllib.request.urlopen

    def _req(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise PaperConfigError("missing TRADIER_PAPER_ACCESS_TOKEN")
        _assert_base(self.base)
        url = f"{self.base}{path}"
        if LIVE_HOST in url.lower() or "sandbox.tradier.com" not in url:
            raise PaperConfigError("REFUSE: paper request left the sandbox host")
        body = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "GrokTrading-Paper/1.0",
        }
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            err = exc.read().decode(errors="replace")
            raise PaperConfigError(f"Tradier paper HTTP {exc.code}: {err[:240]}") from exc

    def balances(self) -> dict[str, Any]:
        return self._req("GET", f"/accounts/{self.account}/balances")

    def quote(self, symbols: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"symbols": symbols, "greeks": "false"})
        return self._req("GET", f"/markets/quotes?{query}")

    def place_option(
        self,
        *,
        option_symbol: str,
        side: str,
        quantity: int = 1,
        order_type: str = "limit",
        price: float | None = None,
        duration: str = "day",
        submit: bool = False,
        preview: bool = False,
    ) -> dict[str, Any]:
        """One-lot option order. Default returns the form and does not POST."""
        if quantity != 1:
            raise PaperConfigError("paper path is one-lot only")
        side_l = side.lower().replace(" ", "_")
        if side_l == "sell_to_open":
            raise PaperConfigError("REFUSE: sell_to_open not enabled on paper one-lot path")
        if side_l not in _ENTRY_SIDES:
            raise PaperConfigError(f"bad side {side}")
        if submit and preview:
            raise PaperConfigError("choose submit or preview, not both")
        root = _OCC_ROOT.match(option_symbol)
        form: dict[str, Any] = {
            "class": "option",
            "symbol": root.group(1) if root else option_symbol[:6].strip(),
            "option_symbol": option_symbol,
            "side": side_l,
            "quantity": quantity,
            "type": order_type,
            "duration": duration,
        }
        if order_type == "limit":
            if price is None:
                raise PaperConfigError("limit requires price")
            form["price"] = f"{float(price):.2f}"
        if not submit and not preview:
            return {
                "dry_run": True,
                "places_orders": False,
                "preview": False,
                "account": self.account,
                "base": self.base,
                "form": form,
            }
        if preview:
            form["preview"] = "true"
        response = self._req("POST", f"/accounts/{self.account}/orders", form)
        return {
            "dry_run": False,
            "places_orders": bool(submit),
            "preview": bool(preview),
            "account": self.account,
            "base": self.base,
            "response": response,
        }
