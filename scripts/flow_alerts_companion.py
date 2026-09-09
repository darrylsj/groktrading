#!/usr/bin/env python3
"""Helsinki host companion: poll UW flow-alerts via package helpers.

Calls groktrading.feeds.flow_alerts.poll_flow_alerts (NOT the offline CLI).
emit_sit_match=False always — never spray sit_match.
On material emit: append a small JSONL line (no Grok webhook tonight).
Never prints tokens.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helsinki_http import UrllibHttp  # noqa: E402

from groktrading.feeds.flow_alerts import (  # noqa: E402
    SeenAlertStore,
    flow_alerts_poll_sec,
    poll_flow_alerts,
    state_document,
)
from groktrading.feeds.unusual_whales import UnusualWhalesClient  # noqa: E402
from groktrading.flow_ledger import FlowLedger  # noqa: E402
from groktrading.io_atomic import write_json_atomic  # noqa: E402
from groktrading.timeutil import UTC  # noqa: E402

DEFAULT_LEDGER = "/var/lib/trading-desk/ledger/uw_flow.sqlite"
DEFAULT_SEEN = "/var/lib/trading-desk/ledger/flow_alerts_seen.json"
DEFAULT_STATE = "/var/lib/trading-desk/state/flow_alerts.json"
DEFAULT_MATERIAL = "/var/lib/trading-desk/state/flow_alerts_material.jsonl"


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _append_material(path: Path, hit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    line = {
        "alert_id": hit.alert_id,
        "event_type": hit.event_type,
        "ts": ts,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, separators=(",", ":"), sort_keys=True))
        handle.write("\n")


def main() -> int:
    ledger_path = Path(os.environ.get("FLOW_LEDGER_PATH", DEFAULT_LEDGER))
    seen_path = Path(os.environ.get("FLOW_ALERTS_SEEN_PATH", DEFAULT_SEEN))
    state_path = Path(os.environ.get("FLOW_ALERTS_STATE_PATH", DEFAULT_STATE))
    material_path = Path(
        os.environ.get("FLOW_ALERTS_MATERIAL_PATH", DEFAULT_MATERIAL)
    )
    token = os.environ.get("UW_API_KEY", "").strip()
    if not token:
        print(
            "flow_alerts_companion: UW_API_KEY missing (not printed)",
            file=sys.stderr,
            flush=True,
        )
        return 2

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.parent.mkdir(parents=True, exist_ok=True)

    clock = UtcClock()
    client = UnusualWhalesClient(
        http=UrllibHttp(timeout=20.0), clock=clock, token=token
    )
    ledger = FlowLedger(ledger_path, clock=clock)
    seen = SeenAlertStore(path=seen_path)
    env = dict(os.environ)

    print(
        "flow_alerts_companion: start "
        f"ledger={ledger_path} state={state_path} "
        "emit_sit_match=False no_webhook no_orders",
        flush=True,
    )

    while True:
        interval = flow_alerts_poll_sec(env)
        try:

            def on_material(hit) -> None:
                # No Grok webhook tonight — JSONL only.
                _append_material(material_path, hit)

            result = poll_flow_alerts(
                client,
                ledger,
                seen,
                now=clock.now(),
                env=env,
                on_material=on_material,
                emit_sit_match=False,
            )
            doc = state_document(
                result, now=clock.now(), seen_count=len(seen._ids)  # noqa: SLF001
            )
            doc["live_http"] = True
            doc["mode"] = "host_companion"
            write_json_atomic(state_path, doc)
            ts = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            print(
                f"flow_alerts_companion: ts={ts} fetched={result.fetched} "
                f"stored={result.stored} new_ids={result.new_ids} "
                f"emitted={result.emitted} skipped={result.skipped} "
                f"cadence={result.cadence_sec}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 — stay up; log type only
            print(
                f"flow_alerts_companion: loop_error={type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
