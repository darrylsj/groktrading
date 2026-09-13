"""Desk defaults and pack paths for the observational strategy factory.

``live_gate`` is forced false in code. Editing the JSON cannot flip the live
order path. This tool never calls Tradier or Unusual Whales.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIVE_GATE = False
PLACES_ORDERS = False
PACK_ENV = "STRATEGY_FACTORY_PACK"
CONFIG_NAME = "strategy_factory.json"

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_CONFIG = REPO_ROOT / "config" / CONFIG_NAME

CATEGORIES = (
    "flow_debit_bto",
    "i4_defined_risk_credit",
    "gex_shadow_obs",
    "overnight_carry",
    "external_shadow",
    "other",
)
STAGES = (
    "candidate",
    "paper",
    "validated",
    "live_allow",
    "rejected",
    "killed",
    "retired",
)
OPEN_STAGES = frozenset({"candidate", "paper", "validated", "live_allow"})
TERMINAL_STAGES = frozenset({"rejected", "killed", "retired"})
FORWARD = {
    "candidate": "paper",
    "paper": "validated",
    "validated": "live_allow",
}
REJECT_FROM = frozenset({"candidate", "paper", "validated"})
KILL_FROM = frozenset({"candidate", "paper", "validated", "live_allow"})
RETIRE_FROM = frozenset({"validated", "live_allow"})

CONFIRMATION_SOURCES = (
    "uw_print",
    "tradier_fresh_ask",
    "gex_agree",
    "shortlist_hit",
    "helsinki_fresh",
    "mechanism_named",
    "falsifier_named",
)

EVENTS_REL = Path("evidence") / "strategy_factory_events.jsonl"
LEDGER_REL = Path("evidence") / "strategy_factory_ledger.jsonl"
ACTIVE_REL = Path("state") / "strategy_factory_active.json"

DESK_DEFAULTS: dict[str, Any] = {
    "kind": "strategy_factory_config",
    "live_gate": False,
    "places_orders": False,
    "max_active_per_category_per_session": 3,
    "min_confirmations_for_validated": 2,
    "min_confirmations_for_live_allow": 3,
    "require_falsifier_for_live_allow": True,
    "require_mechanism_for_validated": True,
    "confirmation_sources": list(CONFIRMATION_SOURCES),
    "categories": list(CATEGORIES),
}


class FactoryError(ValueError):
    """Fail-closed strategy-factory reject. ``code`` is the stable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class DeskConfig:
    max_active_per_category_per_session: int
    min_confirmations_for_validated: int
    min_confirmations_for_live_allow: int
    require_falsifier_for_live_allow: bool
    require_mechanism_for_validated: bool
    confirmation_sources: frozenset[str]
    categories: frozenset[str]
    live_gate: bool = LIVE_GATE
    places_orders: bool = PLACES_ORDERS

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "strategy_factory_config",
            "live_gate": LIVE_GATE,
            "places_orders": PLACES_ORDERS,
            "max_active_per_category_per_session": self.max_active_per_category_per_session,
            "min_confirmations_for_validated": self.min_confirmations_for_validated,
            "min_confirmations_for_live_allow": self.min_confirmations_for_live_allow,
            "require_falsifier_for_live_allow": self.require_falsifier_for_live_allow,
            "require_mechanism_for_validated": self.require_mechanism_for_validated,
            "confirmation_sources": sorted(self.confirmation_sources),
            "categories": sorted(self.categories),
        }


@dataclass(frozen=True)
class PackPaths:
    root: Path
    events: Path
    ledger: Path
    active: Path


def pack_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(PACK_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT


def pack_paths(root: str | Path | None = None) -> PackPaths:
    base = pack_root(root)
    return PackPaths(
        root=base,
        events=base / EVENTS_REL,
        ledger=base / LEDGER_REL,
        active=base / ACTIVE_REL,
    )


def resolve_config_path(
    pack: Path | None = None,
    explicit: str | Path | None = None,
) -> Path | None:
    if explicit is not None and str(explicit).strip():
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FactoryError("config_missing", f"config not found: {path}")
        return path
    if pack is not None:
        candidate = pack / "config" / CONFIG_NAME
        if candidate.is_file():
            return candidate
    if REPO_CONFIG.is_file():
        return REPO_CONFIG
    return None


def _as_int(value: object, field: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise FactoryError("config_invalid", f"{field} must be an integer")
    if value < 0:
        raise FactoryError("config_invalid", f"{field} must be >= 0")
    return value


def _as_bool(value: object, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise FactoryError("config_invalid", f"{field} must be a boolean")
    return value


def _as_str_set(value: object, field: str, default: tuple[str, ...]) -> frozenset[str]:
    if value is None:
        return frozenset(default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FactoryError("config_invalid", f"{field} must be a list of strings")
    return frozenset(item.strip() for item in value if item.strip())


def load_config(
    pack: str | Path | None = None,
    explicit: str | Path | None = None,
) -> DeskConfig:
    """Load desk config. ``live_gate`` is always false after load."""
    root = pack_root(pack)
    path = resolve_config_path(root, explicit)
    raw: dict[str, Any] = dict(DESK_DEFAULTS)
    if path is not None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, Mapping):
            raise FactoryError("config_invalid", "config must be a JSON object")
        raw.update(dict(doc))
    sources = _as_str_set(
        raw.get("confirmation_sources"),
        "confirmation_sources",
        CONFIRMATION_SOURCES,
    )
    categories = _as_str_set(raw.get("categories"), "categories", CATEGORIES)
    unknown_cats = categories - frozenset(CATEGORIES)
    if unknown_cats:
        raise FactoryError(
            "unknown_category",
            "config categories not on the allowlist: " + ", ".join(sorted(unknown_cats)),
        )
    unknown_src = sources - frozenset(CONFIRMATION_SOURCES)
    if unknown_src:
        raise FactoryError(
            "unknown_source",
            "config confirmation_sources not on the allowlist: " + ", ".join(sorted(unknown_src)),
        )
    return DeskConfig(
        max_active_per_category_per_session=_as_int(
            raw.get("max_active_per_category_per_session"),
            "max_active_per_category_per_session",
            3,
        ),
        min_confirmations_for_validated=_as_int(
            raw.get("min_confirmations_for_validated"),
            "min_confirmations_for_validated",
            2,
        ),
        min_confirmations_for_live_allow=_as_int(
            raw.get("min_confirmations_for_live_allow"),
            "min_confirmations_for_live_allow",
            3,
        ),
        require_falsifier_for_live_allow=_as_bool(
            raw.get("require_falsifier_for_live_allow"),
            "require_falsifier_for_live_allow",
            True,
        ),
        require_mechanism_for_validated=_as_bool(
            raw.get("require_mechanism_for_validated"),
            "require_mechanism_for_validated",
            True,
        ),
        confirmation_sources=sources,
        categories=categories,
        live_gate=LIVE_GATE,
        places_orders=PLACES_ORDERS,
    )
