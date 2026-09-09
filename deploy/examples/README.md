# Deploy examples (placeholders only)

Copy-paste templates for a **new** host or a **parallel** install next to
legacy Helsinki. They are not a live deployment and must not contain tokens.

| Path | Role |
| --- | --- |
| `env/*.env.example` | Placeholder env files. Most install as root-owned **0600** under `/etc/trading-desk/`. |
| `env/trading-desk.env.example` | Observed `/opt/trading-desk/.env` **key names** (`TRADIER_*`, `UW_API_KEY`, `TAPE_OUT`, `FLOW_SEC`). `YOUR_*` only. See [REBUILD_NEW_PROVIDER.md](../../docs/REBUILD_NEW_PROVIDER.md). |
| `systemd/groktrading-finnhub.service` | Package Finnhub tape unit (`groktrading-finnhub-tape`). |
| `systemd/groktrading-tape.service` | Package tape **skeleton** (`groktrading-tape`). **Not** `ws_tape.py`. |
| `systemd/groktrading-account-events.service` | Tradier account-events **position truth** (never orders). Files only; not enabled by the installer. |
| `systemd/host-companions/` | Example **operator-wired** live poller units + replay-scorecard timer. **Not** copied, enabled, or started by `install_helsinki.sh`. **Merge ≠ Helsinki restart.** `emit_sit_match=False`. No webhook firehose from flow-alerts by default. Account-events stays files-only / disabled. |
| `env/*.env.example` P1/P2 knobs | `FLOW_ALERTS_POLL_SEC`, `TIDE_POLL_SEC`, `SCREENER_POLL_SEC`, `TRADIER_QUOTE_WATCH_BOUND`, `SHADOW_MARK_SEC`, `FINNHUB_WATCH_WIDEN_CAP`, `UW_WS_URL` (unset = fail-closed). Merge ≠ Helsinki restart; wire companion units separately. |
| `systemd/webhook.env.conf` | Drop-in that loads `/etc/trading-desk/grok-webhook.env`. |

Default unit names are `groktrading-*`. Observed live names are
`trading-desk-*`. The installer does not replace live units unless the
operator passes `--adopt-legacy-names` (and `--force-units` to overwrite).

See [PERMISSIONS.md](PERMISSIONS.md) and [docs/DEPLOY.md](../../docs/DEPLOY.md).
