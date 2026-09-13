# GEX 60-minute paired scorer (shadow)

Shadow research tool. **`live_gate=false` always.** Never invents marks. Never
places orders. Not a live strategy gate.

## What it scores

Given scorecard / candidate records that already have:

- decision-time **ask**
- a GEX tag: `agree` / `fight` / `na`
- an optional later **bid** mark at about 60 minutes (or `--horizon-min 60`)

it computes one-lot ask→bid dollars `(bid − ask) × 100` for:

- **baseline** — every unique OCC that has both ask and mark
- **agree-only** — the `gex=agree` subset of that scored set

Missing marks are **unscored**. Coverage is reported. OCC is **deduplicated**
(first record wins). Records with `invented: true` are dropped, not filled in.

```bash
PYTHONPATH=src:. python -m tools.gex_shadow \
  --input tests/fixtures/gex_shadow/pair_fixture.jsonl \
  --horizon-min 60
```

The fixture file is **synthetic**, labeled `invented: false` and `fixture: true`.
It is not live NBBO and not a fill.

## Kill criteria

- **Becomes a live gate → kill.** This scorer must stay shadow. Wiring GEX
  agree/fight into `evaluate_gate` / `live_order_gate` / Helsinki submit is a
  kill, not a promotion.
- **Fails to beat baseline hit-rate and one-lot $ after 2–4 weeks → drop.**
  If the agree-only subset does not beat the baseline set on both hit-rate and
  summed one-lot ask→bid dollars over a 2–4 week scored sample with honest
  coverage, delete the experiment. Do not keep a dead tag.

Helsinki / box may already have a partial GEX dump. Align those records to this
schema (`decision_ask`, `gex`, `mark_bid`, `invented: false`) before scoring.
Do not invent a mark to raise coverage.
