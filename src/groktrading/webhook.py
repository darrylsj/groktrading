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
from groktrading.sit_match import (
    REASON_OCC_EXECUTED_AT_DEBOUNCE,
    SIT_MATCH_EVENT,
    extract_occ,
    prepare_sit_match_outbound,
    sit_match_print_key,
)
from groktrading.timeutil import UTC, as_utc, quote_age_seconds

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
    print_age_sec: float | None = None
    emitted_at: str | None = None
    hop: dict[str, Any] | None = None


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
    _sit_print_keys: set[str] = field(default_factory=set)

    def send(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        event_type: str = "facts",
    ) -> WebhookSendResult:
        now = as_utc(self.clock.now())
        outbound = payload
        hop: dict[str, Any] | None = None
        print_age_sec: float | None = None
        emitted_at: str | None = None
        if event_type == SIT_MATCH_EVENT:
            first = prepare_sit_match_outbound(payload, now, enqueued_at=now)
            if not first.allow:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason=first.reason,
                    print_age_sec=first.print_age_sec,
                    hop=first.log_fields(),
                )
            if first.print_key is not None and first.print_key in self._sit_print_keys:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason=REASON_OCC_EXECUTED_AT_DEBOUNCE,
                    print_age_sec=first.print_age_sec,
                    hop=first.log_fields(),
                )
            # Re-check immediately before HTTP. A queued/replayed row that
            # was fresh at detect can be minutes old at POST.
            post_now = as_utc(self.clock.now())
            second = prepare_sit_match_outbound(
                first.payload or payload,
                post_now,
                detected_at=payload.get("detected_at"),
                enqueued_at=now,
                stale_at_post=True,
            )
            if not second.allow:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason=second.reason,
                    print_age_sec=second.print_age_sec,
                    hop=second.log_fields(),
                )
            if second.print_key is not None and second.print_key in self._sit_print_keys:
                return WebhookSendResult(
                    sent=False,
                    status_code=None,
                    idempotency_key=idempotency_key,
                    skipped_reason=REASON_OCC_EXECUTED_AT_DEBOUNCE,
                    print_age_sec=second.print_age_sec,
                    hop=second.log_fields(),
                )
            outbound = second.payload or payload
            print_age_sec = second.print_age_sec
            emitted_at = second.emitted_at
            hop = dict(outbound.get("hop") or {})
        if self.store is not None:
            decision = self.store.claim_outbox(
                idempotency_key,
                outbound,
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
        body = canonical_json(outbound)
        signature = sign_body(self.secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-GrokTrading-Signature": signature,
            "X-GrokTrading-Idempotency-Key": idempotency_key,
            "X-GrokTrading-Event-Type": event_type,
            "X-GrokTrading-Timestamp": now.isoformat(),
        }
        post_started = as_utc(self.clock.now())
        status, _text = self.http.post_bytes(url, body, headers)
        post_ended = as_utc(self.clock.now())
        if hop is not None:
            hop = dict(hop)
            hop["post_started_at"] = post_started.isoformat().replace("+00:00", "Z")
            hop["post_ended_at"] = post_ended.isoformat().replace("+00:00", "Z")
            hop["post_ms"] = quote_age_seconds(post_started, post_ended) * 1000.0
        if self.store is None:
            self._sent_keys.add(idempotency_key)
            self._last_sent[event_type] = now
        if event_type == SIT_MATCH_EVENT and isinstance(outbound, dict):
            print_key = sit_match_print_key(
                extract_occ(outbound),
                str(outbound.get("executed_at") or "") or None,
            )
            if print_key:
                self._sit_print_keys.add(print_key)
        return WebhookSendResult(
            sent=True,
            status_code=status,
            idempotency_key=idempotency_key,
            signature_hex=signature,
            redacted_body=redact_mapping(outbound),
            print_age_sec=print_age_sec,
            emitted_at=emitted_at,
            hop=hop,
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
        if event_type == SIT_MATCH_EVENT:
            prepared = prepare_sit_match_outbound(payload, as_utc(now))
            if not prepared.allow:
                return False
        return self.store.claim_inbox(
            idempotency_key, payload, event_type, now, clock_state=clock_state
        ).accept
