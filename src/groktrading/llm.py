"""Grok/LLM decision interface.

The model returns approve/skip plus a thesis from assembled facts only.
It must never invent prices or call a broker.
"""

from __future__ import annotations

from typing import Protocol

from groktrading.models import AssembledFacts, LLMDecision


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
    forbidden = ("tradier", "broker", "place_order", "order_client")
    names = set(dir(llm))
    for name in forbidden:
        if name in names and not name.startswith("_"):
            raise TypeError(f"LLM adapter must not expose broker surface: {name}")
