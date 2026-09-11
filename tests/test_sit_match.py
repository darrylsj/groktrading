from __future__ import annotations

import json
from datetime import datetime, timedelta

from groktrading.idempotency import DurableIdempotency
from groktrading.models import AssembledFacts, Candidate
from groktrading.sit_match import (
    DEFAULT_SIT_MATCH_MAX_AGE_SEC,
    REASON_INVALID_MAX_AGE,
    REASON_MIN_INTERVAL,
    REASON_MISSING,
    REASON_MUTED,
    REASON_OCC_DEBOUNCE,
    REASON_PRINT_AGE_CONTRADICTS,
    REASON_STALE,
    REASON_STALE_AT_POST,
    REASON_UNPARSEABLE,
    attach_executed_at,
    evaluate_sit_match_freshness,
    evaluate_sit_match_payload,
    executed_at_iso,
    parse_executed_at,
    prepare_sit_match_outbound,
    print_age_contradicts,
    sit_match_max_age_sec,
    sit_match_occ_key,
    sit_match_webhook_enabled,
)
from groktrading.sit_match_sim import result_document, simulate_sit_match_http
from groktrading.timeutil import UTC
from groktrading.webhook import SignedWebhookSender, WebhookInbox, canonical_json
from helpers import morning_pt, passing_candidate

NOW = datetime(2026, 9, 9, 16, 30, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class SequenceClock:
    """Return successive timestamps so POST-time recheck can go stale."""

    def __init__(self, times: list[datetime]) -> None:
        self._times = list(times)
        self._i = 0

    def now(self) -> datetime:
        if self._i >= len(self._times):
            return self._times[-1]
        value = self._times[self._i]
        self._i += 1
        return value


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


def test_print_age_sec_overwritten_from_executed_at() -> None:
    executed = NOW - timedelta(seconds=12)
    inbound = {
        "event": "sit_match",
        "occ": "NVDA260918P00170000",
        "executed_at": executed_at_iso(executed),
        "print_age_sec": 3.0,
        "created_at": executed_at_iso(NOW - timedelta(seconds=2)),
        "detected_at": executed_at_iso(NOW - timedelta(seconds=1)),
    }
    prepared = prepare_sit_match_outbound(inbound, NOW, enqueued_at=NOW)
    assert prepared.allow is True
    assert prepared.payload is not None
    assert prepared.print_age_sec == 12
    assert prepared.payload["print_age_sec"] == 12
    assert prepared.payload["emitted_at"] == executed_at_iso(NOW)
    assert prepared.payload["hop"]["executed_at_age_sec"] == 12
    assert prepared.payload["hop"]["print_age_sec"] == 12
    assert not print_age_contradicts(prepared.payload["print_age_sec"], 12)


def test_bogus_print_age_does_not_bypass_stale_executed_at() -> None:
    inbound = {
        "event": "sit_match",
        "occ": "NVDA260918P00170000",
        "executed_at": "2026-09-09T16:00:00Z",
        "print_age_sec": 5.0,
        "created_at": "2026-09-09T16:29:55Z",
        "timestamp": "2026-09-09T16:29:55Z",
    }
    prepared = prepare_sit_match_outbound(inbound, NOW)
    assert prepared.allow is False
    assert prepared.reason == REASON_PRINT_AGE_CONTRADICTS
    assert prepared.freshness.age_seconds == 1800
    assert prepared.payload is None

    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=FrozenClock(NOW),
    )
    result = sender.send(
        "https://example.invalid/hook",
        inbound,
        idempotency_key="lie-1",
        event_type="sit_match",
    )
    assert result.sent is False
    assert result.skipped_reason == REASON_PRINT_AGE_CONTRADICTS
    assert http.calls == []


def test_stale_at_post_skips_after_enqueue_clock_jump() -> None:
    executed = NOW - timedelta(seconds=10)
    inbound = {
        "event": "sit_match",
        "occ": "NVDA260918P00170000",
        "executed_at": executed_at_iso(executed),
        "print_age_sec": 10.0,
    }
    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=SequenceClock([NOW, NOW + timedelta(seconds=120)]),
    )
    result = sender.send(
        "https://example.invalid/hook",
        inbound,
        idempotency_key="queued-late-1",
        event_type="sit_match",
    )
    assert result.sent is False
    assert result.skipped_reason == REASON_STALE_AT_POST
    assert result.print_age_sec == 130
    assert http.calls == []


def test_occ_only_debounce_blocks_new_print_on_same_occ() -> None:
    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=FrozenClock(NOW),
        env={"SIT_MATCH_MIN_INTERVAL_SEC": "60"},
        mute_path="/nonexistent/sit_match_webhook_muted",
    )
    first = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": "2026-09-09T16:29:40Z",
        },
        idempotency_key="print-a",
        event_type="sit_match",
    )
    second = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": "2026-09-09T16:29:50Z",
        },
        idempotency_key="print-b",
        event_type="sit_match",
    )
    assert first.sent is True
    assert second.sent is False
    assert second.skipped_reason == REASON_OCC_DEBOUNCE
    assert len(http.calls) == 1
    assert sit_match_occ_key("nvda260918p00170000") == "NVDA260918P00170000"


def test_min_interval_caps_global_post_rate() -> None:
    http = CaptureHttp()
    clock = FrozenClock(NOW)
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=clock,
        env={"SIT_MATCH_MIN_INTERVAL_SEC": "60"},
        mute_path="/nonexistent/sit_match_webhook_muted",
    )
    first = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": "2026-09-09T16:29:40Z",
        },
        idempotency_key="nvda-1",
        event_type="sit_match",
    )
    other = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "AAPL260918C00200000",
            "executed_at": "2026-09-09T16:29:50Z",
        },
        idempotency_key="aapl-1",
        event_type="sit_match",
    )
    assert first.sent is True
    assert other.sent is False
    assert other.skipped_reason == REASON_MIN_INTERVAL
    clock.now_value = NOW + timedelta(seconds=61)
    later = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": executed_at_iso(NOW + timedelta(seconds=55)),
        },
        idempotency_key="nvda-2",
        event_type="sit_match",
    )
    assert later.sent is True
    assert len(http.calls) == 2


def test_sit_match_webhook_mute_env_and_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mute = tmp_path / "sit_match_webhook_muted"
    assert sit_match_webhook_enabled({"SIT_MATCH_WEBHOOK": "1"}, mute) is True
    assert sit_match_webhook_enabled({"SIT_MATCH_WEBHOOK": "0"}, mute) is False
    mute.write_text("", encoding="utf-8")
    assert sit_match_webhook_enabled({"SIT_MATCH_WEBHOOK": "1"}, mute) is False

    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=FrozenClock(NOW),
        env={"SIT_MATCH_WEBHOOK": "0"},
        mute_path=str(tmp_path / "absent"),
    )
    result = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": "2026-09-09T16:29:40Z",
        },
        idempotency_key="muted-1",
        event_type="sit_match",
    )
    assert result.sent is False
    assert result.skipped_reason == REASON_MUTED
    assert http.calls == []


def test_sender_stamps_truthful_print_age_and_emitted_at() -> None:
    http = CaptureHttp()
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=FrozenClock(NOW),
    )
    result = sender.send(
        "https://example.invalid/hook",
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": "2026-09-09T16:29:40Z",
            "print_age_sec": 1.0,
        },
        idempotency_key="fresh-stamp-1",
        event_type="sit_match",
    )
    assert result.sent is True
    body = json.loads(http.calls[0][1])
    assert body["executed_at"] == "2026-09-09T16:29:40Z"
    assert body["print_age_sec"] == 20
    assert body["emitted_at"] == executed_at_iso(NOW)
    assert result.print_age_sec == 20
    assert result.hop is not None
    assert result.hop["post_ms"] == 0.0


def test_inbox_rejects_lying_print_age_on_stale_print() -> None:
    store = DurableIdempotency(":memory:")
    inbox = WebhookInbox(store)
    now = morning_pt()
    assert (
        inbox.claim(
            "k-lie",
            {
                "event": "sit_match",
                "executed_at": (now - timedelta(seconds=900)).astimezone(UTC).isoformat(),
                "print_age_sec": 4,
            },
            "sit_match",
            now,
            clock_state="open",
        )
        is False
    )


def test_simulate_fresh_http_path_is_fast() -> None:
    result = simulate_sit_match_http(executed_at_age_sec=0.0)
    assert result.sent is True
    assert result.http_received is True
    assert result.body is not None
    assert result.body["occ"] == "NVDA260918P00170000"
    assert result.body["print_age_sec"] == result.print_age_sec
    assert result.post_ms is not None
    assert result.post_ms < 2000
    assert result.enqueue_to_post_ms is not None
    assert result.enqueue_to_post_ms < 2000
    doc = result_document(result)
    assert doc["http_received"] is True
    assert "grok-webhook.env" in doc["note"]


def test_simulate_stale_and_lie_never_post() -> None:
    stale = simulate_sit_match_http(stale_executed_at=True)
    assert stale.sent is False
    assert stale.http_received is False
    assert stale.skipped_reason in {REASON_STALE, REASON_PRINT_AGE_CONTRADICTS}
    lie = simulate_sit_match_http(stale_executed_at=True, lie_print_age_sec=5.0)
    assert lie.sent is False
    assert lie.http_received is False
    assert lie.skipped_reason == REASON_PRINT_AGE_CONTRADICTS


def test_host_contract_mute_skips_injected_post(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scripts_loader import ws_tape_sit_match

    mute = tmp_path / "sit_match_webhook_muted"
    mute.write_text("", encoding="utf-8")
    ws_tape_sit_match.HOST_MUTE_FILE = mute
    posted: list[object] = []
    result = ws_tape_sit_match.maybe_post_sit_match(
        {
            "event": "sit_match",
            "occ": "NVDA260918P00170000",
            "executed_at": executed_at_iso(NOW - timedelta(seconds=5)),
        },
        now=NOW,
        post=posted.append,
    )
    assert result.allow is False
    assert result.reason == REASON_MUTED
    assert posted == []


def test_simulate_script_lie_print_age_exits_zero() -> None:
    from scripts_loader import simulate_sit_match_webhook

    assert simulate_sit_match_webhook.main(["--lie-print-age"]) == 0
