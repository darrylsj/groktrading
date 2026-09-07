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
3. **Consistent experiment identity** — `experiment_id`, `requested_model`,
   `recommend_backend`, `prompt_version`, and random-K `seed` / `draws` must match
   across the set when present. Mixing arms → **`rejected`**.
4. **Sufficient baselines** — kill/continue require **five known random-K
   percentiles** and **five mechanical nets**. One known percentile (or a missing
   mechanical mark) is **`insufficient`**, not continue.

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
| `insufficient` | Fewer than five scoreable paper sessions, or five sessions without a full set of known random-K percentiles and mechanical nets | Collect more complete paper sessions. Do not act. |
| `rejected` | Duplicate sessions, synthetic evaluations, missing identity, or mixed experiment identity | Do not kill or continue. Supply five distinct real paper sessions from the same experiment. |
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
2. Five known random-K percentiles and five mechanical nets
3. Mean random-K percentile `≥ 60`
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
| Random-K | 1,000 seeded draws of K printed contracts (K = model enter count). Seed material is `20260908` plus `packet_hash`. Mechanical 300s / uncapped entry. Model net as a percentile rank of complete draws. |
| Mechanical top-K | Highest UW-tagged **ask-side** premium sums; same 15:55 ET exit. Side is never inferred from price vs NBBO. |
| Abstain | Zero enters; net `0` |
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
incomplete. Tuesday stays packet baseline (`research.cli run`). See
[TUESDAY_EXECUTION_READINESS.md](TUESDAY_EXECUTION_READINESS.md).
