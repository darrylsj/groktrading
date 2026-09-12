#!/usr/bin/env python3
"""Thin ranker CLI (plane 2). Offline-safe. Never emits sit_match.

Writes schema-stable shortlist.json (≤1–3 OCCs) for Continual15 to pull.
Host path (ops documentation, not auto-deploy):
  /opt/trading-desk/state/shortlist.json

Never places orders. Never prints tokens. emit_sit_match=False.
"""

from __future__ import annotations

from groktrading.shortlist import main

if __name__ == "__main__":
    raise SystemExit(main())
