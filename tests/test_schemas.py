from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "schemas"


def test_schemas_are_json_objects() -> None:
    files = list(ROOT.glob("*.json"))
    assert files, "expected JSON schemas"
    for path in files:
        data = json.loads(path.read_text())
        assert data.get("title")
        assert data.get("type") == "object"
