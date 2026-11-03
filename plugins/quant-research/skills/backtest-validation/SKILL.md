---
name: backtest-validation
description: Use when backtesting target weights or positions, adding transaction costs (spread, commission, market impact, borrow), computing break-even cost, validating out of sample, walk-forward testing, checking overfitting or the deflated / probabilistic Sharpe ratio, or checking factor or market exposure before calling a result alpha.
---

# Backtest and validation

This skill owns **costs, out-of-sample validation and overfitting checks** (`qrkit backtest`, `costs`, `validate`, `exposure`; red flags are defined in `quant-research:hypothesis-and-edge` and run here). Step order belongs to `quant-research:research-workflow`.

**Core principle:** an in-sample Sharpe ratio is an upper bound. Costs, the number of variants you tried and the one-time out-of-sample run decide what is left.

`qrkit` means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled).

## Strategy output contract

The project's own engine (or `qrkit meanrev pairs-weights` / `qrkit momentum portfolio`) produces **target weights**: a CSV/Parquet with `date, asset, weight`. A weight dated t is decided at the close of t using data up to t, and earns the return from t to t+1. A listed date defines the whole book (unlisted assets are 0); between listed dates weights are held. qrkit rejects files that break the contract.

## The sequence (in-sample)

```bash
qrkit backtest  --weights <weights.csv>                         # gross and net returns, summary
qrkit costs     --backtest qr-output/series/backtest-<k>-returns.csv
qrkit red-flags --backtest qr-output/series/backtest-<k>-returns.csv --weights <weights.csv> [--sweep sweep.csv]
qrkit exposure  --backtest qr-output/series/backtest-<k>-returns.csv [--factors factors.csv]
qrkit validate  --backtest qr-output/series/backtest-<k>-returns.csv --folds 5
```

Then, once, when the strategy is frozen:

```bash
qrkit validate --oos --from qr-output/<weights-output>.json    # qrkit-built weights: replayed with frozen parameters
qrkit validate --oos --weights <engine-weights-covering-OOS.csv>  # weights from the project's engine
```

## Rules

1. **Report gross and net side by side, each with its confidence interval.** Net uses the hypothesis's cost assumptions: half-spread and commission per unit of turnover, square-root market impact (Y·σ·√(trade/ADV), needs volume and `capital`), and borrow on shorts. Why: gross results are not tradeable; a Sharpe without an interval hides how little a few years of data say.
2. **Show cost sensitivity and the break-even cost** from `qrkit costs`. If break-even is below about twice the assumed cost, say the result is fragile to costs. Why: cost assumptions are the least certain input.
3. **Every backtested weights file is a trial.** `qrkit validate` reads the number of distinct variants for this hypothesis id from `trials.csv` and computes the deflated Sharpe ratio (Bailey & López de Prado 2014) against `dsr_threshold`. Do not backtest variants "off the record" in your own code. Why: the deflated Sharpe is only honest if the trial count is.
4. **Walk-forward stability:** `validate` splits the in-sample window into sequential folds. If fewer than 60% of folds have a positive Sharpe, report the result as unstable. Fitted parameters (hedge ratios, thresholds) must be re-estimated per fold by the strategy; qrkit's hedge ratio does this with `--refit-every`.
5. **The OOS run happens once per hypothesis id, after everything is frozen.** qrkit refuses a second run. Before running it, confirm: hypothesis locked, test done, costs set, variant chosen on in-sample data only. Why: once you have seen the OOS result, any change makes the OOS window in-sample. If you need another attempt, write a new hypothesis (new id) and say the OOS window is no longer clean.
6. **Exposure before alpha.** `qrkit exposure` regresses net returns on the market (equal-weight panel proxy) and, with a factor file, on its factors. Without a factor file the status is WARN: you may say "net of market exposure", never "alpha".

## Grids of variants

When the hypothesis declares a grid: backtest every variant with qrkit (each is logged), select by the pre-registered rule on in-sample results only, run the pre-registered test on the selected variant and pass it explicitly with `qrkit report --test <json> --backtest-out <json>`. The deflated Sharpe (N = all variants from `trials.csv`) is what accounts for the selection; a Holm correction across the variants' tests (`qrkit stats multiple`) is supporting evidence. Run the one-time OOS only on the selected variant.

## Interpreting validation

| Result | Meaning |
|---|---|
| DSR ≥ threshold, OOS pass | Selection-adjusted evidence and a clean replication: eligible for *effect found* (with the in-sample test) |
| DSR < threshold, high in-sample Sharpe | Expected from the number of variants tried: not evidence |
| OOS fail, in-sample pass | Overfitting or decay; *no effect* unless the OOS test was underpowered (then *inconclusive*) |
| OOS CI wide and includes 0 | Short OOS window; *inconclusive*, not *effect found* |

## Common mistakes

| Mistake | Fix |
|---|---|
| Costs omitted "for now" | Costs are in the hypothesis from the start; `qrkit backtest` always reports net. |
| One cost level only | `qrkit costs` sweep: 0×, 0.5×, 1×, 2×, 3×, 5× and break-even. |
| Turnover from weight changes ignored for hedge-ratio updates | Weights must move with β; qrkit pairs weights do. |
| OOS = second half of the data the parameters were chosen on | OOS is the window in `hypothesis.yaml`, touched only by `validate --oos`. |
| Running OOS, then "fixing" the strategy and running again | Refused by qrkit; write a new hypothesis and say the OOS window is spent. |
| Calling a beta-heavy long-short "alpha" | Run `qrkit exposure`; report the betas. |

Details of the cost model and validation statistics: `references/costs-and-validation.md`.
