"""Signed, idempotent webhook sender with cooldown and redaction.

Helsinki pushes assembled facts to Grok. No LLM polling. Secrets are never
written to logs or tape files.

In-memory debounce (~90s) is kept for unit tests and as a fallback. Durable
SQLite WAL idempotency (inbox + outbox) is the package replacement for the
Helsinki weekend same-digest spam. After-hours / weekend coalesces by digest.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from groktrading.idempotency import DurableIdempotency
from groktrading.redaction import redact_mapping
from groktrading.timeutil import UTC, as_utc

DEFAULT_COOLDOWN = timedelta(seconds=5)
HELSINKI_INMEMORY_DEBOUNCE = timedelta(seconds=90)


class HttpPoster(Protocol):
    def post_bytes(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, str]:
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def sign_body(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()


@dataclass
class WebhookSendResult:
    sent: bool
    status_code: int | None
    idempotency_key: str
    skipped_reason: str | None = None
    signature_hex: str | None = None
    redacted_body: dict[str, Any] | None = None
    session_kind: str | None = None


@dataclass
class SignedWebhookSender:
    secret: bytes
    http: HttpPoster
    clock: Clock = field(default_factory=UtcClock)
    cooldown: timedelta = DEFAULT_COOLDOWN
    store: DurableIdempotency | None = None
    clock_state: str | None = None
    _last_sent: dict[str, datetime] = field(default_factory=dict)
    _sent_keys: set[str] = field(default_factory=set)

    def send(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        event_type: str = "facts",
    ) -> WebhookSendResult:
        now = as_utc(self.clock.now())
        if self.store is not None:
            decision = self.store.claim_outbox(
                idempotency_key,
                payload,
                event_type,
                now,
                clock_state=self.clock_state,
            )
            if not decision.accept:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason=decision.reason,
                    session_kind=decision.session_kind,
                )
        else:
            if idempotency_key in self._sent_keys:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason="idempotent_replay",
                )
            last = self._last_sent.get(event_type)
            if last is not None and now - last < self.cooldown:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason="cooldown",
                )
        body = canonical_json(payload)
        signature = sign_body(self.secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-GrokTrading-Signature": signature,
            "X-GrokTrading-Idempotency-Key": idempotency_key,
            "X-GrokTrading-Event-Type": event_type,
            "X-GrokTrading-Timestamp": now.isoformat(),
        }
        status, _text = self.http.post_bytes(url, body, headers)
        if self.store is None:
            self._sent_keys.add(idempotency_key)
            self._last_sent[event_type] = now
        return WebhookSendResult(
            sent=True,
            status_code=status,
            idempotency_key=idempotency_key,
            signature_hex=signature,
            redacted_body=redact_mapping(payload),
        )


class WebhookInbox:
    """Grok-side consumer: durable claim before any LLM or gate work."""

    def __init__(self, store: DurableIdempotency) -> None:
        self.store = store

    def claim(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        event_type: str,
        now: datetime,
        clock_state: str | None = None,
    ) -> bool:
        return self.store.claim_inbox(
            idempotency_key, payload, event_type, now, clock_state=clock_state
        ).accept
