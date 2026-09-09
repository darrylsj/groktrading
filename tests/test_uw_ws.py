from __future__ import annotations

from groktrading.feeds.uw_ws import (
    REASON_INVALID,
    REASON_UNSET,
    probe_document,
    probe_uw_ws,
)
from groktrading.redaction import REDACTED


def test_unset_fail_closed() -> None:
    probe = probe_uw_ws({})
    assert probe.ok is False
    assert probe.configured is False
    assert probe.reason == REASON_UNSET
    assert probe.connected is False
    assert probe.live_socket is False
    assert probe.places_orders is False
    doc = probe_document(probe)
    assert doc["invents_protocol"] is False
    assert "subscribe" in doc["note"].lower() or "protocol" in doc["note"].lower()


def test_invalid_scheme_fail_closed() -> None:
    probe = probe_uw_ws({"UW_WS_URL": "https://api.unusualwhales.com/socket"})
    assert probe.ok is False
    assert probe.reason == REASON_INVALID
    assert probe.connected is False


def test_configured_does_not_connect_and_redacts_token() -> None:
    probe = probe_uw_ws({"UW_WS_URL": "wss://api.unusualwhales.com/socket?token=super-secret"})
    assert probe.ok is True
    assert probe.configured is True
    assert probe.connected is False
    assert probe.public_url is not None
    assert "super-secret" not in probe.public_url
    assert REDACTED in probe.public_url
    assert "channels" in probe.channels_docs
    assert "websocket.md" in probe.skill_docs
