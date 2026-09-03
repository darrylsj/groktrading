from __future__ import annotations

from datetime import datetime, timedelta

from groktrading.redaction import REDACTED, redact_mapping
from groktrading.timeutil import UTC
from groktrading.webhook import SignedWebhookSender, canonical_json, sign_body


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


def test_hmac_and_idempotency_and_redaction() -> None:
    secret = b"test-secret-not-production"
    http = CaptureHttp()
    clock = FrozenClock(datetime(2026, 9, 3, 14, 0, tzinfo=UTC))
    sender = SignedWebhookSender(
        secret=secret, http=http, clock=clock, cooldown=timedelta(seconds=5)
    )
    payload = {"signal_id": "sig-1", "token": "should-not-log"}
    first = sender.send("https://example.invalid/hook", payload, idempotency_key="k1")
    assert first.sent is True
    assert first.status_code == 200
    body = http.calls[0][1]
    assert sign_body(secret, body) == http.calls[0][2]["X-GrokTrading-Signature"]
    assert http.calls[0][2]["X-GrokTrading-Idempotency-Key"] == "k1"
    assert first.redacted_body is not None
    assert first.redacted_body["token"] == REDACTED

    replay = sender.send("https://example.invalid/hook", payload, idempotency_key="k1")
    assert replay.sent is False
    assert replay.skipped_reason == "idempotent_replay"
    assert len(http.calls) == 1

    cooled = sender.send("https://example.invalid/hook", payload, idempotency_key="k2")
    assert cooled.skipped_reason == "cooldown"

    clock.now_value = clock.now_value + timedelta(seconds=6)
    second = sender.send(
        "https://example.invalid/hook",
        {"signal_id": "sig-2"},
        idempotency_key="k2",
    )
    assert second.sent is True
    assert canonical_json({"a": 1, "b": 2}) == b'{"a":1,"b":2}'
    assert redact_mapping({"authorization": "Bearer abc"})["authorization"] == REDACTED
