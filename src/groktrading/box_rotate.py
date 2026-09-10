"""Box Trading Desk Archive cold-rotate contract.

Hot Helsinki disk holds a short ledger window (7–14 days). Closed day packs
older than that window go to Box under ``daily/YYYY-MM-DD/…``. Secrets never
leave the host: ``.env``, tokens, credentials, and key material are denied.

This module plans and filters. Upload uses Box CLI when present. Delete is
fail-closed until the upload is verified **or** the operator passes
``--confirm-delete``. No Box network in unit tests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from groktrading.timeutil import as_pt

DEFAULT_KEEP_HOT_DAYS = 7
MIN_KEEP_HOT_DAYS = 7
MAX_KEEP_HOT_DAYS = 14
BOX_DAILY_PREFIX = "daily"

# Basenames / suffixes that must never be uploaded (secrets, not research).
DENY_EXACT_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "schwab_token.json",
    }
)
DENY_SUFFIXES = (
    ".env",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".kdbx",
)
DENY_NAME_SUBSTRINGS = (
    "token",
    "secret",
    "credential",
    "passwd",
    "password",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "webhook",
)
# Extra path segments (any ancestor or the file name).
DENY_PATH_PARTS = frozenset({".ssh", "secrets", "credentials"})
# Only these research suffixes may leave the host.
ALLOW_EXPORT_SUFFIXES = (".sqlite", ".json", ".jsonl")

_DATE_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")


class BoxRotateError(ValueError):
    """Fail-closed rotate input (window, delete guard, empty plan)."""


def keep_hot_days(raw: object | None) -> int:
    """Accept 7–14 inclusive. Missing → 7. Invalid → error (fail closed)."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_KEEP_HOT_DAYS
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise BoxRotateError("invalid_keep_hot_days") from exc
    if value < MIN_KEEP_HOT_DAYS or value > MAX_KEEP_HOT_DAYS:
        raise BoxRotateError("keep_hot_days_out_of_window")
    return value


def pack_date_from_path(path: Path) -> date | None:
    """First ``YYYY-MM-DD`` in the path parts or filename, else None."""
    for part in (*path.parts, path.stem):
        match = _DATE_RE.search(part)
        if match is None:
            continue
        try:
            return date(int(match["y"]), int(match["m"]), int(match["d"]))
        except ValueError:
            continue
    return None


def _resolved_outside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


def deny_reason(path: Path, *, root: Path | None = None) -> str | None:
    """Why this path must not be uploaded. None = allowed research artifact.

    Filename checks are case-insensitive (``.ENV``, ``.env.staging``).
    Symlinks and resolved paths outside ``root`` are denied.
    """
    if path.is_symlink():
        return "deny_symlink"
    if root is not None and _resolved_outside_root(path, root):
        return "deny_outside_archive_root"
    name = path.name
    lowered = name.lower()
    deny_exact = {item.lower() for item in DENY_EXACT_NAMES}
    if lowered in deny_exact:
        return "deny_exact_name"
    if lowered.startswith(".env"):
        return "deny_env_file"
    for suffix in DENY_SUFFIXES:
        if lowered.endswith(suffix):
            return f"deny_suffix:{suffix}"
    for part in path.parts:
        if part.lower() in DENY_PATH_PARTS:
            return "deny_path_part"
    for needle in DENY_NAME_SUBSTRINGS:
        if needle in lowered:
            return f"deny_name_substring:{needle}"
    if not any(lowered.endswith(suffix) for suffix in ALLOW_EXPORT_SUFFIXES):
        return "deny_not_controlled_export"
    return None


def is_denied(path: Path, *, root: Path | None = None) -> bool:
    return deny_reason(path, root=root) is not None


def session_date(now: datetime) -> date:
    return as_pt(now).date()


def is_closed_pack(pack_date: date, today: date) -> bool:
    """A pack is closed once its PT session date is strictly before today."""
    return pack_date < today


@dataclass(frozen=True)
class RotateItem:
    src: Path
    pack_date: date
    box_relpath: str
    denied: bool
    deny_reason: str | None
    eligible: bool


@dataclass
class RotatePlan:
    keep_hot_days: int
    today: date
    cutoff: date
    items: list[RotateItem] = field(default_factory=list)
    box_cli_present: bool = False
    verified: bool = False
    confirm_delete: bool = False

    @property
    def uploadable(self) -> list[RotateItem]:
        return [i for i in self.items if i.eligible and not i.denied]

    @property
    def denied_items(self) -> list[RotateItem]:
        return [i for i in self.items if i.denied]

    def can_delete(self) -> bool:
        """Delete only after verified upload or an explicit operator confirm."""
        return self.verified or self.confirm_delete

    def box_destination(self, item: RotateItem) -> str:
        return item.box_relpath


def box_relpath(pack_date: date, src: Path, root: Path) -> str:
    """``daily/YYYY-MM-DD/<relative-or-name>`` — no parent escapes."""
    day = pack_date.isoformat()
    try:
        rel = src.resolve().relative_to(root.resolve())
        tail = Path(*[p for p in rel.parts if p not in {".", ".."}])
    except ValueError:
        tail = Path(src.name)
    if tail == Path("."):
        tail = Path(src.name)
    return f"{BOX_DAILY_PREFIX}/{day}/{tail.as_posix()}"


def plan_rotate(
    root: Path,
    *,
    now: datetime,
    keep_days: int | None = None,
    paths: Sequence[Path] | None = None,
    box_cli_present: bool = False,
    verified: bool = False,
    confirm_delete: bool = False,
) -> RotatePlan:
    """Scan ``root`` (or an explicit path list) for closed, aged, allowed packs."""
    window = DEFAULT_KEEP_HOT_DAYS if keep_days is None else keep_hot_days(keep_days)
    today = session_date(now)
    cutoff = today - timedelta(days=window)
    plan = RotatePlan(
        keep_hot_days=window,
        today=today,
        cutoff=cutoff,
        box_cli_present=box_cli_present,
        verified=verified,
        confirm_delete=confirm_delete,
    )
    candidates = list(paths) if paths is not None else _default_candidates(root)
    for path in candidates:
        if not path.is_symlink() and not path.is_file():
            continue
        reason = deny_reason(path, root=root)
        pack_date = pack_date_from_path(path)
        denied = reason is not None
        eligible = False
        dest = ""
        if pack_date is not None and not denied:
            dest = box_relpath(pack_date, path, root)
            eligible = is_closed_pack(pack_date, today) and pack_date <= cutoff
        plan.items.append(
            RotateItem(
                src=path,
                pack_date=pack_date or date.min,
                box_relpath=dest,
                denied=denied,
                deny_reason=reason,
                eligible=eligible,
            )
        )
    return plan


def assert_can_delete(plan: RotatePlan) -> None:
    if not plan.can_delete():
        raise BoxRotateError("delete_requires_verified_upload_or_confirm_delete")


def _default_candidates(root: Path) -> Iterable[Path]:
    """Files under ``root``. Do not follow symlink directories."""
    if not root.exists():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [name for name in dirnames if not (base / name).is_symlink()]
        for name in filenames:
            found.append(base / name)
    return sorted(found)
