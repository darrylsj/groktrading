"""Operational retention for the hot ledger and companion JSONL.

Helsinki keeps a 7–14 day hot window on disk. Closed packs rotate to Box
(``box_rotate``). This module is the verified export/purge path for
``uw_flow.sqlite`` and a bound for companion material JSONL growth.

Does not SSH, enable timers, or place orders. Purge is fail-closed until
``verified`` or ``confirm``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from groktrading.box_rotate import BoxRotateError, keep_hot_days
from groktrading.flow_ledger import FlowLedger, FlowLedgerError
from groktrading.timeutil import as_utc

DEFAULT_JSONL_MAX_BYTES = 2_000_000
DEFAULT_JSONL_KEEP_LINES = 2_000
DEFAULT_JSONL_NAMES = (
    "flow_alerts_material.jsonl",
    "flow_alerts.jsonl",
)


class RetentionError(ValueError):
    """Fail-closed retention (window, verify guard, I/O)."""


@dataclass(frozen=True)
class JsonlBoundResult:
    path: Path
    existed: bool
    trimmed: bool
    bytes_before: int
    bytes_after: int
    lines_before: int
    lines_after: int


@dataclass(frozen=True)
class RetainResult:
    keep_hot_days: int
    purged_rows: int
    jsonl: tuple[JsonlBoundResult, ...]
    verified: bool
    confirm: bool
    dry_run: bool


def assert_can_purge(*, verified: bool, confirm: bool) -> None:
    if not (verified or confirm):
        raise RetentionError("purge_requires_verified_or_confirm")


def bound_jsonl(
    path: Path,
    *,
    max_bytes: int = DEFAULT_JSONL_MAX_BYTES,
    keep_lines: int = DEFAULT_JSONL_KEEP_LINES,
    dry_run: bool = False,
) -> JsonlBoundResult:
    """Keep the tail of a JSONL file when it exceeds byte or line bounds."""
    if max_bytes < 1 or keep_lines < 1:
        raise RetentionError("jsonl_bound_must_be_positive")
    if not path.is_file():
        return JsonlBoundResult(
            path=path,
            existed=False,
            trimmed=False,
            bytes_before=0,
            bytes_after=0,
            lines_before=0,
            lines_after=0,
        )
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    bytes_before = len(raw)
    lines_before = len(lines)
    over = bytes_before > max_bytes or lines_before > keep_lines
    if not over:
        return JsonlBoundResult(
            path=path,
            existed=True,
            trimmed=False,
            bytes_before=bytes_before,
            bytes_after=bytes_before,
            lines_before=lines_before,
            lines_after=lines_before,
        )
    kept = lines[-keep_lines:] if lines_before > keep_lines else lines
    out = "".join(kept).encode("utf-8")
    if not dry_run:
        path.write_bytes(out)
    return JsonlBoundResult(
        path=path,
        existed=True,
        trimmed=True,
        bytes_before=bytes_before,
        bytes_after=len(out),
        lines_before=lines_before,
        lines_after=len(kept),
    )


def discover_companion_jsonl(state_dir: Path) -> list[Path]:
    found: list[Path] = []
    if not state_dir.exists():
        return found
    for name in DEFAULT_JSONL_NAMES:
        path = state_dir / name
        if path.is_file() and not path.is_symlink():
            found.append(path)
    return found


def retain_hot_window(
    ledger: FlowLedger,
    *,
    now: datetime,
    keep_days: int | None = None,
    verified: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
    jsonl_paths: list[Path] | None = None,
    jsonl_max_bytes: int = DEFAULT_JSONL_MAX_BYTES,
    jsonl_keep_lines: int = DEFAULT_JSONL_KEEP_LINES,
) -> RetainResult:
    """Purge ledger rows older than the 7–14 day hot window; bound JSONL.

    ``verified`` means the operator already rotated the closed day pack to
    Box (or otherwise exported it). ``confirm`` is an explicit override.
    """
    try:
        window = keep_hot_days(keep_days)
    except BoxRotateError as exc:
        raise RetentionError(str(exc)) from exc
    assert_can_purge(verified=verified, confirm=confirm)
    stamp = as_utc(now)
    purged = 0
    if not dry_run:
        try:
            purged = ledger.purge_older_than(window, now=stamp)
        except FlowLedgerError as exc:
            raise RetentionError(str(exc)) from exc
    jsonl_results = tuple(
        bound_jsonl(
            path,
            max_bytes=jsonl_max_bytes,
            keep_lines=jsonl_keep_lines,
            dry_run=dry_run,
        )
        for path in (jsonl_paths or [])
    )
    return RetainResult(
        keep_hot_days=window,
        purged_rows=purged,
        jsonl=jsonl_results,
        verified=verified,
        confirm=confirm,
        dry_run=dry_run,
    )
