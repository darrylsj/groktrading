# Box Trading Desk Archive (cold rotate)

Helsinki keeps a **hot** append-only research ledger on limited disk
(**7–14 days**). Closed day packs older than that window rotate to **Box
Trading Desk Archive**. The archive holds research artifacts only — **no
secrets**.

This repo ships a **plan + deny-list + delete guard**. Upload uses Box CLI
when the operator has it. CI never calls Box or Tradier.

Related: [DEPLOY.md](DEPLOY.md), [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md),
package `groktrading.box_rotate` / `groktrading.retention`, scripts
`scripts/box_cold_rotate.py` and `scripts/hot_ledger_retain.py`.

## Layout

Local hot tree (example):

```
/var/lib/trading-desk/ledger/
  uw_flow.sqlite          # live hot SQLite (not a closed pack)
  flow-2026-09-01.sqlite  # closed day pack (name or folder YYYY-MM-DD)
  2026-09-01/tape.json
```

Box destination:

```
daily/YYYY-MM-DD/<relative-or-basename>
```

A pack is **closed** when its PT session date is strictly before today. It is
**eligible** when it is closed **and** `pack_date <= today − keep_hot_days`.

`keep_hot_days` must be **7–14** inclusive (default **7**). Outside that
window the helper fail-closes.

## Never upload

Deny-list (path filter; unit-tested; case-insensitive):

- `.env` and `.env*` (including `.ENV`, `.env.staging`)
- `*.pem` / `*.key` / `*.p12` / `*.pfx`
- names containing `token`, `secret`, `credential`, `password`, `api_key`, …
- path segments `.ssh`, `secrets`, `credentials`
- `schwab_token.json`
- **symlinks** (including a symlink whose name looks like a pack)
- resolved paths **outside** the archive root
- anything that is not a controlled export (``.sqlite`` / ``.json`` / ``.jsonl``)

Tokens stay in root-owned **0600** env files on the host. They are not Box
objects.

## Delete guard

Local delete of an eligible pack is **fail-closed** unless:

1. the operator asserts a verified Box upload (`--verified`), **or**
2. the operator passes **`--confirm-delete`** (explicit override when Box CLI
   is absent or upload was verified out of band).

`--dry-run` prints the plan and deletes nothing.

```bash
python scripts/box_cold_rotate.py \
  --src /var/lib/trading-desk/ledger \
  --keep-hot-days 7 \
  --dry-run

# After a verified Box upload (operator read-after-write):
python scripts/box_cold_rotate.py \
  --src /var/lib/trading-desk/ledger \
  --keep-hot-days 7 \
  --box-parent-id YOUR_BOX_FOLDER_ID \
  --verified \
  --delete
```

Box CLI (optional, serial — do not parallelize): `box files:upload`.
Auth check: `box users:get me --json`. Do not use
`box configure:environments:get --current` (can print environment secrets).

## Hot window retain (7–14 days)

After a **verified** Box upload of the closed day pack, purge the live hot
SQLite (`uw_flow.sqlite`) and bound companion material JSONL:

```bash
python scripts/hot_ledger_retain.py \
  --ledger /var/lib/trading-desk/ledger/uw_flow.sqlite \
  --state-dir /var/lib/trading-desk/state \
  --keep-hot-days 7 \
  --dry-run --verified

# After the operator confirms the Box pack is present:
python scripts/hot_ledger_retain.py \
  --ledger /var/lib/trading-desk/ledger/uw_flow.sqlite \
  --state-dir /var/lib/trading-desk/state \
  --keep-hot-days 7 \
  --verified
```

Purge is fail-closed without `--verified` or `--confirm`. Example systemd
timer / cron live under `deploy/examples/systemd/hot-retention/` and
`deploy/examples/cron/hot-retain.cron`. **Do not enable them from this
repo or a cloud agent.**

Merging this repo does **not** run rotate or retain on Helsinki. Operator SSH only.
