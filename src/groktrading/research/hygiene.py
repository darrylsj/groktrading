"""Pre-LLM universe hygiene for Opening15 expanded/select.

Deterministic filters run before the model and are logged (which gate fired).
The LLM is reserved for judgment (thesis coherence, cite-or-abstain). Computable
refuse rules live here, not in the selector prompt.

Paper research path only. Not imported by `research.cli run` / `recommend()`,
and not part of the live Tradier/Helsinki order path.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")
CONTRACT_MULTIPLIER = 100
# Planning frame documented across README / SAFETY / ARCHITECTURE. Not funded cash.
DEFAULT_PLANNING_EQUITY_USD = 25_000.0
# 0.8% of $25k = $200 debit = $2.00/share at one lot. Derived, not a $1–3 hard range.
DEFAULT_PREMIUM_BUDGET_PCT = 0.008
DEFAULT_DTE_MIN = 0
DEFAULT_DTE_MAX = 45
DEFAULT_MAX_SPREAD = 0.50
DEFAULT_MAX_SPREAD_FRAC = 0.25


class HygieneSettings(BaseModel):
    """Select-path shortlist knobs. Defaults are research hygiene, not live-card gates.

    `planning_equity_usd` is the $25,000 planning frame when the frozen context has
    no known account equity or cash. `premium_budget_pct` is the max one-lot debit
    as a fraction of that base (equity, else cash, else planning). Max premium per
    share is `base * pct / 100`. Do not replace this with a hard-coded $1–3 band.

    `dte_min` / `dte_max` are a configurable window. DTE is logged on every keep
    and reject so shadow data can split 0–2 vs longer. The default window includes
    both; it is not an overnight-horizon policy.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    planning_equity_usd: float = Field(default=DEFAULT_PLANNING_EQUITY_USD, gt=0)
    premium_budget_pct: float = Field(default=DEFAULT_PREMIUM_BUDGET_PCT, gt=0, le=1)
    dte_min: int = Field(default=DEFAULT_DTE_MIN, ge=0)
    dte_max: int = Field(default=DEFAULT_DTE_MAX, ge=0)
    max_spread: float = Field(default=DEFAULT_MAX_SPREAD, gt=0)
    max_spread_frac: float = Field(default=DEFAULT_MAX_SPREAD_FRAC, gt=0, le=1)
    min_volume: int = Field(default=1, ge=0)
    min_open_interest: int = Field(default=0, ge=0)
    require_ask_side_tag: bool = False

    @property
    def max_debit_usd(self) -> float:
        return self.planning_equity_usd * self.premium_budget_pct


class HygieneBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    base_usd: float
    premium_budget_pct: float
    max_debit_usd: float
    max_premium_per_share: float
    multiplier: int = CONTRACT_MULTIPLIER


def as_number(value: Any) -> float | None:
    """Parse a provider number. Never invent a substitute."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def as_int(value: Any) -> int | None:
    number = as_number(value)
    if number is None:
        return None
    return int(number)


def normalize_occ(symbol: str) -> str:
    return "".join(str(symbol).split()).replace("-", "").upper()


def parse_occ(symbol: str) -> dict[str, Any] | None:
    occ = normalize_occ(symbol)
    match = OCC_RE.fullmatch(occ)
    if not match:
        return None
    root, yymmdd, right, strike_raw = match.groups()
    try:
        expiry = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
        strike = int(strike_raw) / 1000
    except ValueError:
        return None
    return {
        "root": root,
        "expiration": expiry,
        "right": right,
        "strike": strike,
        "occ": occ,
    }


def parse_expiration(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if type(value) is date:
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def dte_days(session: date, expiration: date | None) -> int | None:
    if expiration is None:
        return None
    return (expiration - session).days


def _provider_side_label(raw: dict[str, Any]) -> str:
    """Copy of capture.provider_aggressor: UW tags only, never infer from NBBO."""
    tokens: list[str] = []
    for key in ("tags", "tag"):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            tokens.extend(str(item).lower() for item in value)
        else:
            tokens.append(str(value).lower())
    if any(token == "ask_side" or token.endswith("ask_side") for token in tokens):
        return "ask_side"
    if any(token == "bid_side" or token.endswith("bid_side") for token in tokens):
        return "bid_side"
    return "unknown"


def dte_bucket(dte: int | None) -> str:
    if dte is None:
        return "unknown"
    if dte <= 2:
        return "0-2"
    return "3+"


def observed_premium(*, ask: float | None, print_price: float | None, last: float | None) -> tuple[float | None, str | None]:
    if ask is not None:
        return ask, "ask"
    if print_price is not None:
        return print_price, "print_price"
    if last is not None:
        return last, "last"
    return None, None


def resolve_budget(settings: HygieneSettings, context_records: list[Any]) -> HygieneBudget:
    equity: float | None = None
    cash: float | None = None
    for record in context_records:
        if getattr(record, "category", None) != "portfolio":
            continue
        payload = getattr(record, "payload", {}) or {}
        if not isinstance(payload, dict):
            continue
        if equity is None:
            equity = as_number(payload.get("equity"))
        if cash is None:
            cash = as_number(payload.get("cash"))
    if equity is not None:
        base, source = equity, "account_equity"
    elif cash is not None:
        base, source = cash, "account_cash"
    else:
        base, source = settings.planning_equity_usd, "planning_equity"
    max_debit = base * settings.premium_budget_pct
    return HygieneBudget(
        source=source,
        base_usd=base,
        premium_budget_pct=settings.premium_budget_pct,
        max_debit_usd=max_debit,
        max_premium_per_share=max_debit / CONTRACT_MULTIPLIER,
    )


def _row(
    *,
    symbol: str,
    contract: str,
    dte: int | None,
    sources: list[str],
    evidence_ids: list[str],
    bid: float | None,
    ask: float | None,
    premium: float | None,
    premium_source: str | None,
    volume: int | None,
    open_interest: int | None,
    ask_side_tag: bool | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spread = None
    spread_frac = None
    if bid is not None and ask is not None:
        spread = ask - bid
        spread_frac = spread / ask if ask > 0 else None
    body: dict[str, Any] = {
        "symbol": symbol,
        "contract": contract,
        "dte": dte,
        "dte_bucket": dte_bucket(dte),
        "sources": sources,
        "evidence_ids": evidence_ids,
        "bid": bid,
        "ask": ask,
        "premium": premium,
        "premium_source": premium_source,
        "spread": spread,
        "spread_frac": spread_frac,
        "volume": volume,
        "open_interest": open_interest,
        "ask_side_tag": ask_side_tag,
    }
    if extra:
        body.update(extra)
    return body


def _reject(gate: str, why: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate": gate,
        "symbol": row["symbol"],
        "contract": row["contract"],
        "why": why,
        "dte": row["dte"],
        "dte_bucket": row["dte_bucket"],
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "premium": row.get("premium"),
        "premium_source": row.get("premium_source"),
        "volume": row.get("volume"),
        "open_interest": row.get("open_interest"),
        "ask_side_tag": row.get("ask_side_tag"),
        "sources": row.get("sources"),
    }


class _Observed:
    __slots__ = (
        "symbol",
        "contract",
        "sources",
        "evidence_ids",
        "bid",
        "ask",
        "last",
        "print_price",
        "volume",
        "open_interest",
        "expiration",
        "tags_seen",
        "ask_side_tag",
    )

    def __init__(self, symbol: str, contract: str) -> None:
        self.symbol = symbol
        self.contract = contract
        self.sources: list[str] = []
        self.evidence_ids: list[str] = []
        self.bid: float | None = None
        self.ask: float | None = None
        self.last: float | None = None
        self.print_price: float | None = None
        self.volume: int | None = None
        self.open_interest: int | None = None
        self.expiration: date | None = None
        self.tags_seen = False
        self.ask_side_tag: bool | None = None

    def add_source(self, name: str) -> None:
        if name not in self.sources:
            self.sources.append(name)

    def add_evidence(self, evidence_id: str) -> None:
        if evidence_id and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)

    def fill_quote(self, *, bid: Any = None, ask: Any = None, last: Any = None) -> None:
        if self.bid is None:
            self.bid = as_number(bid)
        if self.ask is None:
            self.ask = as_number(ask)
        if self.last is None:
            self.last = as_number(last)

    def fill_liquidity(self, *, volume: Any = None, open_interest: Any = None) -> None:
        if self.volume is None:
            self.volume = as_int(volume)
        if self.open_interest is None:
            self.open_interest = as_int(open_interest)

    def note_ask_side(self, raw: dict[str, Any]) -> None:
        if "tags" not in raw and "tag" not in raw:
            return
        self.tags_seen = True
        label = _provider_side_label(raw)
        if label == "ask_side":
            self.ask_side_tag = True
        elif self.ask_side_tag is not True:
            self.ask_side_tag = False


def _get(records: dict[str, _Observed], symbol: str, contract: str) -> _Observed:
    occ = normalize_occ(contract)
    item = records.get(occ)
    if item is None:
        item = _Observed(symbol, occ)
        records[occ] = item
    elif not item.symbol and symbol:
        item.symbol = symbol
    return item


def collect_universe(
    packet: Any,
    context_records: list[Any],
) -> dict[str, _Observed]:
    """Build observed contracts from frozen packet prints and context chains.

    Fields are copied only when present. Prices are never invented.
    """
    records: dict[str, _Observed] = {}
    symbols = set(packet.config.symbols)
    for event in packet.events:
        if event.kind != "option_trade":
            continue
        if event.symbol not in symbols:
            continue
        contract = event.raw.get("option_chain_id") or event.raw.get("option_symbol")
        if not contract:
            continue
        item = _get(records, event.symbol, str(contract))
        item.add_source("packet_print")
        item.add_evidence(event.event_id)
        item.fill_quote(
            bid=event.raw.get("nbbo_bid") if event.raw.get("nbbo_bid") not in (None, "") else event.raw.get("bid"),
            ask=event.raw.get("nbbo_ask") if event.raw.get("nbbo_ask") not in (None, "") else event.raw.get("ask"),
            last=event.raw.get("last"),
        )
        if item.print_price is None:
            item.print_price = as_number(event.raw.get("price"))
        item.fill_liquidity(
            volume=event.raw.get("volume"),
            open_interest=event.raw.get("open_interest")
            or event.raw.get("prior_session_open_interest"),
        )
        parsed = parse_occ(item.contract)
        if parsed and item.expiration is None:
            item.expiration = parsed["expiration"]
        item.note_ask_side(event.raw)

    for record in context_records:
        category = getattr(record, "category", None)
        payload = getattr(record, "payload", {}) or {}
        evidence_id = getattr(record, "evidence_id", "")
        if not isinstance(payload, dict):
            continue
        if category == "option_chain":
            expiration = parse_expiration(payload.get("expiration") or payload.get("expiration_date"))
            for contract in payload.get("contracts") or []:
                if not isinstance(contract, dict):
                    continue
                symbol = str(
                    contract.get("underlying")
                    or (record.symbols[0] if getattr(record, "symbols", None) else "")
                    or ""
                )
                occ = contract.get("symbol") or contract.get("option_symbol")
                if not occ:
                    continue
                if symbol and symbol not in symbols:
                    continue
                if not symbol:
                    parsed = parse_occ(str(occ))
                    symbol = parsed["root"] if parsed else ""
                    if symbol not in symbols:
                        continue
                item = _get(records, symbol, str(occ))
                item.add_source("option_chain")
                item.add_evidence(evidence_id)
                item.fill_quote(
                    bid=contract.get("bid"),
                    ask=contract.get("ask"),
                    last=contract.get("last"),
                )
                item.fill_liquidity(
                    volume=contract.get("volume"),
                    open_interest=contract.get("prior_session_open_interest")
                    or contract.get("open_interest"),
                )
                if item.expiration is None:
                    item.expiration = parse_expiration(contract.get("expiration_date")) or expiration
        elif category == "option_screener":
            rows = payload.get("contracts") or payload.get("rows") or []
            if isinstance(payload.get("option_symbol"), str):
                rows = [payload, *rows] if rows else [payload]
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                occ = row.get("option_symbol") or row.get("symbol")
                symbol = str(row.get("ticker_symbol") or row.get("ticker") or "")
                if not occ:
                    continue
                if not symbol:
                    parsed = parse_occ(str(occ))
                    symbol = parsed["root"] if parsed else ""
                if symbol not in symbols:
                    continue
                item = _get(records, symbol, str(occ))
                item.add_source("option_screener")
                item.add_evidence(evidence_id)
                item.fill_quote(ask=row.get("avg_price"), last=row.get("avg_price"))
                if item.print_price is None:
                    # Screener "premium" is often notional USD, not per-share. Do not use it as ask.
                    item.print_price = as_number(row.get("avg_price"))
                item.fill_liquidity(
                    volume=row.get("volume"),
                    open_interest=row.get("open_interest"),
                )
                if item.expiration is None:
                    item.expiration = parse_expiration(row.get("expiry") or row.get("expiration"))
    return records


def apply_gates(
    item: _Observed,
    *,
    session: date,
    symbols: set[str],
    settings: HygieneSettings,
    budget: HygieneBudget,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    parsed = parse_occ(item.contract)
    if item.expiration is None and parsed:
        item.expiration = parsed["expiration"]
    if not item.symbol and parsed:
        item.symbol = parsed["root"]
    dte = dte_days(session, item.expiration)
    premium, premium_source = observed_premium(
        ask=item.ask, print_price=item.print_price, last=item.last
    )
    row = _row(
        symbol=item.symbol,
        contract=item.contract,
        dte=dte,
        sources=list(item.sources),
        evidence_ids=list(item.evidence_ids),
        bid=item.bid,
        ask=item.ask,
        premium=premium,
        premium_source=premium_source,
        volume=item.volume,
        open_interest=item.open_interest,
        ask_side_tag=item.ask_side_tag if item.tags_seen else None,
    )

    if item.symbol not in symbols:
        return None, _reject("universe", "contract underlying is outside the frozen ten-stock universe", row)
    if not item.contract:
        return None, _reject("universe", "missing option symbol", row)

    if dte is not None and (dte < settings.dte_min or dte > settings.dte_max):
        return None, _reject(
            "dte_window",
            f"dte {dte} outside configurable window [{settings.dte_min}, {settings.dte_max}]",
            row,
        )

    if premium is None:
        return None, _reject(
            "premium_unobserved",
            "no observed ask, print price, or last; premium not invented",
            row,
        )
    if premium <= 0:
        return None, _reject("premium_budget", "observed premium is not positive", row)
    if premium > budget.max_premium_per_share:
        return None, _reject(
            "premium_budget",
            (
                f"observed {premium_source} {premium} exceeds budget-derived max "
                f"premium {budget.max_premium_per_share} "
                f"(base={budget.base_usd} {budget.source} * "
                f"{budget.premium_budget_pct} / {CONTRACT_MULTIPLIER})"
            ),
            row,
        )

    if item.bid is not None and item.ask is not None:
        spread = item.ask - item.bid
        if item.ask <= 0:
            return None, _reject("spread", "observed ask is not positive", row)
        if item.bid > item.ask:
            return None, _reject("spread", "observed bid exceeds ask (crossed)", row)
        frac = spread / item.ask
        if spread > settings.max_spread or frac > settings.max_spread_frac:
            return None, _reject(
                "spread",
                (
                    f"observed spread {spread} (frac {frac:.4f}) exceeds "
                    f"max_spread={settings.max_spread} or "
                    f"max_spread_frac={settings.max_spread_frac}"
                ),
                row,
            )

    if item.volume is not None and item.volume < settings.min_volume:
        return None, _reject(
            "liquidity",
            f"observed volume {item.volume} < min_volume {settings.min_volume}",
            row,
        )
    if item.volume is None and item.open_interest is not None:
        if item.open_interest < settings.min_open_interest:
            return None, _reject(
                "liquidity",
                (
                    f"volume unobserved; open_interest {item.open_interest} < "
                    f"min_open_interest {settings.min_open_interest}"
                ),
                row,
            )

    if settings.require_ask_side_tag and item.tags_seen and item.ask_side_tag is not True:
        return None, _reject(
            "ask_side",
            "tags were present and did not include a provider ask_side tag",
            row,
        )

    return row, None


def build_shortlist(
    packet: Any,
    context_records: list[Any] | None = None,
    settings: HygieneSettings | None = None,
) -> dict[str, Any]:
    """Return a candidates.json artifact: kept rows plus structured rejects."""
    context_records = list(context_records or [])
    cfg = getattr(packet.config, "hygiene", None)
    resolved = settings or cfg or HygieneSettings()
    budget = resolve_budget(resolved, context_records)
    universe = collect_universe(packet, context_records)
    symbols = set(packet.config.symbols)
    candidates: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for contract in sorted(universe):
        kept, dropped = apply_gates(
            universe[contract],
            session=packet.session,
            symbols=symbols,
            settings=resolved,
            budget=budget,
        )
        if dropped:
            rejects.append(dropped)
        elif kept:
            candidates.append(kept)
    return {
        "architecture": "gates_then_judgment",
        "path": "opening15_expanded_select",
        "session": str(packet.session),
        "budget": budget.model_dump(),
        "dte_window": {"min": resolved.dte_min, "max": resolved.dte_max},
        "settings": resolved.model_dump(),
        "candidates": candidates,
        "rejects": rejects,
        "stats": {
            "universe": len(universe),
            "kept": len(candidates),
            "dropped": len(rejects),
        },
    }


def shortlist_contracts(artifact: dict[str, Any]) -> set[str]:
    return {str(row["contract"]) for row in artifact.get("candidates") or []}
