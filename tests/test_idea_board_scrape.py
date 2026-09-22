"""TradeMachine freshness, Options AI DOM-only, dual-source shadow pointer."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import tools.idea_board_scrape.get_ideas as get_ideas
from tools.idea_board_scrape.idea_card_map import board_to_idea_cards
from tools.idea_board_scrape.normalize_trademachine import normalize, rows_from_har
from tools.idea_board_scrape.paper_lift import PAPER_API_BASE, PaperLiftError, paper_one_lot_ready

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
FRESH = "2026-09-22T17:30:00.000Z"
STALE = "2026-09-20T17:30:00.000Z"
BOARD_URL = (
    "https://www.trademachine.com/wp-admin/admin-ajax.php?action=tm_get_today2_strategy_results"
)


def _wire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    board_dir = tmp_path / "evidence" / "idea_boards"
    board_dir.mkdir(parents=True)
    monkeypatch.setattr(get_ideas, "ROOT", tmp_path)
    monkeypatch.setattr(get_ideas, "BOARD_DIR", board_dir)
    monkeypatch.setattr(get_ideas, "LEDGER", board_dir / "idea_board_ledger.jsonl")
    monkeypatch.setattr(get_ideas, "SHADOW", tmp_path / "state" / "idea_board_latest.json")
    return board_dir


def _entry(
    *,
    body: object,
    started: str = FRESH,
    status: int = 200,
    method: str = "GET",
    url: str = BOARD_URL,
) -> dict:
    return {
        "startedDateTime": started,
        "request": {"method": method, "url": url, "headers": [], "cookies": []},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": "application/json"}],
            "cookies": [],
            "content": {"text": json.dumps(body)},
        },
    }


def _write_har(path: Path, entries: list[dict]) -> None:
    path.write_text(
        json.dumps({"log": {"entries": entries}}),
        encoding="utf-8",
    )


def _row(ticker: str, *, active: int = 0, share: str = "s_test") -> dict:
    return {
        "ticker": ticker,
        "templateType": "etf_2_days_up_diagonal",
        "isActive": active,
        "triggeredToday": False,
        "shareKey": share,
    }


def _leg_url(share: str, ticker: str) -> str:
    return (
        "https://www.trademachine.com/wp-admin/admin-ajax.php"
        f"?action=tm_get_strategy_result&share_key={share}&ticker={ticker}"
        "&attach_live_option_quotes=1"
    )


def _xlk_legs() -> dict:
    return {
        "portfolio": {
            "tradeList": [
                {
                    "description": "Open_TechnicalOpen:long",
                    "size": 1,
                    "price": 2.92,
                    "type": "Call",
                    "expiration": "Oct2`26",
                    "strike": 194,
                    "symbol": "XLK",
                },
                {
                    "description": "Open_TechnicalOpen:short",
                    "size": -1,
                    "price": 0.90,
                    "type": "Call",
                    "expiration": "Sep25`26",
                    "strike": 196,
                    "symbol": "XLK",
                },
                {
                    "description": "_ClosingMark:long",
                    "size": 1,
                    "price": 9.99,
                    "type": "Call",
                    "strike": 1,
                    "symbol": "XLK",
                },
            ]
        }
    }


def test_latest_200_wins_and_observation_time_is_source_time(tmp_path: Path) -> None:
    har = tmp_path / "trademachine_today_REDACTED.har"
    _write_har(
        har,
        [
            _entry(
                body=[_row("AAA"), _row("BBB"), _row("CCC")],
                started="2026-09-22T16:00:00.000Z",
            ),
            _entry(body=[_row("XLK", active=1, share="s_xlk")], started=FRESH),
            _entry(body=_xlk_legs(), url=_leg_url("s_xlk", "XLK"), started=FRESH),
        ],
    )
    extracted = rows_from_har(har, now=NOW)
    assert [row["ticker"] for row in extracted.rows] == ["XLK"]
    assert extracted.login_health == "AUTHENTICATED"
    board = get_ideas.build_board("trademachine", har, None, now=NOW, allow_stale=False)
    assert board["as_of_pt"] == "2026-09-22 10:30:00 PT"
    assert board["as_of_pt"] != datetime.now(get_ideas.PT).strftime("%Y-%m-%d %H:%M:%S PT")
    idea = board["ideas"][0]
    assert len(idea["legs"]) == 2
    assert idea["entry"]["mid"] is None
    assert idea["legs"][0]["display_price"] == 2.92
    assert idea["legs"][0]["expiry"] is None
    assert idea["legs"][0]["expiration_label"] == "Oct2`26"
    assert idea["legs"][1]["side"] == "SHORT"
    assert idea["legs"][1]["display_price"] == 0.90
    assert all(leg["display_price"] != 9.99 for leg in idea["legs"])
    cards = board_to_idea_cards(board)
    assert cards[0]["legs_missing"] is False
    assert cards[0]["occ_resolvable"] is False
    assert cards[0]["provenance"]["execution_realm"] == "shadow"
    assert cards[0]["provenance"]["live_order_gate"] is False
    assert cards[0]["strategy_template_id"] == "etf_2_days_up_diagonal"
    assert cards[0]["vendor_status"] == "Active"


def test_active_rows_sort_first_and_near_active_legs_stay_empty() -> None:
    board = normalize(
        [
            _row("SMH", active=0),
            _row("XLK", active=1, share="s_xlk"),
            _row("BAC", active=0),
        ],
        endpoint="GET test",
        observed_at=NOW,
        login_health="AUTHENTICATED",
        legs_by_key={"share:s_xlk": [{"side": "LONG", "right": "C", "strike": 194}]},
    )
    assert [idea["ticker"] for idea in board["ideas"]] == ["XLK", "SMH", "BAC"]
    near = board["ideas"][1]
    assert near["legs"] == []
    assert near["ui_fields"]["empty_legs_expected"] is True
    assert near["ui_fields"]["legs_expected"] is False
    assert board["ideas"][0]["ui_fields"]["legs_expected"] is True
    assert board["counts"]["near_active"] == 2


def test_negative_tm_host_method_action_status_and_401(tmp_path: Path) -> None:
    wrong_host = tmp_path / "trademachine_wrong.har"
    _write_har(
        wrong_host,
        [
            _entry(
                body=[_row("SPY")],
                url="https://evil.example/admin-ajax.php?action=tm_get_today2_strategy_results",
            )
        ],
    )
    with pytest.raises(SystemExit, match="www.trademachine.com"):
        rows_from_har(wrong_host, now=NOW)

    post = tmp_path / "trademachine_post.har"
    _write_har(post, [_entry(body=[_row("SPY")], method="POST")])
    with pytest.raises(SystemExit, match="GET 200"):
        rows_from_har(post, now=NOW)

    extra = tmp_path / "trademachine_extra.har"
    _write_har(
        extra,
        [
            _entry(
                body=[_row("SPY")],
                url=BOARD_URL + "_extra",
            )
        ],
    )
    with pytest.raises(SystemExit, match="exact|GET 200"):
        rows_from_har(extra, now=NOW)

    denied = tmp_path / "trademachine_denied.har"
    _write_har(denied, [_entry(body=[], status=401)])
    with pytest.raises(SystemExit, match="NOT_AUTHENTICATED"):
        rows_from_har(denied, now=NOW)

    stale = tmp_path / "trademachine_stale.har"
    _write_har(stale, [_entry(body=[_row("SPY")], started=STALE)])
    with pytest.raises(SystemExit, match="stale"):
        rows_from_har(stale, now=NOW)

    fixed = tmp_path / "trademachine_today_20260921_0910_pt_REDACTED.har"
    _write_har(fixed, [_entry(body=[_row("SPY")])])
    with pytest.raises(SystemExit, match="fixed default HAR"):
        rows_from_har(fixed, now=NOW)


def test_no_fixed_default_har_and_get_ideas_not_on_live_gate() -> None:
    text = (ROOT / "tools" / "idea_board_scrape" / "get_ideas.py").read_text(encoding="utf-8")
    assert "trademachine_today_20260921_0910" not in text
    gate = (ROOT / "tools" / "live_order_gate" / "gate.py").read_text(encoding="utf-8")
    assert "get_ideas" not in gate
    assert "idea_board_scrape" not in gate
    with pytest.raises(SystemExit, match="no fixed default HAR"):
        get_ideas.run_inputs(source="both", hars=[], boards=[], write_shadow=False, now=NOW)


def test_options_ai_har_heuristic_is_disabled(tmp_path: Path) -> None:
    chain = tmp_path / "options_ai_chain.har"
    _write_har(
        chain,
        [
            _entry(
                body={"ideas": [{"ticker": "AAPL", "strategy": "Call", "status": "Available"}]},
                url="https://api.options.ai/markets/tradier/expire-strikes?symbol=AAPL",
            ),
            _entry(
                body={"contracts": [{"symbol": "AAPL", "strike": 100}]},
                url="https://api.options.ai/markets/tradier/chain-details?symbol=AAPL",
            ),
            _entry(
                body={"quotes": [{"symbol": "AAPL"}]},
                url="https://api.options.ai/markets/v1/quotes/AAPL",
            ),
        ],
    )
    with pytest.raises(SystemExit, match="HAR→ideas publication is disabled"):
        get_ideas.refuse_options_ai_har(chain)
    with pytest.raises(SystemExit, match="quotes-only"):
        get_ideas.build_board("options_ai", chain, None, now=NOW, allow_stale=False)

    click = tmp_path / "options_ai_click.har"
    _write_har(
        click,
        [_entry(body={"ideas": [{"ticker": "AAPL"}]}, url="https://api.clickoptions.ai/v1/ideas")],
    )
    with pytest.raises(SystemExit, match="ClickOptions"):
        get_ideas.refuse_options_ai_har(click)


def test_options_ai_dom_board_keeps_observed_fields(tmp_path: Path) -> None:
    sample = json.loads(
        (ROOT / "evidence" / "idea_boards" / "options_ai_20260921_0846_pt.json").read_text(
            encoding="utf-8"
        )
    )
    board = get_ideas.validate_options_ai_dom_board(sample)
    assert board["mode"] == "paper"
    assert board["login_health"] == "AUTHENTICATED"
    assert board["ideas"][0]["status"] == "Available"
    assert board["ideas"][0]["legs"]
    assert board["provenance"]["har_heuristic"] is False
    assert board["provenance"]["chain_xhr_mapped"] is False
    assert board["provenance"]["live_order_gate"] is False
    assert board["provenance"]["compare_metrics_invented"] is False
    assert board["ideas"][0]["compare_metrics_present"] is False
    assert board["ideas"][0]["max_risk"] is None
    assert board["ideas"][0]["pop"] is None

    rich = json.loads(json.dumps(sample))
    rich["ideas"][0]["ui_fields"]["max_risk"] = 120
    rich["ideas"][0]["ui_fields"]["max_gain"] = 340
    rich["ideas"][0]["ui_fields"]["pop"] = 0.62
    captured = get_ideas.validate_options_ai_dom_board(rich)
    assert captured["ideas"][0]["compare_metrics_present"] is True
    assert captured["ideas"][0]["compare_metrics_source"] == "dom"
    assert captured["ideas"][0]["pop"] == 0.62
    assert captured["ideas"][1]["pop"] is None

    thin = json.loads(json.dumps(sample))
    thin["ideas"][0].pop("status")
    with pytest.raises(SystemExit, match="refusing to invent Available"):
        get_ideas.validate_options_ai_dom_board(thin)


def test_dual_source_keeps_har_and_writes_shadow_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)
    shadow = tmp_path / "state" / "idea_board_latest.json"
    shadow.parent.mkdir(parents=True)
    shadow.write_text('{"previous": true}\n', encoding="utf-8")

    har = tmp_path / "trademachine_today_REDACTED.har"
    _write_har(
        har,
        [
            _entry(body=[_row("XLK", active=1, share="s_xlk")]),
            _entry(body=_xlk_legs(), url=_leg_url("s_xlk", "XLK")),
        ],
    )
    oai = tmp_path / "options_ai_board.json"
    sample = json.loads(
        (ROOT / "evidence" / "idea_boards" / "options_ai_20260921_0846_pt.json").read_text(
            encoding="utf-8"
        )
    )
    oai.write_text(json.dumps(sample), encoding="utf-8")

    bad = tmp_path / "options_ai_chain.har"
    _write_har(
        bad,
        [
            _entry(
                body={"ideas": [{"ticker": "AAPL", "strategy": "Call"}]},
                url="https://api.options.ai/markets/tradier/chain-details?symbol=AAPL",
            )
        ],
    )
    with pytest.raises(SystemExit, match="HAR→ideas publication is disabled"):
        get_ideas.run_inputs(
            source="both",
            hars=[har, bad],
            boards=[],
            write_shadow=True,
            now=NOW,
        )
    assert json.loads(shadow.read_text(encoding="utf-8")) == {"previous": True}

    summary = get_ideas.run_inputs(
        source="both",
        hars=[har],
        boards=[oai],
        write_shadow=True,
        now=NOW,
    )
    health = summary["source_health"]
    assert health["trademachine"]["ok"] is True
    assert health["options_ai"]["ok"] is True
    assert health["trademachine"]["with_legs"] == 1
    pointer = json.loads(shadow.read_text(encoding="utf-8"))
    assert pointer["order_boundary"]["wired_to_live_order_gate"] is False
    assert pointer["order_boundary"]["shadow_metadata_is_not_a_live_order_authorization"] is True
    assert {item["source"] for item in pointer["boards"]} == {"trademachine", "options_ai"}
    assert summary["wired_to_live_order_gate"] is False


def test_source_both_requires_each_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(tmp_path, monkeypatch)
    har = tmp_path / "trademachine_today_REDACTED.har"
    _write_har(har, [_entry(body=[_row("XLK", active=1)])])
    with pytest.raises(SystemExit, match="exactly one"):
        get_ideas.run_inputs(source="both", hars=[har], boards=[], write_shadow=True, now=NOW)


def test_paper_stub_never_live_and_skips_unresolved_occ() -> None:
    card = {
        "source": "trademachine",
        "occ_resolvable": False,
        "legs_missing": True,
        "provenance": {
            "execution_realm": "shadow",
            "live_order_gate": False,
            "authorizes_live_orders": False,
        },
    }
    decision = paper_one_lot_ready(card)
    assert decision["places_orders"] is False
    assert decision["api_base"] == PAPER_API_BASE
    assert decision["api_base"] == "https://sandbox.tradier.com/v1"
    assert "api.tradier.com" not in decision["api_base"]
    oai = dict(card)
    oai["source"] = "options_ai"
    assert paper_one_lot_ready(oai)["reason"] == "options_ai_dom_until_confirmed"
    naked = dict(card)
    naked["provenance"] = {"execution_realm": "live", "live_order_gate": True}
    with pytest.raises(PaperLiftError):
        paper_one_lot_ready(naked)


def test_cdp_capture_scrubs_and_refuses_raw_repo_har() -> None:
    script = ROOT / "tools" / "idea_board_scrape" / "cdp_har_capture.js"
    try:
        node = subprocess.run(
            [
                "node",
                "-e",
                (
                    "const m = require(" + json.dumps(str(script)) + ");"
                    "const url = m.scrubUrl('https://trade.options.ai/cb?token=referer-secret');"
                    "if (url.includes('referer-secret')) process.exit(4);"
                    "const headers = m.scrubHeaders("
                    "[{name:'X-API-Key', value:'header-secret-value'}]);"
                    "if (headers[0].value !== '[REDACTED]') process.exit(5);"
                    "const buf = Buffer.from('not-utf8-\\xff', 'latin1');"
                    "if (m.decodeUtf8(buf) !== null) process.exit(6);"
                    "console.log('ok');"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.skip("node is not installed")
    if node.returncode == 127:
        pytest.skip("node is not installed")
    assert node.returncode == 0, node.stderr
    refused = subprocess.run(
        ["node", str(script), str(ROOT / "evidence" / "raw.har")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 3
    assert "REFUSE raw HAR" in refused.stderr
    assert not (ROOT / "evidence" / "raw.har").exists()
