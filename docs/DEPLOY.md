# Rebuild / new host

Portable, **secret-free** install path for this repository. Use it to stand up
a brand-new Ubuntu-like VPS or to place a **parallel** package tree next to
the observed Helsinki host. Merging this repo, running the installer, or
copying example units is **not** a claim that Helsinki already runs this
commit. Observed live facts stay in [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md).

Do **not** SSH, deploy, or restart services from a cloud agent. An operator
runs these steps on the machine they control.

## Different provider full rebuild

This page is the **package installer** path (`/opt/groktrading`,
`groktrading-*.service`, skeleton tape). It does **not** copy live secrets,
legacy `ws_tape.py`, or the two trading-desk crons.

To clone **today’s observed Helsinki trading-desk** onto a **different cloud
provider** (secret copy matrix by key name and dest path, legacy scripts,
systemd + webhook drop-in, `CRON_TZ=America/Los_Angeles` crons, Grok
routine webhook, validation, cutover): follow
[REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md). Merging that runbook
is still not a deployment.

## Hard rules

These are also comments in `scripts/install_helsinki.sh`. Do not weaken them.

| Rule | Meaning |
| --- | --- |
| No secrets in git | Tokens live only as operator-placed **0600** files under `/etc/trading-desk/` (and, on the observed host, `/opt/trading-desk/.env`). Never commit them. The installer never prints or requires tokens. |
| WebSocket never places orders | Finnhub/UW/Tradier WS ticks are not an order path. |
| Finnhub ≠ option NBBO | Do not gate option limit prices on Finnhub ticks. |
| ≥20% cash / max deploy 80% | Overnight long options are allowed. **12:30 PT** is a **new-entry cutoff only**, not a forced flatten. |
| Sandbox ≠ live fill evidence | Tradier production NBBO is pricing truth. |
| Default remains `signals_only` | The installer never sets `GROKTRADING_LIVE_EXPLICITLY_ENABLED`. `--start` still does not place orders. |

## What the installer does and does not do

Canonical script: [`scripts/install_helsinki.sh`](../scripts/install_helsinki.sh)
(wrapper: [`deploy/install.sh`](../deploy/install.sh)).

**Does**

- Require root/sudo (fail closed). `--help` and `--dry-run` do not need root.
- Default `INSTALL_ROOT=/opt/groktrading` (distinct from legacy `/opt/trading-desk`).
- Create `/etc/trading-desk` (0700) if missing; **never overwrite** existing `*.env`.
- Create system user `tradingdesk`, `/var/lib/trading-desk`, and a venv.
- `pip install -e ".[ws]"` from this package (`pyproject.toml`).
- Install **package-named** units `groktrading-finnhub.service` and
  `groktrading-tape.service` plus a webhook drop-in on the tape unit.
- `systemctl daemon-reload`.

**Does not** (unless the operator passes an explicit flag)

- `systemctl enable` — requires `--enable`.
- `systemctl start` — requires `--start`.
- Replace live `trading-desk-*.service` — requires `--adopt-legacy-names`
  (and `--force-units` to overwrite files; `--i-mean-cutover` to enable/start
  when those legacy units already exist).
- Write into `/opt/trading-desk` — requires `--allow-legacy-root`. Even then
  the copy is **not** `--delete`, so dest-only loose scripts (`ws_tape.py`,
  `tape_poller.py`, `finnhub_adapter.py`, `nightly_print_bt.py`) stay.
- Copy filled secrets, enable live mode, place orders, or restart remote hosts.

**Package vs legacy tape**

The package exposes `groktrading-finnhub-tape` and `groktrading-tape`.
`groktrading-tape` writes a **signals-only skeleton** JSON
(`/var/lib/trading-desk/package_tape_skeleton.json`). It is **not** a port of
legacy `/opt/trading-desk/ws_tape.py`. Wiring UW + Tradier into a live tape
and merging Finnhub ticks into that tape remain **separate operator steps**.

---

## A. Brand-new Ubuntu-like VPS

Placeholder secrets are enough to finish this path. Do not invent host IPs.

1. Install OS packages:

   ```bash
   sudo apt-get update
   sudo apt-get install -y git python3 python3-venv python3-pip rsync sudo
   ```

2. Clone a **tag or commit** of this repo to the package root (not the legacy path):

   ```bash
   sudo git clone https://github.com/darrylsj/groktrading.git /opt/groktrading
   cd /opt/groktrading
   sudo git checkout --detach <tag-or-commit>
   ```

3. Preview, then install files only (no enable, no start):

   ```bash
   sudo ./scripts/install_helsinki.sh --dry-run
   sudo ./scripts/install_helsinki.sh
   ```

4. Place **0600** env files from examples. Skip any dest that already exists.
   Fill `YOUR_*` placeholders in place. Never commit the filled files.

   ```bash
   sudo install -o root -g root -m 0600 deploy/examples/env/finnhub.env.example /etc/trading-desk/finnhub.env
   sudo install -o root -g root -m 0600 deploy/examples/env/grok-webhook.env.example /etc/trading-desk/grok-webhook.env
   sudo install -o root -g root -m 0600 deploy/examples/env/unusual-whales.env.example /etc/trading-desk/unusual-whales.env
   sudo install -o root -g root -m 0600 deploy/examples/env/tradier-sandbox.env.example /etc/trading-desk/tradier-sandbox.env
   sudo install -o root -g root -m 0600 deploy/examples/env/tradier-live.env.example /etc/trading-desk/tradier-live.env
   sudo install -o root -g root -m 0600 deploy/examples/env/groktrading.env.example /etc/trading-desk/groktrading.env
   ```

   Keep `GROKTRADING_MODE=signals_only` and
   `GROKTRADING_LIVE_EXPLICITLY_ENABLED=false`.

5. Optional: enable (does not start), then start (still no orders):

   ```bash
   sudo ./scripts/install_helsinki.sh --enable
   sudo ./scripts/install_helsinki.sh --start
   ```

6. Check units and skeleton output. This is **not** live fill evidence.

   ```bash
   systemctl status groktrading-finnhub.service groktrading-tape.service
   journalctl -u groktrading-finnhub.service -u groktrading-tape.service -n 50 --no-pager
   ```

Nightly cron and the observed loose scripts are **not** installed here.

---

## B. Parallel install next to legacy Helsinki (no cutover)

Goal: this package lives beside `/opt/trading-desk` without taking traffic.

1. Clone or checkout this repo to **`/opt/groktrading`**. Do **not** set
   `INSTALL_ROOT=/opt/trading-desk`. Do **not** pass `--allow-legacy-root`.
2. Run `sudo ./scripts/install_helsinki.sh` with **no** `--adopt-legacy-names`,
   **no** `--enable`, **no** `--start` unless you want only the new
   `groktrading-*` units (they do not replace `trading-desk-*`).
3. `/etc/trading-desk` already exists on the observed host. The installer
   leaves every existing `*.env` untouched and does not print their contents.
4. Leave `trading-desk-tape.service` and `trading-desk-finnhub.service` running.
   Do not restart them from a cloud agent.
5. Compare package output under `/var/lib/trading-desk/` with the observed
   loose JSON under `/opt/trading-desk/` (`live_tape.json`, `finnhub_tape.json`).
   Do not overwrite those live files.
6. Integrating Finnhub tape into the existing Tradier/UW tape remains an
   **explicit remaining deployment step** ([OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md)).

---

## C. Cutover checklist (explicit operator action only)

Nothing below is performed by the installer default, by a merge, or by a
cloud agent. Do this only when the parallel install is healthy and you
intend to switch the host.

1. Confirm `/opt/groktrading` is the intended tag/commit and
   `groktrading-*` units are installed.
2. Confirm env files under `/etc/trading-desk/` are root-owned **0600** and
   still not in git.
3. Stop **legacy** units yourself:

   ```bash
   sudo systemctl stop trading-desk-tape.service trading-desk-finnhub.service
   sudo systemctl disable trading-desk-tape.service trading-desk-finnhub.service
   ```

4. Choose **one** cutover style:

   **Prefer package names** (safer; live unit files stay on disk unused):

   ```bash
   sudo ./scripts/install_helsinki.sh --enable --start
   ```

   **Adopt legacy names** (replaces `trading-desk-*.service` content — extra
   flags required because those units already exist on Helsinki):

   ```bash
   sudo ./scripts/install_helsinki.sh \
     --adopt-legacy-names --force-units --i-mean-cutover --enable --start
   ```

   Read that command twice. `--i-mean-cutover` exists so enable/start of
   pre-existing `trading-desk-*` names cannot happen by accident.

5. Point anything that still expects `/opt/trading-desk/ws_tape.py` at the
   new process **only after** you have an operator-owned tape equivalent.
   The package skeleton is not that equivalent.
6. Keep `GROKTRADING_MODE=signals_only` unless you are separately and
   explicitly enabling paper or live **outside** this installer.
7. Record the cutover in [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md) and
   [CHANGELOG.md](../CHANGELOG.md) as an **operator** note. Until that
   happens, this repo still does not claim the live host runs this commit.

---

## Rebuild the existing Helsinki host later

Same as **B** then **C**. Treat `/opt/trading-desk` as the live tree until
cutover. Use `/opt/groktrading` as the rebuild target. If you ever must
install **into** `/opt/trading-desk`:

```bash
sudo INSTALL_ROOT=/opt/trading-desk ./scripts/install_helsinki.sh --allow-legacy-root
```

That still will not delete dest-only loose scripts and still will not
replace `trading-desk-*.service` unless you also pass the adopt / force /
cutover flags above.

## Related

- Different-provider full rebuild: [REBUILD_NEW_PROVIDER.md](REBUILD_NEW_PROVIDER.md)
- Examples: [deploy/examples](../deploy/examples)
- Permissions: [deploy/examples/PERMISSIONS.md](../deploy/examples/PERMISSIONS.md)
- Operating model: [OPERATING_MODEL.md](OPERATING_MODEL.md)
- Safety: [SAFETY.md](SAFETY.md)
