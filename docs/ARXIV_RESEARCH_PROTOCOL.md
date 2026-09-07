# Related work and prospective research protocol

Research date: 2026-09-07. Status: literature screening and proposed experiment; no new profitability findings. Read alongside `GROK_RESEARCH_HANDOFF.md`.

## What already exists

The broad idea of using an LLM to trade, remember outcomes and revise beliefs has substantial prior work. A larger or newer model does not make those concepts new. The papers below are relevant references, not independent validation that this system will earn money. Screening covered arXiv abstracts and selected full text; this is not an exhaustive systematic review or a replication audit.

| Paper | Relationship to this experiment | Important distinction |
| --- | --- | --- |
| [FinMem (2023)](https://arxiv.org/abs/2311.13743) | Layered memory, multi-source financial information and trading decisions. | Stock experiments; memory-based trading is prior art. |
| [FinAgent (2024)](https://arxiv.org/abs/2402.18485) | News, prices, multimodal inputs, reflection and memory retrieval. | Includes strategy/tool augmentation; not this opening-window options experiment. |
| [FinCon (2024)](https://arxiv.org/abs/2407.06567) | Outcome-driven self-critique and updated investment beliefs via verbal reinforcement. | Direct precedent for a resolver that influences later decisions; uses multiple agents. |
| [LiveTradeBench (2025)](https://arxiv.org/abs/2511.03628) | Prospective prices/news/portfolio evaluation across models. | Stocks and prediction markets; reports that general benchmark rankings do not imply better trading outcomes. |
| [A Hybrid Architecture for Options Wheel Strategy Decisions (2025)](https://arxiv.org/abs/2512.01123) | LLM interprets market context, builds Bayesian networks, and refines them from outcomes. | Options and feedback already appear together; wheel strategy and model-generated Bayesian inference differ from discretionary intraday long-option selection. Historical results are author-reported, not replicated here. |
| [Inferring Latent Market Forces (2025)](https://arxiv.org/abs/2512.17923) | Tests LLM recognition of gamma-exposure patterns, including 0DTE hedging, using obfuscated inputs. | Pattern recognition is distinct from profitable executable trades. Useful motivation for separating reasoning quality and PnL. |
| [From Natural Language to Executable Option Strategies (2026)](https://arxiv.org/abs/2603.16434) | Structured option-chain reasoning and an executable intermediate language. | Executable strategy translation does not establish a predictive trading edge. |

I did not identify an exact match in this search to the complete combination: ten equities, opening 15 minutes of UW-accessible options flow, archived global/company/macro context, actual portfolio constraints, up to three discretionary same-day selections, and next-session resolver memory, evaluated prospectively through Codex CLI. This is a bounded search finding, not proof of novelty. Search again before submission, follow citations, and read the closest full papers before claiming a contribution.

## Proposed contribution

Working title: **Prospective Evaluation of Memory-Augmented LLM Discretion in Intraday Equity Options**.

Question: does compact, evidence-linked feedback improve executable, cost-adjusted next-session option selection compared with the same model and evidence without memory?

Secondary question: does expanded context improve over flow/price evidence alone? Separate this from whether either system produces positive absolute returns. The use of Codex CLI is an implementation choice, not the scientific contribution. Memory changes the model's supplied context; it does not train its weights or guarantee recursive improvement.

## Freeze before collecting confirmatory outcomes

1. Fix the ten symbols, eligibility rules, entry deadline, one-contract paper sizing, capital accounting, exit policy, quote-age/spread limits, costs, failure treatment and observation period. A pilot may inform these choices, but pilot days do not count as untouched confirmatory evidence.
2. Use a 10-session operational pilot. Then use pilot variance and an economically meaningful minimum effect to plan sample size. A proposed 60-session follow-up is a planning budget, not a power guarantee; register the final duration before starting it. Publish an inconclusive estimate if intervals remain wide.
3. Archive every eligible session, including no-trade, missing data, rejected output, timeout and outage days. Keep zero-trade results distinct from unknown PnL. Never substitute an end-of-day rerun for a failed morning decision.
4. Register one primary contrast: full context plus memory versus full context without memory, measured as paired mean net dollar PnL per scheduled session under equal capital limits. Report both known totals and unresolved exposure; missing exits must not be treated as zero or silently dropped. Freeze sensitivity bounds/imputation policy before confirmatory testing.
5. Secondary arms: flow/price only without memory, a predeclared simple flow ranking, randomized eligible-contract selection, and cash. All arms use identical eligibility, capital and fill/exit assumptions. Baselines measure added value; they do not constrain the discretionary selector's reasoning.
6. Commit prompts, schema, code, configuration, arm assignment, planned statistics and model identity settings before open. Record requested and observed model identity separately; unknown observed identity remains unknown. If model versions change, mark the break and analyze separately. Do not relabel an unavailable model as another.

## Timing and execution

Only use information observed within the prescribed opening window. Preserve exchange/event time, publication time, actual receipt time and archive freeze time. A previously announced future event is valid calendar context; the later realized event is not. UW entitlement-limited records must not be described as all OPRA traffic.

The baseline collector allows a bounded retrieval delay for opening-window UW prints; expanded context is required to have been observed by 09:45 ET. Publish this distinction. Freeze all arms' data equally. Persist every CLI attempt, elapsed time, input hash, prompt hash and selected contract. Inference latency counts: paper entry is the first eligible ask observed after the actual decision response, not the 09:45 price. Mark stale/expired decisions unfilled. A second, explicitly labeled common-time analysis can compare selection skill without different response times; it does not replace the executable-latency primary result.

Use ask-side buys and bid-side sells, fees, slippage, quote sizes and stale-quote exclusions. Report gross PnL, trading-cost-net PnL and net after allocated data/CLI/infrastructure costs separately. Paper fills approximate execution and cannot prove real fillability, queue position or achievable live returns. Existing evaluator exits at 15:55 ET; discretionary exit suggestions remain annotations until a separate exit experiment is preregistered. Restrict initial runs to normal full sessions; enforce an exchange calendar before scheduling short sessions.

## Test the learning loop rather than reward a good story

The resolver receives immutable decisions and deterministic outcome calculations. It must review winners, losers, watches, no-trade decisions and skipped stocks. It may offer tentative explanations; a price change alone cannot identify a causal mechanism. It cannot edit historical picks, calculated PnL or active instructions.

The next session sees a bounded summary of prior eligible days with supporting IDs, counterevidence and a way to disprove each lesson. Keep detailed archives. Run the no-memory arm on the same days. Each arm has its own history; do not leak another arm's selected outcomes or learned lessons into it. Log prompt-change proposals separately, version candidates, and test them on future shadow sessions. Selective repeated testing and promotion on the same outcomes will overfit.

## Analysis and reproducibility

- Unit of dependence is the session, not each of three correlated options. Report paired daily differences and day-block bootstrap intervals with a prespecified block-length sensitivity analysis. Report sample size, effect size and uncertainty, not just win rate.
- Report fill rate, selection/abstention rate, data coverage, decision latency, maximum drawdown, mean/median PnL, tail losses and all operating costs. Distinguish standalone selection results from portfolio-constrained feasibility.
- Treat secondary comparisons and changing prompts as exploratory unless correction/testing rules were registered. Do not stop early merely because cumulative PnL is positive.
- For stochastic variation, use a predeclared number of shadow repetitions per day and equal compute budgets across arms; preserve all outputs. Never pick the best rerun after observing outcomes. CLI execution does not promise a reproducible random seed.
- Release code, prompts, schemas, synthetic fixtures, environment versions and an artifact manifest. Publish licensed aggregates where raw commercial feed redistribution is not permitted; document this reproducibility limitation. Keep credentials and identifiable account information private.
- Prospective collection limits historical look-ahead, but does not prove absence of model training contamination or causal reasoning. Include these limits explicitly.

## arXiv path

Existing related work does not prevent a new contribution through a careful extension, replication, benchmark or informative negative result. Publication need not depend on making money. An honest protocol or methods manuscript can describe planned work, but must not present planned or synthetic results as measured findings.

arXiv accepts topical, refereeable scientific contributions from registered authors, is free to submit to, and moderates submissions. New users or new categories may need endorsement. Authors are generally expected to submit their own work. Acceptance is not guaranteed and posting is not peer review. See [submission guidelines](https://info.arxiv.org/help/submit/index.html) and [endorsement](https://info.arxiv.org/help/endorsement.html).

Prepare a manuscript with related work, exact protocol, architecture, results, ablations, failures and limitations; use placeholders until results exist. A human author should verify every claim/citation, review the complete manuscript and data permissions, and submit through their own arXiv account. A suitable candidate category is q-fin.TR or q-fin.CP, subject to the final paper and moderation. No arXiv submission has been made.
