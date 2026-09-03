#!/usr/bin/env python3
"""Fail the build if secret-shaped values appear in tracked files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("pem-header", re.compile(r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "generic-bearer-assignment",
        re.compile(
            r"""(api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9_\-]{24,}['\"]""",
            re.I,
        ),
    ),
    ("finnhub-query-token", re.compile(r"token=[A-Za-z0-9]{20,}")),
]

ALLOW_SUBSTRINGS = (
    "unused-test-token",
    "test-secret-not-production",
    "placeholder",
    "YOUR_",
    "changeme",
    "example",
    "[REDACTED]",
)


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    files = []
    for line in raw.splitlines():
        path = ROOT / line
        if path.suffix in {".png", ".jpg", ".lock"}:
            continue
        if path.name == "scan_secrets.py":
            continue
        files.append(path)
    return files


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                if any(allow in snippet for allow in ALLOW_SUBSTRINGS):
                    continue
                # Env example keys without values are fine.
                if path.name.endswith(".example"):
                    continue
                rel = path.relative_to(ROOT)
                failures.append(f"{rel}: {name}: {snippet[:48]}")
    if failures:
        print("Secret scanner failed:")
        for row in failures:
            print(f"  {row}")
        return 1
    print("Secret scanner passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
