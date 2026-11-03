---
name: strategy-methods
description: Use when researching a mean-reversion or momentum strategy — pairs trading, cointegration, spread z-score, hedge ratio, half-life, statistical arbitrage, time-series momentum (trend following), cross-sectional momentum (winners minus losers, 12-1), quantile long-short portfolios or rank IC — to build the signal, spread or weights and apply that family's established tests and pitfalls.
---

# Strategy methods: mean reversion and momentum

This skill owns **the family-specific methods and pitfalls** for mean reversion and momentum (`qrkit meanrev ...`, `qrkit momentum ...`). It builds spreads, signals and weights in-sample and runs the family's tests. Choosing the pre-registered test belongs to `quant-research:statistical-testing`; costs and validation to `quant-research:backtest-validation`; order to `quant-research:research-workflow`.

**Core principle:** each family has a few classic ways to fool yourself, and the literature has already named them. Apply the established method, then check the named pitfalls before showing any result.

`qrkit` means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled). All commands read only the in-sample window and write weights in the strategy output contract (`date, asset, weight`).

Load the reference for the family you are working on:
- Mean reversion, pairs, cointegration, hedge ratios: `references/mean-reversion.md`
- Time-series and cross-sectional momentum: `references/momentum.md`

## Errors to flag every time

These are errors, not style choices. If the user's code or request contains one, say "this is an error" and why, then do it correctly.

| Error | Why it is wrong | Correct method |
|---|---|---|
| **Hedge ratio estimated on the full sample** (or on data the strategy later trades) | The spread is stationary by construction on the data that fitted it: look-ahead | `qrkit meanrev hedge-ratio --mode static --formation N [--refit-every M]` or `--mode rolling --window W` |
| **No hedge rebalancing cost** | Every change in β trades both legs; ignoring it overstates returns | Weights from `qrkit meanrev pairs-weights` move with β; `qrkit backtest` charges the turnover; report hedge turnover |
| **Cross-sectional momentum signal without a skip period** | The latest month carries short-term reversal and bid-ask bounce (Jegadeesh & Titman 1993) | `--skip 21` on daily data (12-1 = `--lookback 231 --skip 21`); qrkit reports an error for `--kind xs --skip 0`. Time-series momentum follows Moskowitz-Ooi-Pedersen and may use `--skip 0` |
| Cointegration tested on the full sample, then "validated" on a sub-period | The full sample includes the OOS window | Test in-sample only (qrkit enforces the window) |
| Screening many pairs and keeping the best p-values | Multiple testing | BH-FDR on the screen (`qrkit stats multiple --method bh`), survivors confirmed OOS |
| Time-series momentum without volatility scaling | High-vol assets dominate P&L and the test | `qrkit momentum signal --kind ts` (sign / ex-ante EWMA vol) |

## Mean reversion: the sequence

```bash
qrkit meanrev engle-granger --a KO --b PEP                     # both directions, MacKinnon critical values
qrkit meanrev hedge-ratio --a KO --b PEP --mode static --fit tls --formation 252 --refit-every 63
qrkit meanrev half-life --series qr-output/series/<hedge>-spread.csv --column spread --holding-period 10
qrkit meanrev variance-ratio --series qr-output/series/<hedge>-spread.csv --column spread --lags 5
qrkit meanrev zscore --hedge qr-output/series/<hedge>-spread.csv --window 20
qrkit meanrev pairs-weights --zscore qr-output/series/<z>-zscore.csv --entry 2 --exit 0.5
```

Then hand the weights file to `quant-research:backtest-validation`. State how the spread is built (log or price levels, `--levels`) and how β maps to leg weights (qrkit: w_a = pos/(1+|β|), w_b = −pos·β/(1+|β|)).

Read `hedge_turnover` in the hedge-ratio output: `abs_dbeta_per_year` well above 1 means β jumps at each refit and the hedge itself drives turnover and cost. That is evidence of an unstable relationship, not a cost detail to tune away.

Static and rolling hedge ratios are **separate variants**, and every rolling window length or formation length tried is a trial. Decide the variant in the hypothesis where you can.

## Momentum: the sequence

```bash
qrkit momentum signal --kind xs --lookback 231 --skip 21       # 12-1 cross-sectional
qrkit momentum ic --signal qr-output/series/<sig>-signal.csv --horizon 21 --step 21
qrkit momentum portfolio --signal qr-output/series/<sig>-signal.csv --kind xs --quantiles 5 --holding 1 --rebalance 21
qrkit momentum tsmom --lookback-periods 12 --skip-periods 0 --period 21     # pooled TSMOM regression, Driscoll-Kraay errors
```

For time-series momentum: `--kind ts` gives sign(past return)/ex-ante vol, and `portfolio --kind ts` sizes positions to `--target-vol`. Overlapping holding periods (`--holding > 1`) need Newey-West lags ≥ holding period; qrkit sets this for `ic`.

Pitfalls to report for momentum (details in `references/momentum.md`): crash risk (skewness, max drawdown, performance after market rebounds: in the backtest summary's `crash_diagnostics`), survivorship (universe file), micro-cap dominance (run a `--min-dollar-volume` variant), and cost sensitivity (`qrkit costs` sweep).

## Common mistakes

| Mistake | Fix |
|---|---|
| Using `coint` once in one direction | `qrkit meanrev engle-granger` tests both; a direction-dependent result is "not cointegrated". |
| z-score from full-sample mean and std | `qrkit meanrev zscore` uses trailing windows only; entry/exit thresholds fixed in-sample and frozen. |
| Ignoring bid-ask bounce in short-horizon reversal | Use mid quotes or test with one bar of delay (`qrkit red-flags --weights`). |
| Short leg without borrow cost or dividends | Set `costs.borrow_bps_annual`; use total-return adjusted prices. |
| Reporting only the best look-back | Each look-back is a trial; report all, correct, or pre-register one. |
| Writing your own spread/signal code in pandas | Use qrkit so the in-sample window, timing and trial log are enforced. If the project engine builds the weights, pass them to `qrkit backtest` and check their timing (weight dated t uses data ≤ t). |
