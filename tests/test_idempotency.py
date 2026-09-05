from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from groktrading.idempotency import DurableIdempotency
from groktrading.timeutil import PT
from groktrading.webhook import SignedWebhookSender, WebhookInbox


class CaptureHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def post_bytes(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
        self.calls.append((url, body, headers))
        return 200, "ok"


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


def test_durable_key_replay_and_file_restart(tmp_path: Path) -> None:
    path = tmp_path / "idem.sqlite"
    now = datetime(2026, 9, 3, 7, 30, tzinfo=PT)
    first = DurableIdempotency(path)
    payload = {"event": "sit_match", "occ": "SPY260903C00600000"}
    accepted = first.claim_outbox("k1", payload, "sit_match", now, clock_state="open")
    assert accepted.accept is True
    replay = first.claim_outbox("k1", payload, "sit_match", now, clock_state="open")
    assert replay.accept is False
    assert replay.reason == "idempotent_replay"
    restarted = DurableIdempotency(path)
    again = restarted.claim_outbox("k1", payload, "sit_match", now, clock_state="open")
    assert again.accept is False
    inbox = restarted.claim_inbox("k1", payload, "sit_match", now, clock_state="open")
    assert inbox.accept is True


def test_weekend_same_digest_coalesces() -> None:
    store = DurableIdempotency(":memory:")
    now = datetime(2026, 9, 5, 10, 0, tzinfo=PT)  # Saturday
    payload = {"digest": "same", "kind": "sit_match"}
    first = store.claim_outbox("wk-1", payload, "sit_match", now)
    second = store.claim_outbox("wk-2", payload, "sit_match", now)
    assert first.accept is True
    assert second.accept is False
    assert second.reason == "weekend_or_ah_digest_coalesce"
    assert second.session_kind == "weekend"


def test_after_hours_same_digest_coalesces() -> None:
    store = DurableIdempotency(":memory:")
    now = datetime(2026, 9, 3, 16, 30, tzinfo=PT)
    payload = {"event": "cash_up", "flag": "entry_cutoff_only_no_flatten"}
    first = store.claim_inbox("ah-1", payload, "cash_up", now, clock_state="closed")
    second = store.claim_inbox("ah-2", payload, "cash_up", now, clock_state="closed")
    assert first.accept is True
    assert second.accept is False
    assert second.reason == "weekend_or_ah_digest_coalesce"


def test_rth_debounce_does_not_drop_distinct_digests_after_window() -> None:
    store = DurableIdempotency(":memory:")
    now = datetime(2026, 9, 3, 7, 30, tzinfo=PT)
    first = store.claim_outbox("rth-1", {"n": 1}, "sit_match", now, clock_state="open")
    cooled = store.claim_outbox("rth-2", {"n": 2}, "sit_match", now, clock_state="open")
    assert first.accept is True
    assert cooled.accept is False
    assert cooled.reason == "rth_debounce"
    later = store.claim_outbox(
        "rth-2",
        {"n": 2},
        "sit_match",
        now + timedelta(seconds=91),
        clock_state="open",
    )
    assert later.accept is True


def test_webhook_sender_uses_durable_outbox() -> None:
    store = DurableIdempotency(":memory:")
    http = CaptureHttp()
    clock = FrozenClock(datetime(2026, 9, 5, 11, 0, tzinfo=PT))
    sender = SignedWebhookSender(
        secret=b"test-secret-not-production",
        http=http,
        clock=clock,
        store=store,
    )
    payload = {"signal_id": "sig-weekend"}
    first = sender.send("https://example.invalid/hook", payload, idempotency_key="a")
    second = sender.send("https://example.invalid/hook", payload, idempotency_key="b")
    assert first.sent is True
    assert second.sent is False
    assert second.skipped_reason == "weekend_or_ah_digest_coalesce"
    assert len(http.calls) == 1
    inbox = WebhookInbox(store)
    assert inbox.claim("consumer-1", payload, "facts", clock.now()) is True
    assert inbox.claim("consumer-2", payload, "facts", clock.now()) is False
