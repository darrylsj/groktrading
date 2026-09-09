# Full rebuild of Helsinki on a different cloud provider

Operator-run checklist to stand up **today’s observed trading-desk** on a
**blank Ubuntu-like VPS** at any provider (Hetzner, DigitalOcean, AWS,
Vultr, Linode, or equivalent). No vendor lock-in. Do **not** record a
specific IP, hostname, token, webhook URL, or SSH private key in git.

This page is the **full-parity** path: copy secrets by **key name and dest
path only**, recreate systemd + the two trading-desk crons, and cut over.
The in-repo installer ([DEPLOY.md](DEPLOY.md),
[`scripts/install_helsinki.sh`](../scripts/install_helsinki.sh)) is the
**package** half of Option 1. It is **not** a port of the live loose
scripts.

**Merging this document is not a deployment.** A cloud agent must not SSH,
copy secrets, or restart units. An operator runs every step on machines
they control.

## Honesty: package skeleton ≠ live tape

The observed Helsinki host is **hand-built**. `/opt/trading-desk` has
**no `.git`**. Live behavior comes from loose scripts:

| Script | Role (observed) |
| --- | --- |
| `ws_tape.py` | UW + Tradier tape → `live_tape.json` (`trading-desk-tape.service`) |
| `finnhub_adapter.py` | Finnhub WS → `finnhub_tape.json` (`trading-desk-finnhub.service`) |
| `tape_poller.py` | Weekday RTH cron |
| `nightly_print_bt.py` | Weekday evening cron |

This repository’s `groktrading-tape` CLI writes a **signals-only skeleton**
JSON. It is **not** `ws_tape.py`. A rebuild that **preserves today’s
behavior** must **copy or re-home those legacy scripts** (and their venv)
until package parity exists. Integrating Finnhub ticks into the Tradier/UW
tape remains an **explicit remaining deployment step**
([OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md)).

P1/P2 sensor-farm helpers (flow-alerts, tide_state, quote interest, screener,
shadow marks, UW_WS_URL probe) are **package CLIs**. Merging this repo does
not restart Helsinki. Wire companion units separately. `UW_WS_URL` unset
fail-closes; do not invent a socket protocol. Do not auto-start
account-events.

## Hard rules (do not weaken)

| Rule | Meaning |
| --- | --- |
| No secrets in git | Never commit token values, live webhook URLs/keys, private SSH keys, or host IPs used as credentials. Document **key names** and **dest paths** only. |
| WebSocket never places orders | Finnhub / UW / Tradier WS ticks are not an order path. |
| Finnhub ≠ option NBBO | Do not gate option limit prices on Finnhub ticks. |
| ≥20% cash / max deploy 80% | Overnight long options are allowed. |
| 12:30 PT new-entry cutoff | America/Los_Angeles. **Not** a forced flatten. |
| Sandbox ≠ live fill evidence | Tradier production NBBO is pricing truth. |
| `signals_only` until explicit live | Default mode. Do not set live enablement as part of this rebuild. |
| Trading-desk only | Do **not** copy poly / edgar / spx / Aria (or other shared-host) crons unless the operator **opts in** in writing. |

## Scope

**In scope (trading-desk wake path)**

- New VPS, SSH, firewall, OS deps
- Package tree at `/opt/groktrading` and/or legacy tree at `/opt/trading-desk`
- Three env files (key names below), systemd units + webhook drop-in
- Two trading-desk crons (`CRON_TZ=America/Los_Angeles`)
- Grok Bot routine **Helsinki tape event** webhook (operator panel →
  `GROK_WEBHOOK_*` on the new host)

**Out of scope unless the operator opts in**

- poly / edgar / spx / Aria crons and their env files
- Any other job on the shared old host that is not trading-desk
- Claiming this git commit is the live executor

---

## Observed inventory (names only — do not invent values)

Current host is hand-built (not this git checkout). No IP recorded here.

### Code / runtime

| Path | Notes |
| --- | --- |
| `/opt/trading-desk/` | No `.git` |
| `/opt/trading-desk/ws_tape.py` | Live tape writer |
| `/opt/trading-desk/finnhub_adapter.py` | Finnhub adapter |
| `/opt/trading-desk/tape_poller.py` | RTH cron |
| `/opt/trading-desk/nightly_print_bt.py` | Nightly scorer |
| `/opt/trading-desk/venv` | Local venv; observed `pip freeze` included `websockets` |
| `/opt/trading-desk/live_tape.json` | Tape output |
| `/opt/trading-desk/finnhub_tape.json` | Finnhub tape output |
| `/opt/trading-desk/poller.log` | Poller log |
| `/opt/trading-desk/backtests/` | Nightly outputs |

### Secrets / env (0600, root)

Key **names** only. Never paste live values into git or chat.

| File | Keys present |
| --- | --- |
| `/opt/trading-desk/.env` | `TRADIER_ACCOUNT_ID`, `TRADIER_ACCESS_TOKEN`, `TRADIER_API_BASE`, `UW_API_KEY`, `TAPE_OUT`, `FLOW_SEC` |
| `/etc/trading-desk/finnhub.env` | `FINNHUB_API_KEY` |
| `/etc/trading-desk/grok-webhook.env` | `GROK_WEBHOOK_URL`, `GROK_WEBHOOK_KEY`, `GROK_WEBHOOK_AUTH_HEADER` |

Placeholder templates (not filled files):
[`deploy/examples/env/trading-desk.env.example`](../deploy/examples/env/trading-desk.env.example),
[`deploy/examples/env/finnhub.env.example`](../deploy/examples/env/finnhub.env.example).
The package webhook example uses `GROK_WEBHOOK_SECRET` (HMAC helper in this
repo). The **observed** host file uses `GROK_WEBHOOK_KEY` and
`GROK_WEBHOOK_AUTH_HEADER`. For full-parity rebuild, copy the **observed
key names**.

### systemd

| Unit | Observed layout |
| --- | --- |
| `trading-desk-tape.service` | `WorkingDirectory=/opt/trading-desk`; `EnvironmentFile=/opt/trading-desk/.env`; `ExecStart=` venv python `ws_tape.py`; drop-in loads `EnvironmentFile=-/etc/trading-desk/grok-webhook.env` |
| `trading-desk-finnhub.service` | `EnvironmentFile=-/etc/trading-desk/finnhub.env`; `ExecStart=` venv python `finnhub_adapter.py` |

### cron (`CRON_TZ=America/Los_Angeles`)

Trading-desk **only**. Do not migrate unrelated jobs from the shared host.

| Schedule | Job |
| --- | --- |
| `* 6-12 * * 1-5` | `tape_poller.py` (loads `.env`) |
| `15 19 * * 1-5` | `nightly_print_bt.py` (loads `.env`) |

### Operator-side (not trading-desk files on Helsinki disk)

| Item | Where it lives | Notes |
| --- | --- | --- |
| Grok Bot routine **Helsinki tape event** webhook URL + key | Grok Bot routine panel | Must be recreated or copied into `GROK_WEBHOOK_*` on the new host. Never commit the URL or key. See [H](#h-point--update-the-grok-webhook). |
| SSH access to the new VPS | Operator-managed key pair | Do not commit private keys (`id_rsa*`, `*.pem`). |

---

## A. Provision a new Ubuntu-like VPS

Any provider. Generic Ubuntu LTS (or Debian-like with systemd, apt, Python
≥ 3.11). Do not claim a specific IP in this repo.

1. Create a VPS (2 GB RAM is enough for this desk; more is fine).
2. Note the address **only on the operator workstation** (password manager
   or SSH config). Do not paste it into git, chat, or this PR.
3. Attach the operator’s **public** SSH key at create time.
4. Confirm login as a sudo-capable user (or root, then create a sudo user).

```bash
# From the operator workstation — replace NEW_HOST yourself; do not commit it
ssh -o IdentitiesOnly=yes -i ~/.ssh/YOUR_OPERATOR_KEY YOUR_USER@NEW_HOST
```

## B. Harden basics

Do this before copying secrets.

1. **SSH key auth only.** Disable password authentication once key login
   works. Do not commit `sshd_config` with host-specific secrets.

   ```bash
   sudo install -d -m 0700 /root/.ssh   # if you will scp as root
   # PasswordAuthentication no  — in sshd_config, then reload sshd
   ```

2. **Firewall:** allow inbound SSH; allow outbound HTTPS (and DNS) as
   needed for Tradier / UW / Finnhub / Grok webhook. Deny other inbound.

   ```bash
   sudo apt-get update
   sudo apt-get install -y ufw
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow OpenSSH
   sudo ufw --force enable
   sudo ufw status
   ```

   Tightening outbound to HTTPS-only is optional and provider-specific
   (you still need DNS). Do not lock yourself out of SSH.

3. Unattended upgrades are optional. Do not disable SSH to “be safer.”

## C. Install OS deps and clone this repo

Follow [DEPLOY.md](DEPLOY.md) section A for the **package** tree. Summary:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip rsync sudo cron
```

Clone `darrylsj/groktrading` to **`/opt/groktrading`** (not the live legacy
path):

```bash
sudo git clone https://github.com/darrylsj/groktrading.git /opt/groktrading
cd /opt/groktrading
sudo git checkout --detach <tag-or-commit-you-intend>
sudo ./scripts/install_helsinki.sh --dry-run
sudo ./scripts/install_helsinki.sh
```

The installer defaults: `INSTALL_ROOT=/opt/groktrading`, package-named
units `groktrading-*.service`, **no** `--enable` / `--start`, **never**
writes tokens. See the script header in
[`scripts/install_helsinki.sh`](../scripts/install_helsinki.sh).

If you will also run the **legacy** tree (required for today’s behavior),
create the dest dir **empty** and copy scripts in [E](#e-code-migration-options).
Do **not** point `INSTALL_ROOT` at `/opt/trading-desk` unless you pass
`--allow-legacy-root` and understand that still does not port `ws_tape.py`.
`sit_match` freshness (`executed_at` ≤ `SIT_MATCH_MAX_AGE_SEC`, default 60s)
is in `groktrading.sit_match`; copy that check into the live tape sit_match
branch when you migrate `ws_tape.py`, then restart `trading-desk-tape`.
Helsinki remains a **sensor farm** (always-on listen; Grok decides). Reinstall
must keep: hot ledger under `/var/lib/trading-desk/ledger` (7–14 days), Box
cold-rotate deny-list ([BOX_ARCHIVE.md](BOX_ARCHIVE.md)), and account-events
as **position truth** only. `ws_tape.py` stays dest-only.
**Grok Update Computer does not rebuild Helsinki.**

## D. Secret copy matrix

Copy **files**, not chat paste. Transfer as **root over SSH** (`scp -p`).
Never git, never Slack/chat, never this repository.

On the **new** host, create dest directories first:

```bash
sudo install -d -m 0700 /etc/trading-desk
sudo install -d -m 0755 /opt/trading-desk
```

### Matrix

| Source (old host) | Dest (new host) | Mode / owner | Keys present (names only) | Safe transfer |
| --- | --- | --- | --- | --- |
| `/opt/trading-desk/.env` | `/opt/trading-desk/.env` | `0600` `root:root` | `TRADIER_ACCOUNT_ID`, `TRADIER_ACCESS_TOKEN`, `TRADIER_API_BASE`, `UW_API_KEY`, `TAPE_OUT`, `FLOW_SEC` | `scp` as root; then `cut -d= -f1` only |
| `/etc/trading-desk/finnhub.env` | `/etc/trading-desk/finnhub.env` | `0600` `root:root` | `FINNHUB_API_KEY` | same |
| `/etc/trading-desk/grok-webhook.env` | `/etc/trading-desk/grok-webhook.env` | `0600` `root:root` | `GROK_WEBHOOK_URL`, `GROK_WEBHOOK_KEY`, `GROK_WEBHOOK_AUTH_HEADER` | same; or rotate via [H](#h-point--update-the-grok-webhook) and write new values **on the host only** |

Example file matching the first row’s **key names** (placeholders only):
[`deploy/examples/env/trading-desk.env.example`](../deploy/examples/env/trading-desk.env.example).
Use it only if you must **re-type** keys from a password manager. Prefer
`scp` of the live file so values are not re-typed into a terminal history.

### Transfer commands (placeholders — no real hosts)

From an operator workstation that can SSH to **both** hosts. Use
`OLD_HOST` / `NEW_HOST` from your SSH config. Do not commit those names
if they embed credentials.

```bash
# Privileged copy; preserve mode if possible; never cat the file
scp -p YOUR_USER@OLD_HOST:/opt/trading-desk/.env /tmp/td.env
scp -p /tmp/td.env YOUR_USER@NEW_HOST:/tmp/td.env
ssh YOUR_USER@NEW_HOST 'sudo install -o root -g root -m 0600 /tmp/td.env /opt/trading-desk/.env && sudo shred -u /tmp/td.env'
shred -u /tmp/td.env

scp -p YOUR_USER@OLD_HOST:/etc/trading-desk/finnhub.env /tmp/fh.env
scp -p /tmp/fh.env YOUR_USER@NEW_HOST:/tmp/fh.env
ssh YOUR_USER@NEW_HOST 'sudo install -o root -g root -m 0600 /tmp/fh.env /etc/trading-desk/finnhub.env && sudo shred -u /tmp/fh.env'
shred -u /tmp/fh.env

scp -p YOUR_USER@OLD_HOST:/etc/trading-desk/grok-webhook.env /tmp/wh.env
scp -p /tmp/wh.env YOUR_USER@NEW_HOST:/tmp/wh.env
ssh YOUR_USER@NEW_HOST 'sudo install -o root -g root -m 0600 /tmp/wh.env /etc/trading-desk/grok-webhook.env && sudo shred -u /tmp/wh.env'
shred -u /tmp/wh.env
```

If you can SSH as root on both sides, a single `scp -p root@OLD_HOST:PATH root@NEW_HOST:PATH` is shorter. Same rules: no chat, shred workstation temps.

### Verify key **names** only

On the **new** host. This prints names, not values:

```bash
sudo cut -d= -f1 /opt/trading-desk/.env
sudo cut -d= -f1 /etc/trading-desk/finnhub.env
sudo cut -d= -f1 /etc/trading-desk/grok-webhook.env
sudo stat -c '%a %U:%G %n' /opt/trading-desk/.env /etc/trading-desk/finnhub.env /etc/trading-desk/grok-webhook.env
```

Expected names match the matrix. Expected mode `600`, owner `root`. If
`cut` shows a value (no `=`), stop and fix the file — do not paste it
anywhere.

Do **not** `cat`, `less`, or `journalctl` in a way that dumps token
values into a ticket or chat.

After copy, confirm `TAPE_OUT` on the new host still points at a path
that will exist (typically under `/opt/trading-desk/`). Adjust the **path**
if you re-home outputs; do not publish the token lines.

## E. Code migration options

Choose **one** primary style. Option 1 is recommended so the package and
the live scripts do not overwrite each other.

### Option 1 — recommended parallel (package + legacy scripts)

1. Install the package via [C](#c-install-os-deps-and-clone-this-repo)
   (`/opt/groktrading`, `groktrading-*.service`). Leave those units
   **disabled** until you decide you want the skeleton writers at all.
2. **Separately** copy the observed loose scripts (not secrets — already
   copied in D):

   ```bash
   scp YOUR_USER@OLD_HOST:/opt/trading-desk/ws_tape.py \
       YOUR_USER@OLD_HOST:/opt/trading-desk/finnhub_adapter.py \
       YOUR_USER@OLD_HOST:/opt/trading-desk/tape_poller.py \
       YOUR_USER@OLD_HOST:/opt/trading-desk/nightly_print_bt.py \
       YOUR_USER@NEW_HOST:/tmp/trading-desk-py/
   ssh YOUR_USER@NEW_HOST 'sudo install -o root -g root -m 0755 /tmp/trading-desk-py/*.py /opt/trading-desk/'
   ```

3. Recreate the legacy venv (package names only — `pip freeze` on the old
   host is not a secret):

   ```bash
   # On OLD_HOST — capture names/versions only
   /opt/trading-desk/venv/bin/pip freeze
   ```

   ```bash
   # On NEW_HOST
   sudo python3 -m venv /opt/trading-desk/venv
   sudo /opt/trading-desk/venv/bin/pip install --upgrade pip
   sudo /opt/trading-desk/venv/bin/pip install websockets
   # Then install the rest of the freeze list you captured (package==version lines only)
   ```

   Observed freeze included `websockets`. Do not invent a full lockfile
   here. Install what the copied scripts import.

4. Recreate **legacy** systemd units in [F](#f-recreate-systemd-units--webhook-drop-in)
   pointing at `/opt/trading-desk` and `venv/bin/python`. Do not point
   `trading-desk-tape` at `groktrading-tape` and expect UW+Tradier parity.

5. Optional: enable `groktrading-*` later for comparison under
   `/var/lib/trading-desk/`. Do not overwrite `/opt/trading-desk/*.json`.

### Option 2 — legacy clone (preserve today’s unit names)

Skip the package units if you only want today’s behavior.

1. Copy the four `*.py` files and recreate `venv` as in Option 1 steps 2–3.
2. Recreate `trading-desk-tape.service` and
   `trading-desk-finnhub.service` to match the observed layout ([F](#f-recreate-systemd-units--webhook-drop-in)).
3. Still keep secrets **out of git**. Still clone this repo somewhere if
   you want the runbook on-box (`/opt/groktrading` is fine as docs +
   future installer). Do not `rsync --delete` `/opt/trading-desk`.

Either option: **do not** enable live trading as part of the copy.

## F. Recreate systemd units + webhook drop-in

**Do not enable or start until the env files from [D](#d-secret-copy-matrix) exist
and `cut -d= -f1` matches the matrix.**

These templates match the **observed** layout. They embed **no** tokens.
Adjust `User=` if the old host runs as `root` (observed env files are
root-owned 0600; if the process user cannot read them, run as root or
grant ACL — do not chmod 0644).

`/etc/systemd/system/trading-desk-tape.service`:

```ini
[Unit]
Description=Trading desk UW/Tradier tape (legacy ws_tape.py; signals path)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/trading-desk
EnvironmentFile=/opt/trading-desk/.env
ExecStart=/opt/trading-desk/venv/bin/python /opt/trading-desk/ws_tape.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Drop-in `/etc/systemd/system/trading-desk-tape.service.d/webhook.conf`
(same idea as [`deploy/examples/systemd/webhook.env.conf`](../deploy/examples/systemd/webhook.env.conf)):

```ini
[Service]
EnvironmentFile=-/etc/trading-desk/grok-webhook.env
```

`/etc/systemd/system/trading-desk-finnhub.service`:

```ini
[Unit]
Description=Trading desk Finnhub adapter (legacy finnhub_adapter.py)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/trading-desk
EnvironmentFile=-/etc/trading-desk/finnhub.env
ExecStart=/opt/trading-desk/venv/bin/python /opt/trading-desk/finnhub_adapter.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
# enable/start ONLY after env files exist
sudo systemctl enable trading-desk-tape.service trading-desk-finnhub.service
sudo systemctl start trading-desk-tape.service trading-desk-finnhub.service
```

If you also installed package units via `install_helsinki.sh`, they stay
separate (`groktrading-*`). Do not `--adopt-legacy-names --force-units`
onto these recreated files unless you intend to **replace** `ws_tape.py`
with the package skeleton (you do not, for full-parity).

## G. Recreate the two trading-desk crons

Timezone **must** be `America/Los_Angeles` (already fixed once on the
observed host; see CHANGELOG). Trading-desk **only**.

Install as `/etc/cron.d/trading-desk` (root crontab fragment) or the
equivalent crontab that already exists on the old host — copy **these two
lines and `CRON_TZ`**, not the rest of the shared crontab.

```cron
CRON_TZ=America/Los_Angeles
# RTH tape poller (weekdays 06:00–12:59 PT). Script loads /opt/trading-desk/.env
* 6-12 * * 1-5 root /opt/trading-desk/venv/bin/python /opt/trading-desk/tape_poller.py
# Nightly print scorer (19:15 PT weekdays). Script loads /opt/trading-desk/.env
15 19 * * 1-5 root /opt/trading-desk/venv/bin/python /opt/trading-desk/nightly_print_bt.py
```

If the old host runs these from a non-root crontab, keep that user and
ensure the user can read `/opt/trading-desk/.env` **without** chmod 0644
(group or ACL). Prefer matching the old host.

**Do not** copy poly / edgar / spx / Aria cron lines from the shared host.

Confirm:

```bash
sudo grep -n 'CRON_TZ\|tape_poller\|nightly_print_bt\|poly\|edgar\|spx\|Aria' /etc/cron.d/* /var/spool/cron/crontabs/* 2>/dev/null || true
```

You want `CRON_TZ=America/Los_Angeles`, the two trading-desk jobs, and
**no** poly/edgar/spx/Aria unless you opted in.

## H. Point / update the Grok webhook

The new host must post to the Grok Bot routine that wakes on Helsinki
tape events. The URL and key are **not** in this git tree.

### How to obtain URL + key (Grok Bot routine panel)

1. On the **Grok Bot computer** (not the VPS), open the Grok Bot
   **Routines** panel.
2. Open the routine that wakes on Helsinki tape / `sit_match` (operator
   name: **Helsinki tape event**, or the equivalent wake path you already
   use).
3. Open that routine’s **webhook** (inbound URL / key) settings.
4. Copy, **onto the new host file only**:
   - URL → `GROK_WEBHOOK_URL`
   - Key → `GROK_WEBHOOK_KEY`
   - Auth header name the routine expects → `GROK_WEBHOOK_AUTH_HEADER`
5. Never paste those values into git, chat, email, or a PR.

### Same URL vs rotate

| Choice | What to do |
| --- | --- |
| Keep the same routine URL | `scp` `grok-webhook.env` as in [D](#d-secret-copy-matrix). Old and new hosts would both fire if both units run — avoid dual-fire during overlap (see [J](#j-cutover)). |
| Rotate URL/key | Create a new webhook in the routine panel. Write the new key names/values into `/etc/trading-desk/grok-webhook.env` on the **new** host (`0600` root). Leave the old host on the old URL until you stop it, or update both if you intend a coordinated swap. |

After the file exists:

```bash
sudo systemctl daemon-reload
sudo systemctl restart trading-desk-tape.service   # operator only; not a cloud agent
```

## I. Validation checklist

No invented prices, prints, or P&L. Confirm **process health** and
**mtime / log tokens**, not fictional NBBO.

Do this during **RTH** (regular trading hours) when possible.

| Check | How (redact values) | Pass |
| --- | --- | --- |
| Units active | `systemctl is-active trading-desk-tape.service trading-desk-finnhub.service` | `active` |
| `live_tape.json` mtime advancing in RTH | `stat -c '%y %n' /opt/trading-desk/live_tape.json` twice, minutes apart | Timestamp moves; do not invent a print |
| Finnhub `SUBSCRIBED` | `journalctl -u trading-desk-finnhub.service -n 80 --no-pager` (no token lines into chat) | Log shows subscribe/subscribed for the watchlist the adapter uses |
| Webhook env **PRESENT** in the tape process | `sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value trading-desk-tape.service)/environ \| cut -d= -f1 \| grep '^GROK_WEBHOOK_'` | Key **names** `GROK_WEBHOOK_URL`, `GROK_WEBHOOK_KEY`, `GROK_WEBHOOK_AUTH_HEADER` present; **do not** print values |
| One material `sit_match` wakes Grok | Wait for a real material event, or an operator-owned test fire from the host | Routine wakes; no invented sit or P&L |
| Hard rules still on | Mode remains `signals_only` unless you separately and explicitly enable paper/live | WS still does not place orders |

Package-only extra (if you started `groktrading-*`): skeleton JSON under
`/var/lib/trading-desk/` is **not** evidence the live tape was ported.

## J. Cutover

Nothing here is done by merge, by CI, or by a cloud agent.

1. **New host** validated ([I](#i-validation-checklist)), including webhook
   present and no dual-fire plan.
2. **Stop old** trading-desk units and **comment out / remove only** the
   two trading-desk cron lines on the **old** host:

   ```bash
   # On OLD_HOST — operator
   sudo systemctl stop trading-desk-tape.service trading-desk-finnhub.service
   sudo systemctl disable trading-desk-tape.service trading-desk-finnhub.service
   # Disable the two trading-desk crons only — leave poly/edgar/spx/Aria alone
   ```

3. **Start new** (if not already running as the live path):

   ```bash
   # On NEW_HOST — operator
   sudo systemctl enable --now trading-desk-tape.service trading-desk-finnhub.service
   ```

4. Re-run [I](#i-validation-checklist) on the new host. Confirm the Grok
   routine no longer receives events from the old host.
5. **Keep the old host warm for N trading days** (operator chooses N). Do
   not shred env files on the old host until you are sure. Do not leave
   old units **enabled** (that causes dual webhook fire).
6. **Decommission** the old VPS only after N days of clean new-host
   operation. Rotate any keys that lived only on the old disk if the
   provider retains snapshots.
7. Record the cutover as an **operator** note in
   [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md) and
   [CHANGELOG.md](../CHANGELOG.md). Until that note exists, this repo
   still does not claim the live host runs this commit.

---

## Related

- Package installer path: [DEPLOY.md](DEPLOY.md)
- Observed host facts: [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md)
- Env permissions: [deploy/examples/PERMISSIONS.md](../deploy/examples/PERMISSIONS.md)
- Safety: [SAFETY.md](SAFETY.md)
- Operating model: [OPERATING_MODEL.md](OPERATING_MODEL.md)
