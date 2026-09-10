from __future__ import annotations

import json
from datetime import datetime, timedelta

from groktrading.idempotency import DurableIdempotency
from groktrading.models import AssembledFacts, Candidate
from groktrading.sit_match import (
    DEFAULT_SIT_MATCH_MAX_AGE_SEC,
    REASON_INVALID_MAX_AGE,
    REASON_MISSING,
    REASON_STALE,
    REASON_UNPARSEABLE,
    attach_executed_at,
    evaluate_sit_match_freshness,
    evaluate_sit_match_payload,
    executed_at_iso,
    parse_executed_at,
    sit_match_max_age_sec,
)
from groktrading.timeutil import UTC
from groktrading.webhook import SignedWebhookSender, WebhookInbox, canonical_json
from helpers import morning_pt, passing_candidate

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class CaptureHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def post_bytes(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
        self.calls.append((url, body, headers))
        return 200, "ok"


def test_parse_executed_at_iso_z() -> None:
    parsed = parse_executed_at("2026-09-09T16:29:30Z")
    assert parsed == datetime(2026, 9, 9, 16, 29, 30, tzinfo=UTC)


def test_parse_executed_at_offset() -> None:
    parsed = parse_executed_at("2026-09-09T09:29:30-07:00")
    assert parsed == datetime(2026, 9, 9, 16, 29, 30, tzinfo=UTC)


def test_parse_executed_at_rejects_naive_and_junk() -> None:
    assert parse_executed_at("2026-09-09T16:29:30") is None
    assert parse_executed_at("not-a-timestamp") is None
    assert parse_executed_at("") is None
    assert parse_executed_at(None) is None
    assert parse_executed_at(datetime(2026, 9, 9, 16, 29, 30)) is None
    assert parse_executed_at(1725890000) is None


def test_accept_fresh_print() -> None:
    executed = NOW - timedelta(seconds=12)
    decision = evaluate_sit_match_freshness(executed.isoformat().replace("+00:00", "Z"), NOW)
    assert decision.allow is True
    assert decision.reason is None
    assert decision.age_seconds == 12
    assert decision.max_age_sec == DEFAULT_SIT_MATCH_MAX_AGE_SEC
    assert decision.executed_at_iso == executed_at_iso(executed)


def test_accept_age_equal_to_max() -> None:
    executed = NOW - timedelta(seconds=60)
    decision = evaluate_sit_match_freshness(executed, NOW)
    assert decision.allow is True
    assert decision.age_seconds == 60


def test_reject_stale_print() -> None:
    # Hours-old UW row (e.g. NVDA put 1.07 after Tradier ask walked to 2.90).
    executed = NOW - timedelta(hours=3)
    decision = evaluate_sit_match_freshness("2026-09-09T13:30:00Z", NOW)
    assert decision.allow is False
    assert decision.reason == REASON_STALE
    assert decision.age_seconds == (NOW - executed).total_seconds()


def test_reject_missing_executed_at() -> None:
    for raw in (None, "", "   "):
        decision = evaluate_sit_match_freshness(raw, NOW)
        assert decision.allow is False
        assert decision.reason == REASON_MISSING


def test_reject_unparseable_executed_at() -> None:
    decision = evaluate_sit_match_freshness("yesterday-afternoon", NOW)
    assert decision.allow is False
    assert decision.reason == REASON_UNPARSEABLE


def test_nested_candidate_executed_at_and_payload_attach() -> None:
    executed = "2026-09-09T16:29:45Z"
    payload = {"event": "sit_match", "occ": "NVDA260918P00170000", "candidate": {}}
    missing = evaluate_sit_match_payload(payload, NOW)
    assert missing.allow is False
    assert missing.reason == REASON_MISSING

    payload["candidate"] = {"executed_at": executed}
    fresh = evaluate_sit_match_payload(payload, NOW)
    assert fresh.allow is True
    attached = attach_executed_at(payload, fresh)
    assert attached["executed_at"] == executed
    assert attached["candidate"]["executed_at"] == executed


def test_env_max_age_override() -> None:
    assert sit_match_max_age_sec({}) == 60.0
    assert sit_match_max_age_sec({"SIT_MATCH_MAX_AGE_SEC": "15"}) == 15.0
    executed = NOW - timedelta(seconds=20)
    tight = evaluate_sit_match_freshness(executed, NOW, env={"SIT_MATCH_MAX_AGE_SEC": "15"})
    assert tight.allow is False
    assert tight.reason == REASON_STALE
    wide = evaluate_sit_match_freshness(executed, NOW, env={"SIT_MATCH_MAX_AGE_SEC": "30"})
    assert wide.allow is True


def test_non_finite_max_age_fail_closed_env_and_arg() -> None:
    assert sit_match_max_age_sec({"SIT_MATCH_MAX_AGE_SEC": "inf"}) is None
    assert sit_match_max_age_sec({"SIT_MATCH_MAX_AGE_SEC": "NaN"}) is None
    assert sit_match_max_age_sec({"SIT_MATCH_MAX_AGE_SEC": "-1"}) is None
    old = NOW - timedelta(days=30)
    for limit in (float("inf"), float("nan"), float("-inf")):
        decision = evaluate_sit_match_freshness(old, NOW, max_age_sec=limit)
        assert decision.allow is False
        assert decision.reason == REASON_INVALID_MAX_AGE
    env_inf = evaluate_sit_match_freshness(
        old, NOW, env={"SIT_MATCH_MAX_AGE_SEC": "inf"}
    )
    assert env_inf.allow is False
    assert env_inf.reason == REASON_INVALID_MAX_AGE


def test_created_at_is_not_execution_clock() -> None:
    payload = {
        "event": "sit_match",
        "occ": "NVDA260918P00170000",
        "created_at": "2026-09-09T16:29:50Z",
        "timestamp": "2026-09-09T16:29:50Z",
    }
    decision = evaluate_sit_match_payload(payload, NOW)
    assert decision.allow is False
    assert decision.reason == REASON_MISSING


def test_candidate_and_facts_keep_executed_at() -> None:
    executed = NOW - timedelta(seconds=5)
    candidate = passing_candidate(executed_at=executed)
    assert isinstance(candidate, Candidate)
    assert candidate.executed_at == executed
    facts = AssembledFacts(
        signal_id="sig-1",
        underlying="NVDA",
        option_symbol="NVDA260918P00170000",
        ask="2.90",
        bid="2.85",
        sit_confirmations=2,
        as_of=NOW,
        executed_at=executed,
    )
    assert facts.executed_at == executed


def test_sender_includes_executed_at_and_skips_stale() -> None:
    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=FrozenClock(NOW),
    )
    fresh = sender.send(
        "https://example.invalid/hook",
        {"event": "sit_match", "occ": "NVDA260918P00170000", "executed_at": "2026-09-09T16:29:40Z"},
        idempotency_key="fresh-1",
        event_type="sit_match",
    )
    assert fresh.sent is True
    body = json.loads(http.calls[0][1])
    assert body["executed_at"] == "2026-09-09T16:29:40Z"
    assert canonical_json(body) == http.calls[0][1]

    stale = sender.send(
        "https://example.invalid/hook",
        {"event": "sit_match", "occ": "NVDA260918P00170000", "executed_at": "2026-09-09T14:00:00Z"},
        idempotency_key="stale-1",
        event_type="sit_match",
    )
    assert stale.sent is False
    assert stale.skipped_reason == REASON_STALE
    assert len(http.calls) == 1

    missing = sender.send(
        "https://example.invalid/hook",
        {"event": "sit_match", "occ": "NVDA260918P00170000"},
        idempotency_key="missing-1",
        event_type="sit_match",
    )
    assert missing.sent is False
    assert missing.skipped_reason == REASON_MISSING
    assert len(http.calls) == 1


def test_inbox_rejects_stale_and_missing_sit_match() -> None:
    store = DurableIdempotency(":memory:")
    inbox = WebhookInbox(store)
    now = morning_pt()
    assert (
        inbox.claim(
            "k-missing",
            {"event": "sit_match"},
            "sit_match",
            now,
            clock_state="open",
        )
        is False
    )
    assert (
        inbox.claim(
            "k-stale",
            {"event": "sit_match", "executed_at": (now - timedelta(seconds=61)).isoformat()},
            "sit_match",
            now,
            clock_state="open",
        )
        is False
    )
    assert (
        inbox.claim(
            "k-fresh",
            {
                "event": "sit_match",
                "executed_at": (now - timedelta(seconds=5)).astimezone(UTC).isoformat(),
            },
            "sit_match",
            now,
            clock_state="open",
        )
        is True
    )
