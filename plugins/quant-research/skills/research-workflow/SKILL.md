---
name: research-workflow
description: Use when a user asks whether a trading idea, signal, factor, anomaly or strategy "works", wants a backtest, Sharpe ratio, go/no-go, or kill/iterate/promote decision, or starts any quantitative research experiment on market data (pairs trading, mean reversion, momentum, cointegration, factor returns). Also use when writing up research results or a final research report.
---

# Research workflow

This skill owns **step order, the research budget, the kill / iterate / promote decision and the final report**. Each step has exactly one owning skill; this skill only sequences them.

**Core principle:** a research conclusion is only as good as the weakest step behind it. A convincing Sharpe ratio from a skipped step is a false discovery waiting to be traded.

`qrkit` below means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled). It runs in its own environment; never install anything into the user's project.

## The order (do not reorder, do not skip)

| # | Step | Owning skill | Done when |
|---|------|--------------|-----------|
| 1 | Hypothesis and source of edge | `quant-research:hypothesis-and-edge` | `qrkit hypothesis check` reports complete |
| 2 | Data audit | `quant-research:data-quality-audit` | `qrkit audit` has no FAIL |
| 3 | Lock | `quant-research:hypothesis-and-edge` | `qrkit hypothesis lock` returns an id; re-run `qrkit audit` so the audit is logged under that id |
| 4 | In-sample exploration | `quant-research:strategy-methods` | spread / signal / weights built with qrkit, in-sample only |
| 5 | Pre-registered test | `quant-research:statistical-testing` | the `test` named in `hypothesis.yaml` was run once on the in-sample window |
| 6 | Costs and validation | `quant-research:backtest-validation` | `backtest`, `costs`, `red-flags`, `exposure`, `validate` all ran |
| 7 | One-time out-of-sample run | `quant-research:backtest-validation` | `qrkit validate --oos` ran (once per hypothesis id) |
| 8 | Independent review | `research-reviewer` subagent | required before any *effect found* |
| 9 | Report | this skill | `qrkit report` wrote `qr-output/report-<id>.md` |

Why the order matters: a hypothesis written after seeing results fits the noise; analysis on unaudited data turns data errors into "alpha"; a test chosen after exploration is one more hidden trial; OOS data looked at before the strategy is frozen is no longer out of sample.

If a step is missing, the conclusion is **inconclusive**, whatever the numbers look like. Say which step is missing.

**Exception: stop before OOS when the pre-registered test fails.** If the step-5 test fails, *effect found* is no longer possible, so the OOS run cannot change the conclusion: skip step 7 and keep the out-of-sample window unspent for a later hypothesis. The conclusion is *no effect* if power was adequate, otherwise *inconclusive*. You may still run step 6 in-sample if the user asked for a Sharpe or costs, labelled as descriptive. `qrkit report` handles this case.

## Rules

1. **Every number comes from a `qrkit` output file, and you cite it.** Write `net Sharpe 1.43 [0.12, 2.71] (qr-output/backtest-7181df15bd00.json)`. Why: a number you computed in your head, in pandas, or in an ad-hoc script cannot be reproduced, is not logged as a trial, and is not restricted to the in-sample window.
2. **Never compute a statistic, return series or test outside qrkit**, not even "just to take a quick look". Reading the data with pandas to look at columns is fine; `df.pct_change().mean()` is a statistic. Why: every unlogged look is a hidden trial, and ad-hoc code bypasses the in-sample window. If qrkit lacks a method, say so and mark the result as *outside qrkit, not traceable* in the report.
3. **Use exactly one of three conclusions:** *effect found*, *no effect*, *inconclusive*. *Effect found* requires all three: the pre-registered in-sample test passes, the one-time OOS validation passes, and the deflated Sharpe ratio meets `dsr_threshold` (default 0.95). `qrkit report` computes this; do not overrule it in prose.
4. **Before reporting *effect found*, run the `research-reviewer` subagent** with the hypothesis file, `qr-output/` and the draft report, then attach its findings with `qrkit report --review <file>`. Why: the reviewer has not seen the conversation, so it cannot be talked into the result.
5. **Respect the research budget.** `budget.max_trials` in the hypothesis counts strategy variants (distinct weight files backtested) for the hypothesis id. When it is reached, stop and recommend kill, iterate or promote with reasons. Why: each extra variant raises the bar the deflated Sharpe must clear; past the budget you are mining.
6. **Log early looks at OOS data.** If the user says they already looked at the out-of-sample period, or asks you to, run `qrkit log-event --kind oos_peek --note "<what was seen>"` and tell them the OOS result is now weaker evidence. Never select a variant because it does well in the OOS period.

## Edge cases

- **Sample too short:** if `qrkit hypothesis check` shows `power_at_min_effect < 0.8`, tell the user before testing. A negative result will be *inconclusive*, not *no effect*.
- **Audit FAIL:** stop. Hand over to `quant-research:data-quality-audit` to propose a fix script. Do not analyse the unfixed data "in the meantime".
- **User wants it fast** ("quick go/no-go", "end of day"): run the same steps; they take minutes with qrkit. If you must stop early, report *inconclusive* with the missing steps listed. A fast wrong *go* is the expensive outcome.
- **User pushes for one result** ("make sure the best one does well in 2020-2023"): explain that choosing on the test period destroys it as a test, log the peek, and select only on in-sample data.

## Decision after the report

| Computed conclusion | Budget left | Recommend |
|---|---|---|
| effect found (reviewed) | any | **promote**: name what remains (capacity, live paper trading) |
| no effect (adequately powered) | any | **kill**: name the kill criterion that fired |
| inconclusive | yes | **iterate**: name the single change and write it as a new hypothesis (new id) |
| inconclusive | no | **kill** or collect more data; do not keep varying |

`qrkit report` prints `suggested_decision`; give your reasons next to it.

## Running the report

```bash
qrkit report --interpretation interpretation.md [--review review.md]
```

The report finds the latest outputs for the hypothesis id in `trials.csv`. Override with `--test <json>`, `--backtest-out <json>`, `--oos-out <json>` when you need a specific file (e.g. the pre-registered variant rather than the last one backtested). It writes `qr-output/report-<id>.md` and a JSON with `conclusion`, `suggested_decision` and `reasons`.

## Final answer format

1. First line: the conclusion and the decision (e.g. **No effect — kill**).
2. Red flags, if `qrkit red-flags` raised any.
3. Computed results with file citations: H0, in-sample test, trial count, OOS result with confidence interval, gross and net Sharpe with intervals.
4. Your interpretation, clearly labelled as interpretation. Pass it to `qrkit report --interpretation <file.md>` so it is stored separately from computed results.

## Red flags: stop and go back a step

| Thought | Reality |
|---|---|
| "Let me just quickly check the Sharpe in pandas first" | That is an unlogged trial on unwindowed data. Run qrkit. |
| "The data looks fine, skip the audit" | The baseline agents found duplicates and an unadjusted split only because they looked. qrkit checks ten things in seconds. |
| "I'll write the hypothesis after I see what works" | That is fitting the hypothesis to noise. Write it first. |
| "Full-sample cointegration test first, then split" | The full sample contains the OOS window. Test in-sample only. |
| "It's clearly significant, no need for OOS" | In-sample significance after any search is inflated. *Effect found* needs OOS and DSR. |
| "The user is in a hurry, a rough number is fine" | A rough number becomes the decision. Say *inconclusive* instead. |
| "Run OOS again with the fixed parameters" | OOS runs once per id. A new idea needs a new hypothesis. |
