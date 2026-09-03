"""Atomic JSON writes with redaction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from groktrading.redaction import redact_mapping


def write_json_atomic(path: Path, payload: Any, *, redact: bool = True) -> None:
    """Write JSON via a sibling temp file and os.replace.

    The on-disk document is redacted by default so a leaked tape file does not
    contain tokens or webhook secrets.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = redact_mapping(payload) if redact else payload
    tmp = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(document, indent=2, sort_keys=True, default=str)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
