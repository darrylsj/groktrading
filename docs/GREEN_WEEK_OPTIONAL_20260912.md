# Green-week optional tools (2026-09-12)

Weekend Codex review add-ons. **Optional / shadow.** They do **not** change
live strategy gates (cash floor, 12:30 PT new-entry cutoff, no auto-flatten,
credit/STO **dated hold** through Tue 2026-09-15 RTH — see
[STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md)). Helsinki **shortlist deploy is operator-side** — merge ≠
Helsinki restart; copy/wire the ranker only after an authorized host step.

## 1. Overnight carry fields on `live_order_gate` thesis

In-repo SoT: [`tools/live_order_gate`](../tools/live_order_gate). Schema and
CLI: [LIVE_ORDER_GATE.md](LIVE_ORDER_GATE.md).

Soft notes on a written thesis (same-day entries may omit them):

| Field | Role |
| --- | --- |
| `overnight_carry` | bool — intending to hold past RTH |
| `carry_dte` | remaining DTE note (string or int) |
| `carry_event_risk` | next catalyst / gap risk |
| `carry_rationale` | why the mechanism survives overnight — **not** "cash floor OK" |

`how_it_dies` / `falsifier` remains **required** on every written thesis.
`--overnight-carry` requires the three carry notes. Stamped onto the thesis
receipt JSON, evidence markdown, and a `thinking.jsonl` row under
`gates/carry`. Does not flatten overnight, does not change the cash floor,
does not allow credits/STO (dated hold; see
[STO_UNLOCK_PLAN.md](STO_UNLOCK_PLAN.md)).

## 2. GEX 60-minute paired scorer (shadow)

[`tools/gex_shadow`](../tools/gex_shadow) — `score_gex_pair.py`. Reads
scorecard / candidate records that already have a decision-time ask, a GEX
tag (`agree` / `fight` / `na`), and a later bid mark (~60 minutes or
`--horizon-min 60`). One-lot ask→bid $ for baseline vs agree-only. Missing
marks = unscored (coverage reported). Deduplicate OCC. **Never invent
marks.** `live_gate=false` always.

Kill criteria (also in the tool README): becomes a live gate → kill; fails
to beat baseline hit-rate and one-lot $ after 2–4 weeks → drop.

If the box pack already has a partial GEX dump, align it to this repo schema
before scoring. Do not invent marks to raise coverage.
