# Momentum methods

P0 items of the plugin spec (Appendix A). Items marked [P1] are not yet in qrkit; say so if they are needed. Daily data: 21 bars ≈ 1 month, 252 ≈ 1 year.

## Contents
1. Time-series momentum
2. Cross-sectional momentum
3. Pitfalls
4. References

## 1. Time-series momentum (trend following)

- **Signal = sign (or size) of the past excess return over the look-back, volatility-scaled** (Moskowitz, Ooi & Pedersen 2012). `qrkit momentum signal --kind ts --lookback 252 --skip 0` gives sign(past return) / ex-ante EWMA volatility (centre of mass 60 days, annualised). `qrkit momentum portfolio --kind ts --target-vol 0.4` sizes each position to the target volatility, averaged over assets. Why vol-scaling: without it, the most volatile assets dominate both P&L and the test.
- **Test with pooled regressions of vol-scaled returns on lagged vol-scaled returns, with HAC errors:** `qrkit momentum tsmom --lookback-periods 12 --skip-periods 0 --period 21` (monthly periods, Driscoll-Kraay errors robust to cross-asset correlation). Pre-register this as the test (`test: momentum tsmom`).
- **Variance ratio > 1 is supporting evidence** for trending: `qrkit meanrev variance-ratio --asset X --lags q`, report `p_value_vr_above_1`.
- **Futures need back-adjusted continuous contracts with a documented roll rule.** `qrkit audit` flags jumps on contract changes when a `contract` column is present.
- Excess return: use returns over the risk-free rate where the data allow it; for futures, price returns are already excess returns.

## 2. Cross-sectional momentum

- **Formation / skip / holding structure** (Jegadeesh & Titman 1993). The 12-1 signal skips the latest month to avoid short-term reversal: `qrkit momentum signal --kind xs --lookback 231 --skip 21`. qrkit reports an **error** for `--skip 0`.
- **Quantile long-short portfolios:** `qrkit momentum portfolio --kind xs --quantiles 5 --holding K --rebalance 21`: long the top quintile, short the bottom, each leg 0.5 gross, equal weight. `--holding K > 1` averages the last K monthly cohorts (overlapping portfolios); **Newey-West lags must be at least the holding period**.
- **Rank IC with its t-statistic; report turnover:** `qrkit momentum ic --signal ... --horizon 21 --step 21` (mean IC, IC IR, t with NW lags ≥ horizon/step). Turnover per year is in the backtest summary.
- **Fama-MacBeth regressions [P1].**
- **A new signal must earn alpha after controlling for established factors, including momentum itself** (spanning test, needs a factor file) **[P1]**. Until then: `qrkit exposure --backtest ... --factors factors.csv` regresses on the supplied factors; without a factor file the check is WARN and you must not call the result alpha.

## 3. Pitfalls

- **Momentum crashes** (Daniel & Moskowitz 2016): momentum loses heavily when markets rebound after a bear market. Report skewness, maximum drawdown and `crash_diagnostics` (mean return after bear-market rebounds vs otherwise) from the backtest summary.
- **Survivorship and missing delisting returns inflate results:** losers that delisted are missing from survivor-only panels. Use the universe membership file; the audit's survivorship check is WARN without it, and the report must say so. The backtest counts periods where a position was held on a missing price (`periods_with_position_on_missing_price`): these are likely delistings without delisting returns.
- **Equal-weighted micro-caps dominate:** report a liquidity-filtered variant (`portfolio --min-dollar-volume X`) or value-weighted results from the project engine. Each is a variant (trial).
- **High turnover makes costs decisive:** show results across a range of costs (`qrkit costs --backtest ...`: sweep and break-even cost).

## 4. References

- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance* 48(1).
- Moskowitz, T., Ooi, Y. H. & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics* 104(2).
- Asness, C., Moskowitz, T. & Pedersen, L. H. (2013). Value and momentum everywhere. *Journal of Finance* 68(3).
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2).
- Novy-Marx, R. & Velikov, M. (2016). A taxonomy of anomalies and their trading costs. *Review of Financial Studies* 29(1).
- Driscoll, J. & Kraay, A. (1998). Consistent covariance matrix estimation with spatially dependent panel data. *Review of Economics and Statistics* 80(4).
