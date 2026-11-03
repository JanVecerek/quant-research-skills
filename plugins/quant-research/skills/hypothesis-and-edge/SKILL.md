---
name: hypothesis-and-edge
description: Use when turning a trading idea, signal or anomaly into a testable hypothesis before any backtest or test; when asked why a strategy should make money, who the counterparty is, or whether an edge is a risk premium, behavioural or structural; when writing or changing hypothesis.yaml; and when checking backtest results for red flags such as a daily Sharpe above 2 or an edge that disappears with one bar of delay.
---

# Hypothesis and edge

This skill owns **the source of edge and counterparty, the red-flag check, and the pre-registered hypothesis** (`hypothesis.yaml`, `qrkit hypothesis check|lock`, `qrkit red-flags`). It runs before any test. Step order belongs to `quant-research:research-workflow`.

**Core principle:** decide what would count as success, and why anyone would pay you for it, *before* you see a single result. Otherwise every result can be explained and none can be trusted.

`qrkit` means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled).

## 1. State the source of edge and the counterparty

Before writing the file, answer in one sentence each, in your reply to the user:

| Question | Why it matters |
|---|---|
| **Source of edge:** risk premium, behavioural, or structural? | Each has a different expected size and failure mode (see `references/edge-and-base-rates.md`). |
| **Counterparty:** who is on the other side, and why do they accept losing? | No counterparty means no persistent edge; the "edge" is likely noise. |
| **Why not arbitraged away?** | If the answer is "nobody noticed", the base rate says it will not survive. |
| **Base rate:** what Sharpe do similar strategies earn? | A result far above the base rate is a red flag, not a discovery. |

If the user cannot name a counterparty, say so plainly and record the weakest plausible answer. Do not invent a story that makes the idea sound better.

## 2. Write `hypothesis.yaml`

Copy `references/hypothesis-template.yaml` into the project and fill every field. All fields are required; `qrkit hypothesis check` rejects missing ones. Key choices:

- `h0` / `h1`: about one parameter, stated so a single test can reject H0 (e.g. "mean rank IC = 0" vs "> 0").
- `test`: one of the qrkit commands listed in the template. Choose it with `quant-research:statistical-testing` now, not after exploring. Why: picking the test after seeing results is a hidden trial.
- `min_effect`: the smallest effect worth trading after costs, not the effect you hope for. Power is computed for it. For `metric: cointegration | variance_ratio | beta` there is no standard power formula, so also set `min_sharpe` (smallest annualised net Sharpe worth trading); power is computed for that.
- `in_sample` / `out_of_sample`: OOS is the most recent period and does not overlap IS. Typical split 70/30. Why: you will touch OOS exactly once.
- `costs` and `capital`: realistic values for the asset class; use 0 only where a cost truly does not apply.
- `budget.max_trials`: how many strategy variants you allow yourself (default 10). Set it from the research plan before running anything. If the user asks for a grid (e.g. 12 look-backs × 3 holding periods), declare the whole grid, the selection rule ("highest in-sample net Sharpe") and a budget that covers it here; the deflated Sharpe then charges for every variant. `kill_criteria`: observable conditions under which you stop.

Then run:

```bash
qrkit hypothesis check hypothesis.yaml
```

Report the power. If `power_at_min_effect < 0.8`, tell the user the sample is too short for a conclusive negative result and show `periods_needed_for_80pct_power`.

## 3. Lock it

After the data audit passes (`quant-research:data-quality-audit`):

```bash
qrkit hypothesis lock hypothesis.yaml
```

Lock records the file hash and assigns an id (`H-xxxxxxxxxx`). Every later qrkit command refuses to run if the file changed. **Any edit, including "just a typo" or "a slightly different threshold", creates a new id.** Trials of earlier ids remain in `trials.csv` and the reviewer sees them. Why: moving the goalposts after seeing results is the most common way a researcher fools themselves.

Never edit `qr-output/` files or delete rows from `trials.csv`.

## 4. Red flags on results

After a backtest (`quant-research:backtest-validation`):

```bash
qrkit red-flags --backtest <returns.csv> --weights <weights.csv> [--sweep sweep.csv]
```

| Flag | Why it is suspicious |
|---|---|
| Net Sharpe > 2 on daily data | Few real strategies sustain it; usually look-ahead, stale prices, missing costs or survivorship. |
| One year or period produces most of the P&L | One event, not a repeatable edge. |
| One parameter value works, its neighbours do not | Overfitted spike. Pass a `--sweep` CSV (parameter, metric) when you varied a parameter. |
| Edge lost with one bar of execution delay | The signal uses information you could not trade on, or bid-ask bounce. |

Report every hit at the top of your answer, before any positive number. `qrkit report` places them first.

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing the hypothesis after a "quick look" at results | The quick look is a trial. Log it as such, then write the hypothesis as if blind. |
| H1 "the strategy is profitable" | Name the parameter and the test: "mean daily net return > 0, HAC t-test". |
| `min_effect` set to the observed effect | Set it from economics: the effect that covers costs and is worth the capital. |
| Changing `in_sample.end` to include a good period | That creates a new id; the old trials still count. |
| Skipping counterparty because "it's a well-known anomaly" | Known anomalies decay after publication; say so with the base rate. |
