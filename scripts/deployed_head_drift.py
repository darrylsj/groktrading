#!/usr/bin/env python3
"""Compare local git HEAD to an operator-supplied deployed revision.

Read-only. Does not SSH, does not deploy, does not read env files, and does
not print file contents that fail the SHA check.

The 2026-09-05 host map (docs/OBSERVED_DEPLOYMENT.md) records no ``.git``
under ``/opt/trading-desk``. This repo does not ship a running-revision
file. The legacy path below is the expected one-line artifact an operator
may publish later. Until that fingerprint is passed in, the result is
``comparison=skipped_no_deployed_fingerprint``, which is not a match.

See docs/DEPLOYED_HEAD_DRIFT.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Default package install root (scripts/install_helsinki.sh, docs/DEPLOY.md).
PACKAGE_INSTALL_ROOT = "/opt/groktrading"
# Expected legacy artifact. Not observed on the host map and not created here.
LEGACY_RUNNING_REVISION = "/opt/trading-desk/state/running_revision"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def normalize_sha(value: str) -> str:
    """Return a full git SHA, or raise ValueError without echoing the input."""
    text = value.strip().lower()
    if not _FULL_SHA.fullmatch(text):
        raise ValueError("revision must be a 40-character hex git sha")
    return text


def read_deployed_file(path: Path) -> str:
    """Read a one-line SHA file. Reject anything else without printing it."""
    raw = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("revision file must be a single 40-character hex sha")
    return normalize_sha(lines[0])


def git_head(repo: Path) -> str:
    """``git rev-parse HEAD`` for ``repo``. Stderr from git is not returned."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("git rev-parse HEAD failed")
    return normalize_sha(completed.stdout)


def comparison(head: str, deployed: str) -> str:
    if normalize_sha(head) == normalize_sha(deployed):
        return "match"
    return "drift"


def _print_expectations() -> None:
    print(f"expected_package_command=git -C {PACKAGE_INSTALL_ROOT} rev-parse HEAD")
    print(f"expected_legacy_revision_file={LEGACY_RUNNING_REVISION}")
    print("expected_legacy_revision_file_in_repo=false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print git rev-parse HEAD and optionally compare an operator-supplied "
            "deployed SHA. Does not SSH or deploy."
        )
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Checkout to read (default: current directory).",
    )
    parser.add_argument(
        "--deployed-sha",
        default=None,
        help="40-character hex SHA observed on the host. Do not pass secrets.",
    )
    parser.add_argument(
        "--deployed-file",
        type=Path,
        default=None,
        help=(
            "Local copy of the one-line revision artifact "
            f"(expected host path {LEGACY_RUNNING_REVISION})."
        ),
    )
    args = parser.parse_args(argv)
    if args.deployed_sha is not None and args.deployed_file is not None:
        print("error=pass_only_one_deployed_source", file=sys.stderr)
        return 1
    try:
        head = git_head(args.repo)
    except (RuntimeError, ValueError):
        print("error=git_rev_parse_failed", file=sys.stderr)
        return 1
    print(f"head={head}")
    _print_expectations()
    if args.deployed_sha is None and args.deployed_file is None:
        print("comparison=skipped_no_deployed_fingerprint")
        return 0
    try:
        if args.deployed_sha is not None:
            deployed = normalize_sha(args.deployed_sha)
        else:
            deployed = read_deployed_file(args.deployed_file)
    except (OSError, ValueError):
        print("error=malformed_deployed_revision", file=sys.stderr)
        return 1
    print(f"deployed={deployed}")
    result = comparison(head, deployed)
    print(f"comparison={result}")
    return 0 if result == "match" else 2


if __name__ == "__main__":
    raise SystemExit(main())
