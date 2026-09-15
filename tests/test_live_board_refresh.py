"""Helsinki live-board refresh: fixtures only. No Helsinki. No Vercel token."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from dashboard.book import build_book, build_open_orders
from dashboard.builder import build_board, write_board
from dashboard.ws_stats import build_ws_stats
from scripts_loader import live_board_refresh

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dashboard"
NOW = "2026-09-15T14:05:00+00:00"
SESSION = "2026-09-15"
TEST_TOKEN = "unused-test-token"


def test_book_and_orders_from_fixtures_do_not_invent() -> None:
    book = build_book(FIXTURES / "book.json")
    assert book["present"] is True
    assert book["pnl"] is None
    assert book["invented"] is False
    assert book["places_orders"] is False
    assert book["cash"] == "421.74"
    assert book["positions"][0]["occ"] == "QQQ260914P00580000"
    assert book["positions"][0]["avg_fill"] == "1.25"
    assert "bid" not in book["positions"][0]
    assert "mark" not in book["positions"][0]
    orders = build_open_orders(FIXTURES / "open_orders.json")
    assert orders["present"] is True
    assert orders["places_orders"] is False
    assert orders["orders"][0]["occ"] == "SPY260914C00660000"
    assert orders["orders"][0]["limit"] == "0.80"


def test_book_and_orders_missing_are_holes() -> None:
    missing = build_book(Path("/no/such/book.json"))
    assert missing["present"] is False
    assert missing["empty_reason"] == "file_missing"
    assert missing["positions"] == []
    assert missing["pnl"] is None
    none = build_open_orders(None)
    assert none["empty_reason"] == "no_input"
    assert none["orders"] == []


def test_book_and_orders_can_cite_live_tape_lists() -> None:
    tape = FIXTURES / "live_tape_with_book.json"
    book = build_book(None, live_tape=tape)
    assert book["present"] is True
    assert book["source"] == "live_tape"
    assert book["positions"][0]["occ"] == "IWM260914P00240000"
    assert book["positions"][0]["cost_basis"] == "0.55"
    orders = build_open_orders(None, live_tape=tape)
    assert orders["present"] is True
    assert orders["source"] == "live_tape"
    assert orders["orders"][0]["side"] == "sell_to_close"
    assert orders["orders"][0]["limit_price"] == "0.70"


def test_ws_stats_shortlist_consumer_status() -> None:
    stats = build_ws_stats(
        finnhub_tape=FIXTURES / "finnhub_tape.json",
        live_tape=FIXTURES / "live_tape_health.json",
        shortlist=FIXTURES / "shortlist.json",
    )
    short = stats["shortlist"]
    assert short["present"] is True
    assert short["emit_sit_match"] is False
    assert short["consumer"] == "Continual15"
    assert short["candidate_occs"] == ["QQQ260914P00580000"]
    assert short["candidate_count"] == 1
    assert "pack evidence cards" in short["note"]
    assert stats["missing"] == []


def test_refresh_script_writes_live_json_without_token(tmp_path: Path) -> None:
    out = tmp_path / "live_board"
    code = live_board_refresh.main(
        [
            "--live-tape",
            str(FIXTURES / "live_tape_health.json"),
            "--finnhub-tape",
            str(FIXTURES / "finnhub_tape.json"),
            "--shortlist",
            str(FIXTURES / "shortlist.json"),
            "--refuses",
            str(FIXTURES / "uw_opportunity_refuses.jsonl"),
            "--book",
            str(FIXTURES / "book.json"),
            "--open-orders",
            str(FIXTURES / "open_orders.json"),
            "--out-dir",
            str(out),
            "--session",
            SESSION,
            "--now",
            NOW,
            "--vercel-env",
            str(tmp_path / "missing.vercel.env"),
        ]
    )
    assert code == 0
    live_path = out / "live.json"
    html_path = out / "index.html"
    assert live_path.is_file()
    assert html_path.is_file()
    doc = json.loads(live_path.read_text(encoding="utf-8"))
    assert doc["live_gate"] is False
    assert doc["places_orders"] is False
    assert doc["invented"] is False
    assert doc["sit_match"] is False
    assert doc["refresh"]["llm"] is False
    assert doc["refresh"]["owner"] == "helsinki"
    assert doc["book"]["positions"][0]["occ"] == "QQQ260914P00580000"
    assert doc["open_orders"]["orders"][0]["limit"] == "0.80"
    assert doc["ws_stats"]["shortlist"]["consumer"] == "Continual15"
    assert doc["funnel"]["present"] is True
    html = html_path.read_text(encoding="utf-8")
    assert "Book" in html
    assert "Open orders" in html
    assert "Shortlist candidates" in html
    assert "QQQ260914P00580000" in html
    assert TEST_TOKEN not in html
    assert "Bearer" not in html
    assert "Authorization" not in html


def test_refresh_missing_refuses_is_honest_lag(tmp_path: Path) -> None:
    out = tmp_path / "empty"
    code = live_board_refresh.main(
        [
            "--live-tape",
            str(FIXTURES / "live_tape_health.json"),
            "--finnhub-tape",
            str(FIXTURES / "finnhub_tape.json"),
            "--shortlist",
            str(FIXTURES / "shortlist.json"),
            "--refuses",
            str(tmp_path / "no-refuses.jsonl"),
            "--out-dir",
            str(out),
            "--now",
            NOW,
            "--skip-deploy",
        ]
    )
    assert code == 0
    doc = json.loads((out / "live.json").read_text(encoding="utf-8"))
    assert doc["funnel"]["present"] is False
    assert doc["funnel"]["empty_reason"] == "file_missing"
    assert "lag" in (doc.get("funnel_lag_note") or "").lower()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "may lag" in html.lower() or "refuse ledger" in html.lower()


def test_refresh_skip_deploy_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "skip"
    code = live_board_refresh.main(
        [
            "--live-tape",
            str(FIXTURES / "live_tape_health.json"),
            "--out-dir",
            str(out),
            "--now",
            NOW,
            "--skip-deploy",
        ]
    )
    assert code == 0
    assert (out / "live.json").is_file()


def test_discover_refuses_first_existing_wins(tmp_path: Path, monkeypatch: Any) -> None:
    explicit = tmp_path / "explicit.jsonl"
    explicit.write_text("{}\n", encoding="utf-8")
    assert live_board_refresh.discover_refuses(explicit) == explicit
    assert live_board_refresh.discover_refuses(None) is None
    created = tmp_path / "uw_opportunity_refuses.jsonl"
    created.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        live_board_refresh,
        "HOST_REFUSE_CANDIDATES",
        (str(tmp_path / "missing.jsonl"), str(created)),
    )
    assert live_board_refresh.discover_refuses(None) == created


def test_vercel_creds_never_require_file() -> None:
    creds = live_board_refresh.vercel_creds(Path("/no/such/vercel.env"))
    assert creds == {}


def test_deploy_api_posts_without_echoing_token(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>board</html>\n", encoding="utf-8")
    (tmp_path / "live.json").write_text('{"ok":true}\n', encoding="utf-8")
    seen: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            seen["auth"] = self.headers.get("Authorization")
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(length) or b"{}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"dpl_fixture","url":"example.vercel.app"}')

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        live_board_refresh.VERCEL_DEPLOY_API = f"http://127.0.0.1:{server.server_port}/v13/deployments"
        result = live_board_refresh.deploy_via_api(
            tmp_path,
            {"VERCEL_TOKEN": TEST_TOKEN, "VERCEL_ORG_ID": "team_fixture"},
        )
    finally:
        server.shutdown()
        server.server_close()
        live_board_refresh.VERCEL_DEPLOY_API = "https://api.vercel.com/v13/deployments"
    assert result["ok"] is True
    assert result["id"] == "dpl_fixture"
    assert result["url"] == "https://example.vercel.app"
    assert TEST_TOKEN not in json.dumps(result)
    assert seen["auth"] == f"Bearer {TEST_TOKEN}"
    assert "teamId=team_fixture" in seen["path"]
    names = {item["file"] for item in seen["body"]["files"]}
    assert "index.html" in names
    assert "live.json" in names
    assert seen["body"]["target"] == "production"
    assert seen["body"]["name"] == "trading-desk-live-board"


def test_script_is_secret_free_and_executable() -> None:
    path = ROOT / "scripts" / "live_board_refresh.py"
    text = path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o111
    assert "AKIA" not in text
    assert "ghp_" not in text
    assert "never logs tokens" in text.lower() or "never logs tokens" in text
    assert "sit_match stays OFF" in text
    assert "No LLM" in text or "Zero LLM" in text
    assert "openai" not in text.lower()
    assert "grok-webhook" not in text.lower()


def test_write_board_emits_live_json(tmp_path: Path) -> None:
    board = build_board(
        refuses=FIXTURES / "uw_opportunity_refuses.jsonl",
        shortlist=FIXTURES / "shortlist.json",
        book=FIXTURES / "book.json",
        session=SESSION,
        now=NOW,
    )
    written = write_board(board, out_dir=tmp_path)
    assert Path(written["live_json"]).name == "live.json"
    assert Path(written["board_json"]).name == "board.json"
    live = json.loads(Path(written["live_json"]).read_text(encoding="utf-8"))
    assert live["book"]["present"] is True
    assert "token" not in json.dumps(live).lower() or "token" in "no token committed"
