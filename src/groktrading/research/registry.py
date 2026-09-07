"""File-based prompt version registry. Promotion is recorded, never silent."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from groktrading.research.cycle import Strict
from groktrading.research.opening15 import digest, now_utc, window, write_once

PromptStatus = Literal["proposed", "shadow", "accepted", "rejected"]
INFERENCE_STATUSES = frozenset({"accepted", "shadow"})
PROMPTS = Path(__file__).resolve().parent / "prompts"


class PromptVersion(Strict):
    version_id: str = Field(min_length=1, max_length=80)
    prompt_name: str = Field(min_length=1, max_length=80)
    prompt_hash: str = Field(min_length=64, max_length=64)
    parent_version: str | None = None
    supporting_sessions: list[date] = Field(default_factory=list)
    hypothesis: str = Field(min_length=1, max_length=400)
    proposed_difference: str = Field(min_length=1, max_length=800)
    forward_test: str = Field(min_length=1, max_length=800)
    status: PromptStatus
    created_at: AwareDatetime
    frozen_at: AwareDatetime | None = None


class PromptRegistry(Strict):
    versions: list[PromptVersion]
    active_version_id: str | None = None

    def get(self, version_id: str) -> PromptVersion:
        matches = [item for item in self.versions if item.version_id == version_id]
        if len(matches) != 1:
            raise ValueError("prompt version missing or duplicated")
        return matches[0]


def prompt_hash(prompt_name: str) -> str:
    return digest((PROMPTS / prompt_name).read_text())


def require_usable_for_inference(version: PromptVersion, *, session: date | None = None) -> None:
    """Reject rejected/proposed versions, hash mismatches, and unfrozen or late freezes.

    No silent fallback to another version.
    """
    if version.status not in INFERENCE_STATUSES:
        raise ValueError(
            f"prompt version {version.version_id} status {version.status} is not permitted "
            "for inference (accepted or shadow required); no fallback to a rejected version"
        )
    actual = prompt_hash(version.prompt_name)
    if actual != version.prompt_hash:
        raise ValueError(
            f"prompt version {version.version_id} hash mismatch: recorded hash does not "
            "match the prompt file; no fallback"
        )
    if version.frozen_at is None:
        raise ValueError(
            f"prompt version {version.version_id} is not frozen before the session; "
            "freeze the active version before inference"
        )
    if session is not None:
        start, _ = window(session)
        if version.frozen_at >= start:
            raise ValueError(
                f"prompt version {version.version_id} frozen_at is not before session open"
            )


def seed_registry(built_at: datetime | None = None) -> PromptRegistry:
    at = built_at or now_utc()
    versions = [
        PromptVersion(
            version_id="selector_v2",
            prompt_name="selector_v2.md",
            prompt_hash=prompt_hash("selector_v2.md"),
            parent_version=None,
            supporting_sessions=[],
            hypothesis="Incumbent discretionary selector shipped with the research cycle",
            proposed_difference="Baseline selector_v2 prompt text",
            forward_test="Compare only on future sessions with equal evidence and compute",
            status="accepted",
            created_at=at,
            frozen_at=at,
        ),
        PromptVersion(
            version_id="retrieval_v1",
            prompt_name="retrieval_v1.md",
            prompt_hash=prompt_hash("retrieval_v1.md"),
            parent_version=None,
            supporting_sessions=[],
            hypothesis="Bounded archived-ID retrieval",
            proposed_difference="At most two requests of 40 IDs",
            forward_test="Do not promote retrieval changes from in-sample reruns",
            status="accepted",
            created_at=at,
            frozen_at=at,
        ),
        PromptVersion(
            version_id="resolver_v1",
            prompt_name="resolver_v1.md",
            prompt_hash=prompt_hash("resolver_v1.md"),
            parent_version=None,
            supporting_sessions=[],
            hypothesis="Post-session review without rewriting numerical PnL",
            proposed_difference="Resolver reviews every ranked pick and all ten stocks",
            forward_test="Lessons remain tentative until a recorded experiment review",
            status="accepted",
            created_at=at,
            frozen_at=at,
        ),
    ]
    return PromptRegistry(versions=versions, active_version_id="selector_v2")


def load_registry(path: Path) -> PromptRegistry:
    return PromptRegistry.model_validate_json(path.read_text())


def write_registry(path: Path, registry: PromptRegistry) -> None:
    write_once(path, registry.model_dump(mode="json"))


def propose(
    registry: PromptRegistry,
    *,
    version_id: str,
    prompt_name: str,
    parent_version: str,
    hypothesis: str,
    proposed_difference: str,
    forward_test: str,
    supporting_sessions: list[date] | None = None,
    built_at: datetime | None = None,
) -> PromptRegistry:
    if any(item.version_id == version_id for item in registry.versions):
        raise ValueError("prompt version_id already exists")
    registry.get(parent_version)
    version = PromptVersion(
        version_id=version_id,
        prompt_name=prompt_name,
        prompt_hash=prompt_hash(prompt_name),
        parent_version=parent_version,
        supporting_sessions=supporting_sessions or [],
        hypothesis=hypothesis,
        proposed_difference=proposed_difference,
        forward_test=forward_test,
        status="proposed",
        created_at=built_at or now_utc(),
        frozen_at=None,
    )
    return PromptRegistry(
        versions=[*registry.versions, version],
        active_version_id=registry.active_version_id,
    )


def set_status(
    registry: PromptRegistry, version_id: str, status: PromptStatus
) -> PromptRegistry:
    updated: list[PromptVersion] = []
    for item in registry.versions:
        if item.version_id == version_id:
            updated.append(item.model_copy(update={"status": status}))
        else:
            updated.append(item)
    if not any(item.version_id == version_id for item in registry.versions):
        raise ValueError("prompt version missing")
    return PromptRegistry(versions=updated, active_version_id=registry.active_version_id)


def freeze_active(registry: PromptRegistry, version_id: str, at: datetime) -> PromptRegistry:
    version = registry.get(version_id)
    if version.status not in {"accepted", "shadow"}:
        raise ValueError("only accepted or shadow versions can be frozen as active")
    frozen = [
        item.model_copy(update={"frozen_at": at}) if item.version_id == version_id else item
        for item in registry.versions
    ]
    return PromptRegistry(versions=frozen, active_version_id=version_id)
