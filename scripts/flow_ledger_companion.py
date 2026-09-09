#!/usr/bin/env python3
"""Companion UW option-trades -> hot flow ledger (Helsinki sensor farm).

Does NOT place orders, emit webhooks, or change live sit_match behavior.
Reads UW_API_KEY from the environment (EnvironmentFile). Never prints secrets.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from groktrading.flow_ledger import FlowLedger, FlowLedgerError, flow_digest

UW_OPTION_TRADES = "https://api.unusualwhales.com/api/option-trades"
DEFAULT_LEDGER = "/var/lib/trading-desk/ledger/uw_flow.sqlite"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(raw)


def _ledger_path() -> Path:
    return Path(os.environ.get("FLOW_LEDGER_PATH", DEFAULT_LEDGER))


def _uw_headers() -> dict[str, str]:
    key = os.environ.get("UW_API_KEY", "").strip()
    if not key:
        raise SystemExit("UW_API_KEY missing in environment (not printed)")
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "UW-CLIENT-API-ID": "100001",
    }


def _query() -> str:
    return urllib.parse.urlencode(
        [
            ("is_otm", "true"),
            ("volume_greater_oi", "true"),
            ("min_premium", "10000"),
            ("max_dte", "7"),
            ("min_volume", "100"),
            ("limit", "40"),
            ("excluded_tags[]", "bid_side"),
            ("issue_types[]", "Common Stock"),
        ]
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse 3xx so Authorization is never forwarded to a new origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _urlopen(req: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


def _get_json(url: str, headers: dict[str, str], timeout: float = 20.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        status = int(exc.code)
    except Exception as exc:  # noqa: BLE001 — companion stays up; log type only
        print(f"flow_ledger_companion: fetch_error={type(exc).__name__}", file=sys.stderr, flush=True)
        return -1, {}
    try:
        data = json.loads(body.decode("utf-8", errors="replace") or "{}")
    except Exception:
        data = {}
    return status, data


def _row_payload(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "executed_at": raw.get("executed_at"),
        "ticker": raw.get("ticker") or raw.get("underlying_symbol") or raw.get("underlying"),
        "occ": raw.get("option_chain_id") or raw.get("occ") or raw.get("option_symbol"),
        "print": raw.get("price") if raw.get("price") is not None else raw.get("print"),
        "nbbo_ask": raw.get("nbbo_ask") if raw.get("nbbo_ask") is not None else raw.get("ask"),
        "option_type": raw.get("option_type") or raw.get("put_call") or raw.get("type"),
    }


def poll_once(ledger: FlowLedger, headers: dict[str, str]) -> dict[str, int]:
    status, data = _get_json(f"{UW_OPTION_TRADES}?{_query()}", headers)
    rows = data.get("data") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    inserted = 0
    seen = 0
    skipped = 0
    for raw in rows:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        payload = _row_payload(raw)
        try:
            digest = flow_digest(payload)
            existed = ledger._fetch_digest("option-trades", digest) is not None  # noqa: SLF001
            ledger.append_row(payload, source="option-trades")
        except FlowLedgerError:
            skipped += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"flow_ledger_companion: append_error={type(exc).__name__}", file=sys.stderr, flush=True)
            skipped += 1
            continue
        if existed:
            seen += 1
        else:
            inserted += 1
    return {
        "http_status": status,
        "rows": len(rows),
        "inserted": inserted,
        "seen": seen,
        "skipped": skipped,
    }


def main() -> int:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    interval = _env_float("FLOW_LEDGER_POLL_SEC", _env_float("FLOW_SEC", 8.0))
    if interval < 2.0:
        interval = 2.0
    headers = _uw_headers()
    ledger = FlowLedger(path)
    print(
        f"flow_ledger_companion: start ledger={path} interval_sec={interval} "
        f"mode=append_only no_orders no_webhooks no_sit_match_emit",
        flush=True,
    )
    while True:
        try:
            stats = poll_once(ledger, headers)
            ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            print(
                f"flow_ledger_companion: ts={ts} http={stats['http_status']} "
                f"rows={stats['rows']} inserted={stats['inserted']} "
                f"seen={stats['seen']} skip={stats['skipped']}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"flow_ledger_companion: loop_error={type(exc).__name__}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
