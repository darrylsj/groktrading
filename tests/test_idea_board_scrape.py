"""HAR redact → get_ideas builds idea_board.v0_1 for Trade Machine and Options AI."""

from __future__ import annotations

import json
from pathlib import Path

import tools.idea_board_scrape.get_ideas as get_ideas
from tools.idea_board_scrape.redact_har import redact_har


def _tm_har(path: Path) -> None:
    body = json.dumps(
        [
            {
                "ticker": "BAC",
                "templateType": "credit_the_selloff",
                "isActive": 1,
                "triggeredToday": False,
                "shareKey": "s_secret_share",
            }
        ]
    )
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": (
                            "https://www.trademachine.com/wp-admin/admin-ajax.php"
                            "?action=tm_get_today2_strategy_results&token=raw-token"
                        ),
                        "headers": [{"name": "Cookie", "value": "session=raw"}],
                        "cookies": [{"name": "session", "value": "raw"}],
                        "queryString": [{"name": "token", "value": "raw-token"}],
                    },
                    "response": {
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "cookies": [],
                        "content": {"text": body},
                    },
                }
            ]
        }
    }
    path.write_text(json.dumps(har), encoding="utf-8")


def _oai_har(path: Path) -> None:
    body = json.dumps(
        {"ideas": [{"ticker": "AAPL", "strategy": "long call", "status": "Available"}]}
    )
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.options.ai/ideas",
                        "headers": [{"name": "Authorization", "value": "Bearer raw-token"}],
                        "cookies": [],
                    },
                    "response": {
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "cookies": [],
                        "content": {"text": body},
                    },
                }
            ]
        }
    }
    path.write_text(json.dumps(har), encoding="utf-8")


def test_redact_strips_cookie_and_token_query(tmp_path: Path) -> None:
    src = tmp_path / "raw.har"
    dst = tmp_path / "redacted.har"
    _tm_har(src)
    assert redact_har(src, dst) == 1
    har = json.loads(dst.read_text(encoding="utf-8"))
    request = har["log"]["entries"][0]["request"]
    assert request["headers"][0]["value"] == "[REDACTED]"
    assert request["cookies"] == []
    assert "raw-token" not in request["url"]
    assert "token=%5BREDACTED%5D" in request["url"] or "token=[REDACTED]" in request["url"]


def test_get_ideas_from_har_trademachine_and_options_ai(
    tmp_path: Path, monkeypatch
) -> None:
    board_dir = tmp_path / "evidence" / "idea_boards"
    board_dir.mkdir(parents=True)
    monkeypatch.setattr(get_ideas, "ROOT", tmp_path)
    monkeypatch.setattr(get_ideas, "BOARD_DIR", board_dir)
    monkeypatch.setattr(get_ideas, "LEDGER", board_dir / "idea_board_ledger.jsonl")
    monkeypatch.setattr(get_ideas, "SHADOW", tmp_path / "state" / "idea_board_latest.json")

    tm = tmp_path / "trademachine_today_REDACTED.har"
    oai = tmp_path / "options_ai_board_REDACTED.har"
    _tm_har(tm)
    _oai_har(oai)
    redact_har(tm, tm)
    redact_har(oai, oai)

    boards = [
        get_ideas.run_one("trademachine", tm, None),
        get_ideas.run_one("options_ai", oai, None),
    ]
    get_ideas._write_shadow(boards)

    assert boards[0]["schema"] == "idea_board.v0_1"
    assert boards[0]["source"] == "trademachine"
    assert boards[0]["ideas"][0]["ticker"] == "BAC"
    assert boards[0]["ideas"][0]["status"] == "Active"
    assert boards[0]["no_invented_prices"] is True
    assert boards[1]["schema"] == "idea_board.v0_1"
    assert boards[1]["source"] == "options_ai"
    assert boards[1]["ideas"][0]["ticker"] == "AAPL"
    assert boards[1]["mode"] == "paper"
    shadow = json.loads((tmp_path / "state" / "idea_board_latest.json").read_text())
    assert shadow["no_live_orders_from_scraper"] is True
    assert shadow["desk_use"] == "shadow_only_continual15_shortlist_candidate_feed"
    ledger = (board_dir / "idea_board_ledger.jsonl").read_text(encoding="utf-8")
    assert "shadow_paper_only" in ledger
    assert "raw-token" not in ledger
