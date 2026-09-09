"""Import repo scripts/ modules from tests without installing them as a package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scan_secrets = load("scan_secrets", "scripts/scan_secrets.py")
box_cold_rotate_script = load("box_cold_rotate_script", "scripts/box_cold_rotate.py")
