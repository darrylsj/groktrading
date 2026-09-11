"""Local sit_match HTTP simulation. No secrets. No live Grok webhook.

Proves the signed POST path is milliseconds when ``executed_at`` is now,
and that a stale / lying-``print_age_sec`` payload is never POSTed.
Default listener is 127.0.0.1. This module does not read grok-webhook.env.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.request import Request, urlopen

from groktrading.sit_match import (
    SIT_MATCH_EVENT,
    executed_at_iso,
    prepare_sit_match_outbound,
)
from groktrading.timeutil import UTC, as_utc, quote_age_seconds
from groktrading.webhook import SignedWebhookSender


SIM_OCC = "NVDA260918P00170000"
SIM_SECRET = b"simulate-sit-match-not-production"


class _CapturePoster:
    """urllib POST for the local listener only."""

    def post_bytes(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=2.0) as resp:  # noqa: S310 — local 127.0.0.1 only
            raw = resp.read()
            return int(getattr(resp, "status", 200) or 200), raw.decode("utf-8", errors="replace")


@dataclass
class _Listener:
    received: list[tuple[dict[str, str], bytes]] = field(default_factory=list)

    def handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length)
                owner.received.append((dict(self.headers), body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, fmt: str, *args: object) -> None:
                return

        return Handler


@dataclass(frozen=True)
class SitMatchSimResult:
    sent: bool
    skipped_reason: str | None
    print_age_sec: float | None
    executed_at: str | None
    emitted_at: str | None
    post_ms: float | None
    detect_to_enqueue_ms: float | None
    enqueue_to_post_ms: float | None
    http_received: bool
    body: dict[str, Any] | None
    hop: dict[str, Any] | None
    note: str


def _fresh_payload(now: datetime, *, lie_print_age: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": SIT_MATCH_EVENT,
        "occ": SIM_OCC,
        "executed_at": executed_at_iso(now),
        "detected_at": executed_at_iso(now),
    }
    if lie_print_age is not None:
        payload["print_age_sec"] = lie_print_age
    return payload


def simulate_sit_match_http(
    *,
    now: datetime | None = None,
    stale_executed_at: bool = False,
    lie_print_age_sec: float | None = None,
    executed_at_age_sec: float = 0.0,
) -> SitMatchSimResult:
    """POST a sit_match to a local listener. ``executed_at`` defaults to now.

    ``stale_executed_at`` uses a 10-minute-old print (must not POST).
    ``lie_print_age_sec`` stamps a bogus fresh age on a stale print.
    """
    stamp = as_utc(now or datetime.now(tz=UTC))
    detect = stamp
    if stale_executed_at:
        executed = stamp - timedelta(seconds=600)
        age = 600.0
    else:
        executed = stamp - timedelta(seconds=executed_at_age_sec)
        age = float(executed_at_age_sec)
    payload: dict[str, Any] = {
        "event": SIT_MATCH_EVENT,
        "occ": SIM_OCC,
        "executed_at": executed_at_iso(executed),
        "detected_at": executed_at_iso(detect),
        "enqueued_at": executed_at_iso(stamp),
    }
    if lie_print_age_sec is not None:
        payload["print_age_sec"] = lie_print_age_sec

    listener = _Listener()
    server = ThreadingHTTPServer(("127.0.0.1", 0), listener.handler())
    thread = Thread(target=server.serve_forever, name="sit-match-sim", daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/sit_match"
    try:
        enqueue = as_utc(datetime.now(tz=UTC))
        sender = SignedWebhookSender(
            secret=SIM_SECRET,
            http=_CapturePoster(),
        )
        result = sender.send(
            url,
            payload,
            idempotency_key=f"sim-{executed_at_iso(executed)}",
            event_type=SIT_MATCH_EVENT,
        )
        post_end = as_utc(datetime.now(tz=UTC))
        body: dict[str, Any] | None = None
        if listener.received:
            body = json.loads(listener.received[0][1].decode("utf-8"))
        hop = dict(result.hop or {})
        post_ms = hop.get("post_ms")
        if not isinstance(post_ms, (int, float)):
            post_ms = None
        return SitMatchSimResult(
            sent=result.sent,
            skipped_reason=result.skipped_reason,
            print_age_sec=result.print_age_sec if result.print_age_sec is not None else age,
            executed_at=executed_at_iso(executed),
            emitted_at=result.emitted_at,
            post_ms=float(post_ms) if post_ms is not None else None,
            detect_to_enqueue_ms=quote_age_seconds(detect, enqueue) * 1000.0,
            enqueue_to_post_ms=quote_age_seconds(enqueue, post_end) * 1000.0,
            http_received=bool(listener.received),
            body=body,
            hop=hop or None,
            note=(
                "Local sit_match POST only. Does not read grok-webhook.env. "
                "HTTP path is expected to be milliseconds when executed_at=now. "
                "Consumer receive after a queued Grok Bot wake is a separate hop; "
                "I1 executed_at≤60s must still refuse a delayed wake."
            ),
        )
    finally:
        server.shutdown()
        server.server_close()


def result_document(result: SitMatchSimResult) -> dict[str, Any]:
    """Secret-free JSON for the CLI / journal. No prices."""
    return {
        "sent": result.sent,
        "skipped_reason": result.skipped_reason,
        "print_age_sec": result.print_age_sec,
        "executed_at": result.executed_at,
        "emitted_at": result.emitted_at,
        "post_ms": result.post_ms,
        "detect_to_enqueue_ms": result.detect_to_enqueue_ms,
        "enqueue_to_post_ms": result.enqueue_to_post_ms,
        "http_received": result.http_received,
        "hop": result.hop,
        "body_print_age_sec": None if result.body is None else result.body.get("print_age_sec"),
        "body_emitted_at": None if result.body is None else result.body.get("emitted_at"),
        "note": result.note,
    }


def gate_only_document(
    *,
    stale_executed_at: bool = False,
    lie_print_age_sec: float | None = 5.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """No HTTP. Shows prepare_sit_match_outbound drop of a lying stale print."""
    stamp = as_utc(now or datetime.now(tz=UTC))
    payload = _fresh_payload(stamp - timedelta(seconds=600) if stale_executed_at else stamp)
    if lie_print_age_sec is not None:
        payload["print_age_sec"] = lie_print_age_sec
        if stale_executed_at:
            payload["executed_at"] = executed_at_iso(stamp - timedelta(seconds=600))
    prepared = prepare_sit_match_outbound(payload, stamp)
    return prepared.log_fields()
