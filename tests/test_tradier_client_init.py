"""TradierClient init log: host the client already uses, no secrets, no network."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytest

from groktrading.brokers.tradier import TradierBroker
from groktrading.feeds.tradier import (
    PRODUCTION_REST,
    SANDBOX_REST,
    TradierClient,
    format_tradier_init_log,
    rest_base,
    tradier_account_alias,
)
from groktrading.research.collectors import account_alias
from groktrading.timeutil import UTC


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


class FakeHttp:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        self.urls.append(url)
        return 200, {
            "quotes": {
                "quote": {
                    "symbol": "SPY260903C00600000",
                    "bid": "1.20",
                    "ask": "1.25",
                    "delayed": True,
                }
            }
        }

    def post_form(
        self, url: str, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        return 200, {}

    def delete(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        return 200, {}


def _client(
    *,
    env: str,
    account_id: str = "PAPERACCOUNT",
    token: str = "unused-test-token-not-in-log",
    account_id_source: str | None = None,
    http: FakeHttp | None = None,
) -> TradierClient:
    return TradierClient(
        http=http or FakeHttp(),
        clock=FrozenClock(),
        token=token,
        account_id=account_id,
        env=env,  # type: ignore[arg-type]
        account_id_source=account_id_source,
    )


def test_alias_matches_research_collector_and_hides_id() -> None:
    assert tradier_account_alias("PAPERACCOUNT") == account_alias("PAPERACCOUNT")
    assert "PAPERACCOUNT" not in tradier_account_alias("PAPERACCOUNT")


def test_sandbox_init_logs_client_base_not_env_override(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("TRADIER_API_BASE", "https://not-used.example/v1")
    monkeypatch.setenv("TRADIER_REST_BASE", "https://sandbox.tradier.com/v1")
    token = "unused-test-token-not-in-log"
    account = "PAPERACCOUNT"
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="sandbox", account_id=account, token=token)
    assert client.active_rest_base == SANDBOX_REST
    assert client.active_rest_base == rest_base("sandbox")
    assert client.account_id_source == "constructor"
    assert client.account_alias == tradier_account_alias(account)
    assert account not in caplog.text
    assert token not in caplog.text
    assert "not-used.example" not in caplog.text
    assert SANDBOX_REST in caplog.text
    assert "account_id_source=constructor" in caplog.text
    assert "tradier_client_init" in caplog.text


def test_production_init_ignores_sandbox_rest_env(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("TRADIER_REST_BASE", SANDBOX_REST)
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="production")
    assert client.active_rest_base == PRODUCTION_REST
    assert PRODUCTION_REST in caplog.text
    assert SANDBOX_REST not in caplog.text


def test_account_source_names_env_when_value_matches(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = "PAPERACCOUNT"
    monkeypatch.setenv("TRADIER_ACCOUNT_ID", account)
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="production", account_id=account)
    assert client.account_id_source == "TRADIER_ACCOUNT_ID"
    assert account not in caplog.text
    assert "account_id_source=TRADIER_ACCOUNT_ID" in caplog.text


def test_account_source_stays_constructor_when_env_differs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRADIER_ACCOUNT_ID", "OTHERACCOUNT")
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="sandbox", account_id="PAPERACCOUNT")
    assert client.account_id_source == "constructor"
    assert "OTHERACCOUNT" not in caplog.text
    assert "PAPERACCOUNT" not in caplog.text


def test_unsafe_explicit_source_is_not_logged(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_ACCOUNT_ID", raising=False)
    leaked = "Bearer secrettokenvalue"
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="sandbox", account_id_source=leaked)
    assert client.account_id_source == "constructor"
    assert "secrettokenvalue" not in caplog.text
    assert "Bearer" not in caplog.text


def test_quote_url_uses_logged_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADIER_ACCOUNT_ID", raising=False)
    http = FakeHttp()
    client = _client(env="sandbox", http=http)
    client.quote_option("SPY260903C00600000")
    assert http.urls
    assert http.urls[0].startswith(client.active_rest_base + "/")


def test_broker_wrap_does_not_log_twice(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADIER_ACCOUNT_ID", raising=False)
    with caplog.at_level(logging.INFO, logger="groktrading.feeds.tradier"):
        client = _client(env="production")
        TradierBroker(client=client)
    records = [record for record in caplog.records if "tradier_client_init" in record.getMessage()]
    assert len(records) == 1


def test_format_line_is_the_client_base() -> None:
    line = format_tradier_init_log(
        env="production",
        base_url=rest_base("production"),
        account_id_source="constructor",
        account_alias=tradier_account_alias("PAPERACCOUNT"),
    )
    assert line.startswith("tradier_client_init ")
    assert f"base_url={PRODUCTION_REST}" in line
    assert "PAPERACCOUNT" not in line
