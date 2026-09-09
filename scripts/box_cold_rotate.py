#!/usr/bin/env python3
"""Rotate closed Helsinki day packs to Box Trading Desk Archive.

Never uploads ``.env``, tokens, or credentials. Delete is fail-closed until
Box upload is verified or the operator passes ``--confirm-delete``.

Box CLI is optional. CI tests the deny-list / plan only (no network).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from groktrading.box_rotate import (
    BoxRotateError,
    RotatePlan,
    assert_can_delete,
    keep_hot_days,
    plan_rotate,
)
from groktrading.timeutil import UTC


def _box_cli_present() -> bool:
    return shutil.which("box") is not None


def _run_box(args: list[str], *, dry_run: bool) -> int:
    """One Box CLI invocation. Never prints tokens. Serial — do not parallelize."""
    cmd = ["box", *args]
    if dry_run:
        print(f"dry-run: {' '.join(cmd)}")
        return 0
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _plan_document(plan: RotatePlan) -> dict[str, object]:
    return {
        "keep_hot_days": plan.keep_hot_days,
        "today": plan.today.isoformat(),
        "cutoff": plan.cutoff.isoformat(),
        "box_cli_present": plan.box_cli_present,
        "verified": plan.verified,
        "confirm_delete": plan.confirm_delete,
        "can_delete": plan.can_delete(),
        "uploadable": [
            {"src": str(i.src), "box_relpath": i.box_relpath, "pack_date": i.pack_date.isoformat()}
            for i in plan.uploadable
        ],
        "denied": [
            {"src": str(i.src), "reason": i.deny_reason}
            for i in plan.denied_items
        ],
        "note": (
            "Box Trading Desk Archive. No secrets. "
            "WebSocket never places orders. Grok Bot decides."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plan / upload closed ledger day packs to Box daily/YYYY-MM-DD/. "
            "Never uploads .env or credentials. Never places orders."
        )
    )
    parser.add_argument(
        "--src",
        required=True,
        help="Hot ledger / day-pack directory (no .env files).",
    )
    parser.add_argument(
        "--keep-hot-days",
        default=None,
        help="7–14 inclusive (default 7).",
    )
    parser.add_argument(
        "--box-parent-id",
        default="",
        help="Box folder id for Trading Desk Archive (not a secret; still YOUR_* in git).",
    )
    parser.add_argument(
        "--verified",
        action="store_true",
        help="Operator asserts Box upload was verified (read-after-write).",
    )
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="Allow local delete without a verified Box upload (explicit).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete eligible local files after the delete guard passes.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write the redacted plan JSON.",
    )
    args = parser.parse_args(argv)

    try:
        window = keep_hot_days(args.keep_hot_days)
    except BoxRotateError as exc:
        print(f"box_cold_rotate: fail-closed: {exc}", file=sys.stderr)
        return 2

    root = Path(args.src)
    if not root.is_dir():
        print(f"box_cold_rotate: src is not a directory: {root}", file=sys.stderr)
        return 2

    now = datetime.now(tz=UTC)
    plan = plan_rotate(
        root,
        now=now,
        keep_days=window,
        box_cli_present=_box_cli_present(),
        verified=bool(args.verified),
        confirm_delete=bool(args.confirm_delete),
    )
    doc = _plan_document(plan)
    print(json.dumps(doc, indent=2, sort_keys=True))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.dry_run:
        return 0

    if plan.uploadable and args.box_parent_id and plan.box_cli_present:
        # Upload is operator-owned. We only invoke `box files:upload` per file.
        # Destination name is the daily/ relpath basename; folder layout is
        # documented in docs/BOX_ARCHIVE.md (CLI folder create is serial).
        for item in plan.uploadable:
            rc = _run_box(
                [
                    "files:upload",
                    str(item.src),
                    "--parent-id",
                    args.box_parent_id,
                    "--name",
                    Path(item.box_relpath).name,
                ],
                dry_run=False,
            )
            if rc != 0:
                print("box_cold_rotate: upload failed; refuse delete", file=sys.stderr)
                return rc

    if args.delete:
        try:
            assert_can_delete(plan)
        except BoxRotateError as exc:
            print(f"box_cold_rotate: fail-closed: {exc}", file=sys.stderr)
            return 2
        for item in plan.uploadable:
            item.src.unlink(missing_ok=True)
        print(f"box_cold_rotate: deleted {len(plan.uploadable)} local pack file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
