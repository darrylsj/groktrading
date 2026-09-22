# Deployed vs HEAD drift

Read-only check for the daily Aria source audit and for an operator. It does not SSH to Helsinki, does not deploy, does not restart units, and does not read env files or tokens.

Aria’s **2026-09-21** audit (`docs/ARIA_SOURCE_AUDIT_20260921.md`) reads GitHub HEAD. A hot-patch on the box that never landed in git can still drift (the V14 lesson). [OBSERVED_DEPLOYMENT.md](OBSERVED_DEPLOYMENT.md) records that `/opt/trading-desk` had **no** `.git` on the 2026-09-05 map. This repository does not claim the live host runs HEAD.

## Local fingerprint

From a checkout of this repo:

```bash
python scripts/deployed_head_drift.py
```

That prints `git rev-parse HEAD` (40 hex characters) and the host locations below. Exit 0. With no deployed SHA, the line is `comparison=skipped_no_deployed_fingerprint`. That is an incomplete check, not a match.

## Where Helsinki should expose its running revision

No running-revision file exists in this repo, and the observed host map does not list one. Do not invent a secret or a hostname to fill the gap. Use one of these operator-owned fingerprints:

1. **Package tree.** Default install root is `/opt/groktrading` (`INSTALL_ROOT` in `scripts/install_helsinki.sh`, [DEPLOY.md](DEPLOY.md)). On the host, when that checkout is what is running:

   ```bash
   git -C /opt/groktrading rev-parse HEAD
   ```

   The helper prints that command as `expected_package_command`. It does not run it over the network.

2. **Legacy live tree.** `/opt/trading-desk` has no `.git` in the observed map. Expected artifact, written by an operator on the host, one line, full git SHA, nothing else:

   `/opt/trading-desk/state/running_revision`

   The helper prints that path as `expected_legacy_revision_file` and `expected_legacy_revision_file_in_repo=false`. This script does not create the file.

Copy the single SHA off the host by whatever operator channel you already use, then compare locally. Do not paste tokens, account ids, or env files into the artifact.

## Compare

```bash
python scripts/deployed_head_drift.py --deployed-sha <40-hex>
python scripts/deployed_head_drift.py --deployed-file /path/to/local-copy-of-running_revision
```

| Result | Exit | Meaning |
| --- | --- | --- |
| `comparison=match` | 0 | Deployed SHA equals this checkout’s HEAD |
| `comparison=drift` | 2 | Both SHAs are present and differ |
| `comparison=skipped_no_deployed_fingerprint` | 0 | HEAD was printed; no deployed SHA was supplied |
| `error=malformed_deployed_revision` | 1 | File or argument was not a single 40-character hex SHA (contents are not echoed) |
| `error=git_rev_parse_failed` | 1 | `git rev-parse HEAD` failed in `--repo` (default: current directory) |

Pass only one of `--deployed-sha` or `--deployed-file`.

Optional content fingerprint for one path that exists in git (local only):

```bash
git show HEAD:src/groktrading/gate.py | sha256sum
```

Compare that digest to `sha256sum` of the same relative path on the host. Legacy `/opt/trading-desk/ws_tape.py` is hand-built and is not that package file.

## Daily Aria checklist

- [ ] Record `git rev-parse HEAD` from the checkout under audit (`python scripts/deployed_head_drift.py`).
- [ ] Obtain the host fingerprint out of band (package `git -C /opt/groktrading rev-parse HEAD`, or the one-line file `/opt/trading-desk/state/running_revision`). Do not SSH from this repo.
- [ ] Pass it as `--deployed-sha` or `--deployed-file`.
- [ ] `match`: cite the SHA in the audit. `drift`: flag deployed-vs-HEAD drift. `skipped_no_deployed_fingerprint`: flag the check as not run.
- [ ] Leave live trading, env files, and host units unchanged. This helper does not deploy.
