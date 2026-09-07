"""CLI-only reference implementation for expanded evidence and daily learning.

Provider adapters supply Context JSON. No providers or broker order APIs are called here.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from groktrading.research.codex_cli import (
    CodexRun,
    exec_argv,
    inspect,
    loads_structured,
    parse_events,
    run_codex,
    subprocess_env,
)
from groktrading.research.opening15 import (
    Decision,
    Packet,
    canonical,
    digest,
    now_utc,
    strict_schema,
    window,
    write_once,
)

if TYPE_CHECKING:
    from groktrading.research.registry import PromptRegistry

Category = Literal[
    "world_news",
    "company_news",
    "macro",
    "calendar",
    "option_chain",
    "history",
    "portfolio",
    "depth",
]
CoverageStatus = Literal["available", "partial", "missing", "delayed"]
StageName = Literal[
    "memory",
    "capture",
    "context",
    "select",
    "monitor",
    "evaluate",
    "resolve",
    "day",
]
CATEGORIES = {
    "world_news",
    "company_news",
    "macro",
    "calendar",
    "option_chain",
    "history",
    "portfolio",
    "depth",
}
PROMPTS = Path(__file__).resolve().parent / "prompts"
T = TypeVar("T", bound=BaseModel)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(Strict):
    evidence_id: str = Field(min_length=1, max_length=100)
    category: Category
    symbols: list[str]
    source: str = Field(min_length=1)
    source_uri: str
    # as_of is when this information became true/known, NOT future event occurrence.
    as_of: AwareDatetime
    received_at: AwareDatetime
    summary: str = Field(min_length=1, max_length=1200)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def safe(self) -> Evidence:
        if self.as_of > self.received_at:
            raise ValueError("evidence timestamp after receipt")

        def scan(value: Any) -> None:
            if isinstance(value, dict):
                for key, val in value.items():
                    if re.search(
                        r"(token|secret|password|api_key|account_id|account_number)", key, re.I
                    ):
                        raise ValueError("secret/account identifier field in research evidence")
                    scan(val)
            elif isinstance(value, list):
                for item in value:
                    scan(item)

        scan(self.payload)
        return self


class Coverage(Strict):
    category: Category
    status: CoverageStatus
    detail: str = Field(min_length=1, max_length=600)


class Context(Strict):
    session: date
    frozen_at: AwareDatetime
    records: list[Evidence]
    coverage: list[Coverage]

    @model_validator(mode="after")
    def complete_manifest(self) -> Context:
        if (
            len(self.coverage) != len(CATEGORIES)
            or {x.category for x in self.coverage} != CATEGORIES
        ):
            raise ValueError("declare every context category exactly once, including missing data")
        ids = [r.evidence_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate context evidence ID")
        for record in self.records:
            if record.received_at > self.frozen_at:
                raise ValueError("post-freeze evidence")
        for entry in self.coverage:
            if entry.status in ("available", "partial") and not any(
                r.category == entry.category for r in self.records
            ):
                raise ValueError("coverage claims data absent from archive")
        return self

    def for_selection(self, packet: Packet, allow_degraded: bool = False) -> None:
        _, cutoff = window(packet.session)
        if self.session != packet.session or self.frozen_at > packet.knowledge_cutoff:
            raise ValueError("context does not match frozen opening packet")
        if any(r.as_of > cutoff or r.received_at > cutoff for r in self.records):
            raise ValueError("selection context must be observed by 09:45 ET")
        if not allow_degraded and any(
            c.status != "available" for c in self.coverage if c.category != "depth"
        ):
            raise ValueError(
                "expanded context incomplete; explicit degraded research mode required"
            )

    def index(self) -> dict[str, Any]:
        return {
            "coverage": [c.model_dump() for c in self.coverage],
            "records": [r.model_dump(mode="json", exclude={"payload"}) for r in self.records],
        }

    def retrieve(self, ids: list[str]) -> list[dict[str, Any]]:
        archive = {r.evidence_id: r for r in self.records}
        if len(ids) != len(set(ids)) or not set(ids) <= set(archive):
            raise ValueError("unknown/duplicate archived evidence ID")
        return [archive[i].model_dump(mode="json") for i in ids]


class RetrievalRequest(Strict):
    evidence_ids: list[str] = Field(max_length=40)
    rationale: str = Field(max_length=1200)


class Selection(Strict):
    decision: Decision
    context_citations: list[str]
    portfolio_assessment: str = Field(max_length=2000)
    memory_use: str = Field(max_length=1200)


class Review(Strict):
    option_symbol: str
    diagnosis: Literal[
        "direction",
        "timing",
        "volatility",
        "execution",
        "intervening_event",
        "data_quality",
        "mixed",
        "insufficient_evidence",
    ]
    explanation: str = Field(max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class Lesson(Strict):
    hypothesis: str = Field(min_length=1, max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    counterevidence: str = Field(min_length=1, max_length=400)
    applicable_context: str = Field(max_length=300)
    disconfirmation: str = Field(min_length=1, max_length=300)
    next_question: str = Field(max_length=300)


class StockReflection(Strict):
    symbol: str
    assessment: str = Field(min_length=1, max_length=600)


class Resolution(Strict):
    summary: str = Field(min_length=1, max_length=1200)
    reviews: list[Review] = Field(max_length=3)
    skipped_stocks: list[StockReflection] = Field(min_length=10, max_length=10)
    lessons: list[Lesson] = Field(max_length=3)
    proposed_prompt_change: str = Field(max_length=1500)
    forward_test: str = Field(max_length=1000)


class DailyRecord(Strict):
    session: date
    available_at: AwareDatetime
    source_hash: str
    decision_hash: str
    evaluation_hash: str
    status: Literal["resolved", "failed", "no_trade"]
    resolution: Resolution


class FailureRecord(Strict):
    """Typed ledger row for a stage that never produced a decision or PnL."""

    session: date
    available_at: AwareDatetime
    status: Literal["failed"] = "failed"
    stage: StageName
    error_type: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=800)
    source_hash: str
    attempt_dir: str = Field(max_length=400)
    decision_hash: str | None = None
    evaluation_hash: str | None = None

    @model_validator(mode="after")
    def no_invented_pnl(self) -> FailureRecord:
        dumped = self.model_dump()
        forbidden = {"pnl", "net", "profit", "loss", "fill", "fills"}
        if any(key.lower() in forbidden for key in dumped):
            raise ValueError("failure records must not invent PnL")
        if self.stage in {"select", "capture", "context", "memory"} and self.decision_hash:
            raise ValueError("pre-decision failure cannot attach a decision hash")
        return self


def write_failure(directory: Path, record: FailureRecord) -> Path:
    path = directory / "failure-record.json"
    write_once(path, record.model_dump(mode="json"))
    return path


def failure_from_exception(
    *,
    session: date,
    stage: StageName,
    exc: Exception,
    directory: Path,
    source: dict[str, Any] | None = None,
) -> FailureRecord:
    return FailureRecord(
        session=session,
        available_at=now_utc(),
        stage=stage,
        error_type=type(exc).__name__,
        detail=str(exc) if type(exc) is ValueError else type(exc).__name__,
        source_hash=digest(source or {"stage": stage, "error_type": type(exc).__name__}),
        attempt_dir=str(directory),
    )


class Memory(Strict):
    target_session: date
    built_at: AwareDatetime
    days: list[DailyRecord] = Field(max_length=5)
    failures: list[FailureRecord] = Field(default_factory=list, max_length=5)
    omitted_sessions: list[date]

    @model_validator(mode="after")
    def no_future(self) -> Memory:
        start, _ = window(self.target_session)
        sessions = [d.session for d in self.days]
        if len(sessions) != len(set(sessions)):
            raise ValueError("duplicate day in memory")
        if self.built_at >= start:
            raise ValueError("memory must be locked before target session open")
        if any(
            d.session >= self.target_session or d.available_at > self.built_at for d in self.days
        ):
            raise ValueError("same-day/future or unavailable memory")
        if any(
            item.session >= self.target_session or item.available_at > self.built_at
            for item in self.failures
        ):
            raise ValueError("same-day/future or unavailable memory")
        return self

    def brief(self) -> dict[str, Any]:
        # Small deterministic projection; detailed resolver records stay in the archive.
        result = {
            "target_session": str(self.target_session),
            "built_at": self.built_at.isoformat(),
            "days": [
                {
                    "session": str(d.session),
                    "status": d.status,
                    "source_hash": d.source_hash,
                    "summary": d.resolution.summary,
                    "lessons": [
                        {
                            "hypothesis": x.hypothesis,
                            "status": "tentative",
                            "disconfirmation": x.disconfirmation,
                            "counterevidence": x.counterevidence,
                            "evidence_ids": x.evidence_ids,
                        }
                        for x in d.resolution.lessons
                    ],
                }
                for d in self.days
            ],
            "failures": [
                {
                    "session": str(item.session),
                    "status": item.status,
                    "stage": item.stage,
                    "error_type": item.error_type,
                    "detail": item.detail,
                    "source_hash": item.source_hash,
                }
                for item in self.failures
            ],
            "omitted_sessions": [str(d) for d in self.omitted_sessions],
        }
        if len(canonical(result).encode()) > 14000:
            raise ValueError("memory brief budget exceeded; reduce whole days, never silently trim")
        return result


def load_session_record(path: Path) -> DailyRecord | FailureRecord:
    data = json.loads(path.read_text())
    if "stage" in data and "resolution" not in data:
        return FailureRecord.model_validate(data)
    return DailyRecord.model_validate(data)


def active_selector_prompt(
    registry: PromptRegistry | None,
    *,
    session: date | None = None,
) -> tuple[str, str]:
    """Return (prompt filename, version id). Default remains the shipped selector.

    When a registry is supplied, hash, permitted status, and pre-session freeze are
    enforced. Mismatches raise; there is no fallback to a rejected version.
    """
    if registry is None or not registry.active_version_id:
        return "selector_v2.md", "selector_v2"
    from groktrading.research.registry import require_usable_for_inference

    version = registry.get(registry.active_version_id)
    require_usable_for_inference(version, session=session)
    return version.prompt_name, version.version_id


def build_memory(
    days: list[DailyRecord],
    target: date,
    built_at: datetime,
    failures: list[FailureRecord] | None = None,
) -> Memory:
    if len({d.session for d in days}) != len(days):
        raise ValueError("multiple resolutions for one session; explicitly reconcile versions")
    eligible = sorted(
        [d for d in days if d.session < target and d.available_at <= built_at],
        key=lambda d: d.session,
        reverse=True,
    )
    kept = eligible[:5]
    failure_rows = [
        item
        for item in (failures or [])
        if item.session < target and item.available_at <= built_at
    ]
    failure_rows = sorted(failure_rows, key=lambda item: item.session, reverse=True)[:5]
    while True:
        memory = Memory(
            target_session=target,
            built_at=built_at,
            days=kept,
            failures=failure_rows,
            omitted_sessions=[d.session for d in days if d not in kept],
        )
        try:
            memory.brief()
            return memory
        except ValueError:
            if not kept:
                raise
            kept = kept[:-1]


def cli_json(
    prompt_name: str,
    payload: dict[str, Any],
    schema: type[T],
    directory: Path,
    model: str,
    effort: str,
    budget: int,
    runner: CodexRun | None = None,
) -> T:
    """One archived CLI attempt. No API fallback, automatic retries or broker credentials."""
    runner = runner or run_codex
    info = inspect(runner)
    directory = directory.resolve()
    work = directory / "work"
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    prompt = (PROMPTS / prompt_name).read_text()
    message = prompt + "\nINPUT_JSON:\n" + canonical(payload)
    if len(message.encode()) > budget:
        raise ValueError("model context byte budget exceeded")
    schema_path, output = directory / "schema.json", directory / "last-message.json"
    argv = exec_argv(
        model=model,
        reasoning_effort=effort,
        schema_path=schema_path,
        message_path=output,
        work_dir=work,
    )
    # Honor installed rules. The model is instructed to use only supplied evidence.
    argv = [x for x in argv if x != "--ignore-rules"]
    write_once(
        directory / "request.json",
        {
            "prompt": prompt,
            "payload": payload,
            "input_hash": digest(payload),
            "prompt_hash": digest(prompt),
            "requested_model": model,
            "backend": "codex_cli",
            "cli": info,
            "started_at": now_utc().isoformat(),
            "argv": argv,
        },
    )
    write_once(schema_path, strict_schema(schema.model_json_schema()))
    completed = runner(argv, cwd=work, input_text=message, timeout=600, env=subprocess_env())
    events, metadata = parse_events(completed.stdout or "")
    write_once(
        directory / "response.json",
        {
            "received_at": now_utc().isoformat(),
            "returncode": completed.returncode,
            "events": events,
            "metadata": metadata,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode or not output.is_file():
        raise ValueError("CLI stage failed; preserve attempt, no retry")
    # Any observed shell/web/MCP call invalidates a frozen experiment.
    forbidden = {"command_execution", "mcp_tool_call", "web_search", "file_change"}
    if any(e.get("item", {}).get("type") in forbidden for e in events):
        raise ValueError("tool use invalidated frozen decision")
    return schema.model_validate(loads_structured(output.read_text()))


def select(
    packet: Packet,
    context: Context,
    memory: Memory,
    directory: Path,
    allow_degraded: bool = False,
    runner: CodexRun | None = None,
    registry: PromptRegistry | None = None,
) -> dict[str, Any]:
    if packet.synthetic or packet.config.recommend_backend != "codex_cli":
        raise ValueError("prospective Codex CLI packet required")
    if not packet.knowledge_cutoff <= now_utc() <= packet.knowledge_cutoff + timedelta(minutes=3):
        raise ValueError("stale opening packet")
    context.for_selection(packet, allow_degraded)
    if memory.target_session != packet.session:
        raise ValueError("wrong memory session")
    selector_prompt, prompt_version = active_selector_prompt(registry, session=packet.session)
    write_once(
        directory / "cycle-input.json",
        {
            "packet_hash": digest(packet.model_dump(mode="json")),
            "context": context.model_dump(mode="json"),
            "memory": memory.model_dump(mode="json"),
            "degraded": allow_degraded,
        },
    )
    write_once(directory / "packet.json", packet.model_dump(mode="json"))
    cfg = packet.config
    payload: dict[str, Any] = {
        "opening_packet": packet.compact(),
        "context_index": context.index(),
        "memory": memory.brief(),
        "retrieved": [],
    }
    deadline = window(packet.session)[1] + timedelta(minutes=10)
    retrieved: set[str] = set()
    for i in range(2):
        request = cli_json(
            "retrieval_v1.md",
            payload,
            RetrievalRequest,
            directory / f"retrieval-{i}",
            cfg.model,
            cfg.reasoning_effort,
            cfg.max_input_bytes,
            runner,
        )
        if now_utc() > deadline:
            raise ValueError("overall selection deadline exceeded")
        context.retrieve(request.evidence_ids)
        new = set(request.evidence_ids) - retrieved
        if not new:
            break
        retrieved |= new
        payload["retrieved"] = context.retrieve(sorted(retrieved))
    selection = cli_json(
        selector_prompt,
        payload,
        Selection,
        directory / "selection",
        cfg.model,
        cfg.reasoning_effort,
        cfg.max_input_bytes,
        runner,
    )
    if now_utc() > deadline:
        raise ValueError("overall selection deadline exceeded")
    selection.decision.validate_evidence(packet)
    context.retrieve(selection.context_citations)
    record = {
        "packet_hash": digest(packet.model_dump(mode="json")),
        "context_hash": digest(context.model_dump(mode="json")),
        "memory_hash": digest(memory.model_dump(mode="json")),
        "received_at": now_utc().isoformat(),
        "synthetic": False,
        "requested_model": cfg.model,
        "recommend_backend": "codex_cli",
        "prompt_version": prompt_version,
        "decision": selection.decision.model_dump(mode="json"),
        "context_citations": selection.context_citations,
        "portfolio_assessment": selection.portfolio_assessment,
        "memory_use": selection.memory_use,
    }
    write_once(directory / "decision.json", record)
    return record


def resolve(
    packet: Packet,
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    outcome_context: Context,
    directory: Path,
    runner: CodexRun | None = None,
) -> DailyRecord:
    if packet.synthetic or packet.config.recommend_backend != "codex_cli":
        raise ValueError("prospective CLI experiment required")
    if evaluation.get("packet_hash") != decision.get("packet_hash") or decision.get(
        "packet_hash"
    ) != digest(packet.model_dump(mode="json")):
        raise ValueError("resolver artifact hash mismatch")
    if evaluation.get("decision_hash") != digest(decision):
        raise ValueError("resolver decision hash mismatch")
    if evaluation.get("synthetic") is not False or evaluation.get("paper_only") is not True:
        raise ValueError("explicit prospective paper evaluation required")
    at = now_utc()
    close = window(packet.session)[0] + timedelta(hours=6, minutes=30)
    if at < close or outcome_context.session != packet.session or outcome_context.frozen_at > at:
        raise ValueError("resolver requires completed session and available evidence")
    parsed = Decision.model_validate(decision["decision"])
    parsed.validate_evidence(packet)
    outcomes = {f"outcome:{r['option_symbol']}": r for r in evaluation["rows"]}
    payload = {
        "original_decision": decision,
        "evaluation": evaluation,
        "opening_packet": packet.compact(),
        "outcome_ids": outcomes,
        "outcome_context": outcome_context.model_dump(mode="json"),
    }
    result = cli_json(
        "resolver_v1.md",
        payload,
        Resolution,
        directory / "resolver",
        packet.config.model,
        packet.config.reasoning_effort,
        packet.config.max_input_bytes,
        runner,
    )
    ranked = {p.option_symbol for p in parsed.picks}
    if len(result.reviews) != len(ranked) or {r.option_symbol for r in result.reviews} != ranked:
        raise ValueError("resolver must review every ranked pick exactly once")
    if {r.symbol for r in result.skipped_stocks} != set(packet.config.symbols):
        raise ValueError("resolver must review opportunity costs for all stocks")
    ids = (
        set(outcomes)
        | {e.event_id for e in packet.events}
        | {e.evidence_id for e in outcome_context.records}
    )
    cited_items: list[Review | Lesson] = [*result.reviews, *result.lessons]
    for item in cited_items:
        if not set(item.evidence_ids) <= ids:
            raise ValueError("resolver invented supporting evidence")
    daily = DailyRecord(
        session=packet.session,
        available_at=now_utc(),
        source_hash=digest(payload),
        decision_hash=digest(decision),
        evaluation_hash=digest(evaluation),
        status="resolved" if any(p.action == "enter" for p in parsed.picks) else "no_trade",
        resolution=result,
    )
    write_once(directory / "daily-resolution.json", daily.model_dump(mode="json"))
    return daily
