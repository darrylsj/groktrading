"""Hashed eligibility / evidence manifest for Opening15 select → resolve.

Deterministic comparison-universe declaration lives outside the LLM prompt.
Tuesday packet-only `research.cli run` / `recommend()` does not write this
artifact; evaluate/monitor/resolve then default to the printed packet tape.
"""

from __future__ import annotations

from typing import Any

from groktrading.research.hygiene import shortlist_contracts
from groktrading.research.opening15 import (
    EXPANDED_SELECT_EXPERIMENT_ID,
    PACKET_BASELINE_EXPERIMENT_ID,
    Decision,
    Packet,
    digest,
)

UNIVERSE_PACKET = "packet_printed"
UNIVERSE_SHORTLIST = "hygiene_shortlist"
FIXED_K_VALUES = (1, 2, 3)


def packet_contracts(packet: Packet) -> list[str]:
    return sorted(
        {str(event.raw["option_chain_id"]) for event in packet.events if event.kind == "option_trade"}
    )


def packet_evidence_ids(packet: Packet) -> set[str]:
    return {event.event_id for event in packet.events}


def _manifest_body(
    *,
    universe: str,
    contracts: list[str],
    evidence_ids: list[str],
    packet_contracts_list: list[str],
    hygiene_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    shortlist_only = sorted(set(contracts) - set(packet_contracts_list))
    return {
        "universe": universe,
        "contracts": contracts,
        "evidence_ids": evidence_ids,
        "packet_contracts": packet_contracts_list,
        "shortlist_only_contracts": shortlist_only,
        "hygiene_settings": hygiene_settings,
        "declared_before_inference": True,
    }


def attach_manifest_hash(body: dict[str, Any]) -> dict[str, Any]:
    hashed = dict(body)
    hashed["manifest_hash"] = digest(body)
    return hashed


def verify_eligibility(manifest: dict[str, Any]) -> None:
    recorded = manifest.get("manifest_hash")
    body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if not recorded or digest(body) != recorded:
        raise ValueError("eligibility manifest hash mismatch")


def packet_eligibility(packet: Packet) -> dict[str, Any]:
    contracts = packet_contracts(packet)
    return attach_manifest_hash(
        _manifest_body(
            universe=UNIVERSE_PACKET,
            contracts=contracts,
            evidence_ids=sorted(packet_evidence_ids(packet)),
            packet_contracts_list=contracts,
            hygiene_settings=None,
        )
    )


def build_shortlist_eligibility(
    packet: Packet,
    context_records: list[Any],
    shortlist: dict[str, Any],
) -> dict[str, Any]:
    extra_ids = {
        str(getattr(record, "evidence_id"))
        for record in context_records
        if getattr(record, "evidence_id", None)
    }
    contracts = sorted(shortlist_contracts(shortlist))
    settings = packet.config.hygiene.model_dump()
    return attach_manifest_hash(
        _manifest_body(
            universe=UNIVERSE_SHORTLIST,
            contracts=contracts,
            evidence_ids=sorted(packet_evidence_ids(packet) | extra_ids),
            packet_contracts_list=packet_contracts(packet),
            hygiene_settings=settings,
        )
    )


def resolve_eligibility(packet: Packet, record: dict[str, Any] | None = None) -> dict[str, Any]:
    record = record or {}
    stored = record.get("eligibility")
    if stored:
        if not isinstance(stored, dict):
            raise ValueError("eligibility manifest must be an object")
        verify_eligibility(stored)
        return stored
    if record.get("eligibility_hash"):
        raise ValueError("eligibility hash present without eligibility manifest")
    return packet_eligibility(packet)


def apply_eligibility(decision: Decision, packet: Packet, eligibility: dict[str, Any]) -> None:
    extra = set(eligibility["evidence_ids"]) - packet_evidence_ids(packet)
    decision.validate_evidence(
        packet,
        allowed_contracts=set(eligibility["contracts"]),
        extra_evidence_ids=extra,
    )


def infer_experiment_id(record: dict[str, Any], eligibility: dict[str, Any]) -> str:
    recorded = record.get("experiment_id")
    if recorded:
        return str(recorded)
    if eligibility.get("universe") == UNIVERSE_SHORTLIST:
        return EXPANDED_SELECT_EXPERIMENT_ID
    if record.get("context_citations") is not None:
        return EXPANDED_SELECT_EXPERIMENT_ID
    return PACKET_BASELINE_EXPERIMENT_ID


def infer_prompt_version(record: dict[str, Any], eligibility: dict[str, Any]) -> str:
    recorded = record.get("prompt_version")
    if recorded:
        return str(recorded)
    if eligibility.get("universe") == UNIVERSE_SHORTLIST:
        return "selector_v2"
    return "opening15-discretion-v1"


def arm_identity(
    packet: Packet,
    record: dict[str, Any],
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    hygiene_settings = eligibility.get("hygiene_settings")
    hygiene = {
        "present": eligibility.get("universe") == UNIVERSE_SHORTLIST,
        "settings_hash": digest(hygiene_settings) if hygiene_settings else None,
    }
    config = packet.config
    return {
        "experiment_id": infer_experiment_id(record, eligibility),
        "requested_model": record.get("requested_model") or config.model,
        "recommend_backend": record.get("recommend_backend") or config.recommend_backend,
        "prompt_version": infer_prompt_version(record, eligibility),
        "universe": eligibility["universe"],
        "eligibility_hash": eligibility["manifest_hash"],
        "hygiene": hygiene,
        "coverage_hash": record.get("context_hash"),
        "memory_hash": record.get("memory_hash"),
        "cost_config": {
            "commission_per_contract_side": config.commission_per_contract_side,
            "slippage_per_share": config.slippage_per_share,
            "api_input_usd_per_million": config.api_input_usd_per_million,
            "api_output_usd_per_million": config.api_output_usd_per_million,
        },
    }
