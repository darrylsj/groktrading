"""Grok/LLM decision interface.

The model returns approve/skip plus a thesis from assembled facts only.
It must never invent prices or call a broker.

The LLM sits outside the broker execution boundary. It must never set OCC,
qty, limit, account, or order action. Those fields are owned by the
deterministic gate / executor after an approve on frozen facts.
"""

from __future__ import annotations

from typing import Protocol

from groktrading.models import AssembledFacts, LLMDecision

FORBIDDEN_LLM_ATTRS = (
    "tradier",
    "broker",
    "place_order",
    "order_client",
    "account_id",
    "submit",
)
FORBIDDEN_LLM_DECISION_FIELDS = (
    "occ",
    "option_symbol",
    "quantity",
    "qty",
    "limit",
    "limit_price",
    "proposed_limit",
    "account",
    "account_id",
    "order_action",
    "side",
    "order",
)


class ThesisLLM(Protocol):
    def decide(self, facts: AssembledFacts) -> LLMDecision:
        """Return approve or skip. Implementations must not accept a broker client."""


class StaticSkipLLM:
    """Safe default: skip everything. Useful for signals-only dry runs."""

    def decide(self, facts: AssembledFacts) -> LLMDecision:
        return LLMDecision(
            action="skip",
            thesis="Default skip: no model attached. Facts were not used to invent a price.",
            facts_digest=facts.signal_id,
            model_label="static-skip",
        )


def assert_no_broker_attr(llm: object) -> None:
    names = set(dir(llm))
    for name in FORBIDDEN_LLM_ATTRS:
        if name in names and not name.startswith("_"):
            raise TypeError(f"LLM adapter must not expose broker surface: {name}")


def assert_llm_decision_boundary(decision: LLMDecision) -> None:
    """Refuse any attempt to hang order fields on the decision object."""
    dumped = decision.model_dump()
    for name in FORBIDDEN_LLM_DECISION_FIELDS:
        if name in dumped:
            raise TypeError(f"LLM decision must not set {name}")
    if decision.action not in {"approve", "skip"}:
        raise TypeError("LLM may only approve or skip")
