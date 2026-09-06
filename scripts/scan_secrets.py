#!/usr/bin/env python3
"""Fail the build if secret-shaped values appear in the tree.

Scans git-tracked files and the working tree (excluding .git / venvs / caches).
Intended for a public GitHub audit: real API keys, tokens, private keys,
webhook secrets, and live broker account numbers must not ship.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Known live / sandbox identifiers that must not re-enter public docs.
# Split so the contiguous id never appears in the public tree.
_FORBIDDEN_ACCOUNT_IDS = (
    "6YB" + "72238",  # live production — never publish
    "VA756" + "91022",  # sandbox id previously committed; keep redacted
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "pem-header",
        re.compile("-----BEGIN " + r"(RSA |OPENSSH |EC |DSA )?" + "PRIVATE KEY-----"),
    ),
    (
        "openssh-private-key",
        re.compile("-----BEGIN OPENSSH " + "PRIVATE KEY-----"),
    ),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "generic-bearer-assignment",
        re.compile(
            r"""(api[_-]?key|secret|token|password|passwd|authorization)\s*=\s*['\"][A-Za-z0-9_\-/+=]{24,}['\"]""",
            re.I,
        ),
    ),
    ("finnhub-query-token", re.compile(r"token=[A-Za-z0-9]{20,}")),
    ("openai-sk", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    (
        "home-box-secret-path",
        re.compile(r"/home/box/[^\s\"']*(token|secret|key|credential|env)", re.I),
    ),
    (
        "forbidden-account-id",
        re.compile("|".join(re.escape(x) for x in _FORBIDDEN_ACCOUNT_IDS)),
    ),
]

ALLOW_SUBSTRINGS = (
    "unused-test-token",
    "test-secret-not-production",
    "placeholder",
    "YOUR_",
    "changeme",
    "example",
    "[REDACTED]",
    "ACCOUNT_ID_REDACTED",
    "PAPERACCOUNT",
)

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".eggs",
    "dist",
    "build",
    "htmlcov",
}

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".lock", ".pyc", ".woff", ".woff2"}
SKIP_NAMES = {"scan_secrets.py"}


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    try:
        rel_parts = path.resolve().relative_to(ROOT.resolve()).parts
    except ValueError:
        return True
    return any(part in SKIP_DIR_NAMES for part in rel_parts)


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    files = []
    for line in raw.splitlines():
        path = ROOT / line
        if _should_skip(path):
            continue
        if path.is_file():
            files.append(path)
    return files


def working_tree_files() -> list[Path]:
    """Tracked plus untracked working-tree files (never walks .git)."""
    seen: set[Path] = set()
    files: list[Path] = []
    for path in tracked_files():
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            files.append(path)
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path):
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(path)
    return files


def is_allowed_snippet(snippet: str) -> bool:
    return any(allow in snippet for allow in ALLOW_SUBSTRINGS)


def scan_text(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            snippet = match.group(0)
            if is_allowed_snippet(snippet):
                continue
            hits.append((name, snippet[:48]))
    return hits


def main() -> int:
    failures: list[str] = []
    for path in working_tree_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError:
            continue
        for name, snippet in scan_text(text):
            if path.name.endswith(".example"):
                # Env example keys without real values are fine; still block
                # known live account IDs and private-key headers.
                if name not in {"forbidden-account-id", "pem-header", "openssh-private-key"}:
                    continue
            rel = path.relative_to(ROOT)
            failures.append(f"{rel}: {name}: {snippet}")
    if failures:
        print("Secret scanner failed:")
        for row in failures:
            print(f"  {row}")
        return 1
    print("Secret scanner passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
