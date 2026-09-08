# Opening15 decision protocol

Pre-registered paper-only stop/go rule for the first-15-minute experiment. This document
is the operator-facing encoding of the rule implemented by
`python -m groktrading.research.cli protocol` (also
`python -m groktrading.research.cycle_cli protocol`).

**Not financial advice. Not a live-trading entitlement.**

## Isolation from the live desk

This protocol **reads `evaluation.json` only**. It has:

- no import path into `gate.py`, `order_fsm.py`, `quote_gate.py`, or `executor.py`
- no Helsinki unit, systemd, or installer side effect
- no broker preview, submit, cancel, or modify
- no write into the live tape, webhook, or Grok approve/skip loop

Baselines are computed inside `evaluate()` on the **same frozen packet** and the **same
15:55 ET exit** as the model arm. They are additive (`evaluation.json["baselines"]`).
Existing evaluate keys stay byte-identical. The protocol never changes a packet, a
decision, or a live Candidate.

## Five sessions, then act

Collect **five scoreable paper sessions**, then apply the rule once.

A session is scoreable when `evaluation.json` is paper-only, **`synthetic` is
explicitly `false`**, includes the `baselines` block, and
`selected_net_before_api_and_infra_usd` is not null (zero-trade days count;
missing exits do not).

**Input gates (before kill/continue):**

1. **Distinct real sessions** — five different `session` dates and five different
   `packet_hash` values. Five copies of one day (or one synthetic demo supplied
   five times) are **`rejected`**, not a five-session block.
2. **Not synthetic** — any `synthetic: true` evaluation → **`rejected`**. Demo /
   fixture packets cannot produce kill or continue.
3. **Complete, consistent experiment identity** — `experiment_id`,
   `requested_model`, `recommend_backend`, and `prompt_version` are **required**.
   Missing values are **`rejected`** (they must not compare equal). Universe
   (`packet_printed` vs `hygiene_shortlist`), hygiene/cost config, and random-K
   `seed` / `draws` / predeclared fixed-K arms must match. Tuesday packet-only
   baseline must not pool with expanded select.
4. **Sufficient baselines** — kill/continue require **five known policy
   percentiles** and **five mechanical nets**. Same-K random-K percentile is used
   when the model entered (K>0). On abstain days (K=0) the predeclared fixed-K=1
   arm scores always-flat vs random-1 so zero-trade days remain scoreable. A
   missing policy percentile or mechanical mark is **`insufficient`**, not continue.

Fewer than five scoreable sessions, or five sessions with incomplete baselines →
**`insufficient`**. Do not kill, continue, or go live. Keep collecting paper
sessions. Duplicate or synthetic inputs are **`rejected`** — do not treat them as
progress.

The CLI reads **at most five** paths, in the order given. Do not cherry-pick after
seeing outcomes.

```bash
python -m groktrading.research.cli protocol \
  --sessions research-runs/s1 research-runs/s2 research-runs/s3 \
             research-runs/s4 research-runs/s5 \
  --output research-runs/protocol-verdict
```

## Verdicts

| Verdict | Meaning | What to do |
| --- | --- | --- |
| `insufficient` | Fewer than five scoreable paper sessions, or five sessions without a full set of known policy percentiles (same-K or fixed-K=1 on abstain) and mechanical nets | Collect more complete paper sessions. Do not act. |
| `rejected` | Duplicate sessions, synthetic evaluations, missing identity, or mixed experiment identity (including Tue packet baseline mixed with expanded select) | Do not kill or continue. Supply five distinct real paper sessions from the same experiment. |
| `kill` | Pre-registered stop rule matched | Stop this selector arm. Do **not** go live. Archive and review. |
| `continue` | Pre-registered paper-progress rule matched | More **paper** sessions and/or a **wider paper universe** only. Never live. Never `--allow-degraded` as a live claim. |
| `inconclusive` | Five complete scoreable sessions, neither kill nor continue | Stay paper-only. Do not treat mixed results as an edge. |

### Kill (any)

Registered constants live in `src/groktrading/research/protocol.py`:

1. Model five-session total net `< 0` **and** mean random-K percentile `< 40`
2. Model net `<` mechanical top-K-by-ask-side-premium net on **≥ 4 of 5** sessions
3. Model random-K percentile `< 50` on **≥ 4 of 5** sessions **and** model total `≤ 0`

### Continue (all, and not kill)

1. Five distinct real (non-synthetic) scoreable sessions with consistent experiment identity
2. Five known policy percentiles (same-K when K>0; fixed-K=1 when K=0) and five mechanical nets
3. Mean policy percentile `≥ 60`
4. Model five-session total net `>` mechanical five-session total
5. Model five-session total net `> 0`

**`continue` never means live.** It never means enable systemd, restart Helsinki, widen
the live universe, or feed Opening15 picks into the gate. It means: run more paper
`research.cli run` sessions, or paper-test a wider symbol list, then apply this same
rule again on a newly registered block.

### Inconclusive

Five complete scoreable sessions exist but neither rule matched (wide intervals,
mixed days). Incomplete mechanical or random-K marks are **`insufficient`**, not
inconclusive. Keep paper-only. Publish the uncertainty. Do not go live.

## Baselines on every `evaluation.json`

Computed on the same frozen packet and same 15:55 ET ask-in/bid-out marks:

| Arm | Definition |
| --- | --- |
| Random-K (same-K) | 1,000 seeded draws of K declared-universe contracts (K = model enter count). Seed material is `20260908` plus `packet_hash`. Mechanical 300s / uncapped entry. Model net as a percentile rank of complete draws. Null when K=0; incomplete draws are reported and not treated as zeros. |
| Mechanical top-K | Highest UW-tagged **ask-side** premium sums; same 15:55 ET exit. Side is never inferred from price vs NBBO. |
| Abstain / always-flat | Zero enters; net `0`. Policy scorecard compares the model's enter-or-abstain net to this arm. |
| Fixed-K (1, 2, 3) | Predeclared comparison arms on the same universe and exit so abstain days remain scoreable. Fixed-K=1 `percentile_of_zero` is the policy percentile when K=0. |
| Latency | Decision receipt minus packet `knowledge_cutoff`; each fill's entry minus decision receipt |

These arms measure added value. They do not constrain the discretionary selector.

## Tuesday posture

Tuesday 2026-09-08 is an **operational paper pilot on the clean baseline**:

```bash
python -m groktrading.research.cli run --session 2026-09-08 --output research-runs/2026-09-08
```

That command is **not** `--allow-degraded` and is **not** a claim of full expanded-strategy
readiness. Passing unit tests is not live entitlement proof. Schwab is still unconnected.
The dedicated earnings calendar is still print-fields only. UW economic calendar,
dark pool, screener, and market tide are expanded Opening15 LLM context only
(Finnhub `/calendar/economic` still 403 on this plan). **Post-Tue paper days**
(session 2+ / Wed 2026-09-09 onward) **default to expanded select** after a
logged pre-LLM hygiene shortlist (`candidates.json`; gates then judgment). Fall
back to baseline or explicit `--allow-degraded` only if required coverage is
incomplete. Tuesday stays packet baseline (`research.cli run`). **selector_v3**
is a shadow prompt only (optional `cycle_cli select --shadow-v3 --registry`);
it is not Tuesday's selector and is not the active registry version. Post-Tue
expanded select still defaults to active **selector_v2** plus the hygiene
shortlist. See [TUESDAY_EXECUTION_READINESS.md](TUESDAY_EXECUTION_READINESS.md).
