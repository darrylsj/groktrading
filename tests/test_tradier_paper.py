"""Sandbox paper client stays dry-run and off the live host."""

from __future__ import annotations

import json

import pytest

from tools.tradier_paper.client import PAPER_API_BASE, PaperConfigError, TradierPaperClient
from tools.tradier_paper.occ import to_occ
from tools.tradier_paper.paper_lift import plan_one, run_plan

ENV = {
    "TRADIER_PAPER_ACCOUNT_ID": "YOUR_SANDBOX_ACCOUNT_ID",
    "TRADIER_PAPER_ACCESS_TOKEN": "unused-test-token",
    "TRADIER_PAPER_API_BASE": PAPER_API_BASE,
}


def test_dry_run_does_not_open_a_request() -> None:
    def opener(*_args, **_kwargs):
        raise AssertionError("dry-run must not call the network")

    client = TradierPaperClient(ENV, opener=opener)
    result = client.place_option(
        option_symbol="XLK261002C00200000",
        side="buy_to_open",
        price=1.25,
    )
    assert result["places_orders"] is False
    assert result["dry_run"] is True
    assert result["base"] == "https://sandbox.tradier.com/v1"
    assert "unused-test-token" not in json.dumps(result)


def test_live_host_and_live_account_are_refused() -> None:
    with pytest.raises(PaperConfigError, match="sandbox.tradier.com"):
        TradierPaperClient({**ENV, "TRADIER_PAPER_API_BASE": "https://api.tradier.com/v1"})
    with pytest.raises(PaperConfigError, match="TRADIER_LIVE_ACCOUNT_ID"):
        TradierPaperClient(
            {
                **ENV,
                "TRADIER_PAPER_ACCOUNT_ID": "SAME",
                "TRADIER_LIVE_ACCOUNT_ID": "SAME",
            }
        )


def test_submit_posts_only_when_asked() -> None:
    seen: list[object] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"order":{"id":1}}'

    def opener(request, timeout=30):
        seen.append((request.full_url, timeout, request.data))
        return _Resp()

    client = TradierPaperClient(ENV, opener=opener)
    placed = client.place_option(
        option_symbol="XLK261002C00200000",
        side="buy_to_open",
        price=2.0,
        submit=True,
    )
    assert placed["places_orders"] is True
    assert seen[0][0].startswith("https://sandbox.tradier.com/v1/accounts/")
    assert b"preview" not in seen[0][2]
    with pytest.raises(PaperConfigError, match="sell_to_open"):
        client.place_option(option_symbol="XLK261002C00200000", side="sell_to_open", price=1)
    with pytest.raises(PaperConfigError, match="one-lot"):
        client.place_option(
            option_symbol="XLK261002C00200000",
            side="buy_to_open",
            quantity=2,
            price=1,
            submit=True,
        )


def test_occ_and_plan_do_not_invent_legs() -> None:
    assert to_occ("XLK", "2026-10-02", "C", 200) == "XLK261002C00200000"
    near = plan_one(
        {"source": "trademachine", "ticker": "SMH", "status": "Near Active", "tier": "B"},
        allow_oai=False,
    )
    assert near["reason"] == "near_active_watch_only"
    assert near["places_orders"] is False
    missing = plan_one(
        {
            "source": "trademachine",
            "ticker": "XLK",
            "status": "Active",
            "tier": "A",
            "legs": [],
        },
        allow_oai=False,
    )
    assert missing["reason"].startswith("no resolvable OCC")
    spy = plan_one(
        {
            "source": "trademachine",
            "ticker": "SPY",
            "status": "Active",
            "tier": "A",
            "occ": "SPY260925P00500000",
        },
        allow_oai=False,
    )
    assert spy["reason"] == "refuse_long_put_on_broad_etf"
    oai = plan_one(
        {"source": "options_ai", "ticker": "AAPL", "status": "Available", "tier": "B"},
        allow_oai=False,
    )
    assert oai["reason"] == "options_ai_dom_until_confirmed"


def test_run_plan_stays_dry_without_submit() -> None:
    rank = {
        "top_n": [
            {
                "source": "trademachine",
                "ticker": "XLK",
                "status": "Active",
                "tier": "A",
                "score": 80,
                "strategy": "ETF 2-Days-Up Diagonal",
                "occ": "XLK261002C00200000",
            }
        ]
    }
    payload = run_plan(rank, ask_by_occ={"XLK261002C00200000": 1.5})
    assert payload["places_orders"] is False
    assert payload["submit"] is False
    assert payload["results"][0]["action"] == "dry_run"
    assert payload["api_base"] == "https://sandbox.tradier.com/v1"
