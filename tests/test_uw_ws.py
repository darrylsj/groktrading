from __future__ import annotations

from groktrading.feeds.uw_ws import (
    REASON_INVALID,
    REASON_UNSET,
    probe_document,
    probe_uw_ws,
    public_probe_url,
)


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
    assert probe.public_url == "wss://api.unusualwhales.com/socket"
    assert "super-secret" not in probe.public_url
    assert "token=" not in (probe.public_url or "")
    assert "channels" in probe.channels_docs
    assert "websocket.md" in probe.skill_docs


def test_public_url_drops_access_token_query_and_userinfo() -> None:
    query = probe_uw_ws(
        {
            "UW_WS_URL": (
                "wss://api.unusualwhales.com/socket?access_token=synth-access-token-c4"
            )
        }
    )
    assert query.ok is True
    assert query.public_url == "wss://api.unusualwhales.com/socket"
    assert "synth-access-token-c4" not in (query.public_url or "")
    assert "access_token" not in (query.public_url or "")

    userinfo = probe_uw_ws(
        {
            "UW_WS_URL": (
                "wss://user:synth-access-token-c4@api.unusualwhales.com/socket#frag"
            )
        }
    )
    assert userinfo.ok is True
    assert userinfo.public_url == "wss://api.unusualwhales.com/socket"
    assert "synth-access-token-c4" not in (userinfo.public_url or "")
    assert "user:" not in (userinfo.public_url or "")
    assert "frag" not in (userinfo.public_url or "")
    assert public_probe_url("https://api.unusualwhales.com/socket") is None
