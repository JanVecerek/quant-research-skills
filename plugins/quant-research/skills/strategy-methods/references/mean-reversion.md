# Mean reversion methods

P0 items of the plugin spec (Appendix A). Items marked [P1] are not yet in qrkit; say so if they are needed.

## Contents
1. Establish the premise
2. Pairs
3. Hedge ratio
4. Signal
5. Pitfalls
6. References

## 1. Establish the premise

- **Stationarity: ADF and KPSS together.** ADF H0 = unit root, KPSS H0 = stationary; conclude only when they agree. `qrkit stats stationarity --series <spread.csv> --column spread`. Why: each test has low power against the other's alternative; disagreement means the data cannot tell.
- **Variance ratio (Lo & MacKinlay 1988), heteroskedasticity-robust.** VR(q) < 1 supports mean reversion. `qrkit meanrev variance-ratio --series ... --lags q` (or `--asset X` for a single log price). Report `p_value_vr_below_1`.
- **Hurst exponent:** descriptive only, never a test. Its small-sample bias is large and it has no reliable null distribution.
- **Half-life** from the AR(1) fit ΔSₜ = c + λSₜ₋₁ + ε, half-life = −ln 2 / λ: `qrkit meanrev half-life --series ... --holding-period H`. It must be short relative to the sample (many independent reversions: qrkit checks < n/10) and comparable to the holding period. A half-life of 200 days in a 3-year sample means a handful of reversions: not testable.

## 2. Pairs

- **Engle-Granger with MacKinnon critical values, tested in both directions** (Engle & Granger 1987; MacKinnon 2010): `qrkit meanrev engle-granger --a A --b B [--levels log|price]`. qrkit reports both; a result significant in only one direction is treated as not cointegrated. Why: OLS is not symmetric; one direction can pass by chance.
- **Johansen for three or more assets [P1].**
- **Separate formation and trading periods** (Gatev, Goetzmann & Rouwenhorst 2006): estimate on a formation window, trade in the following window, never on the same data. `hedge-ratio --mode static --formation N` does this; `--refit-every M` rolls it forward.
- **Screening many pairs is multiple testing.** Test every candidate pair in-sample, correct with BH-FDR (`qrkit stats multiple --method bh --outputs <eg outputs>`), and confirm survivors out of sample. Report how many pairs were screened.
- **State how the spread is built:** log prices (default, β is an elasticity) or price levels; and how β maps to weights (qrkit: dollar weights w_a = pos/(1+|β|), w_b = −pos·β/(1+|β|), gross exposure 1).

## 3. Hedge ratio

- **Never estimated on data the strategy later trades.** In qrkit, β applied at t is estimated on bars before t only (tested: changing data after t does not change β up to t).
- **Static and rolling estimates are separate variants**, both logged in `trials.csv`.
- **Static:** estimated on the formation window, frozen for the trading window, re-estimated walk-forward (`--refit-every`). TLS (`--fit tls`, default) is preferred because it is symmetric in the two legs; with OLS (`--fit ols`) test both directions.
- **Rolling:** `--mode rolling --window W`. The window length is a parameter, so every length tried is a trial.
- **Rebalancing cost:** each change in β trades both legs. The weights from `pairs-weights` move with β so `qrkit backtest` charges it; report `hedge_turnover` from the hedge-ratio output.
- **Kalman [P1]:** filtered estimates only (smoothed estimates are look-ahead), noise parameters fitted in-sample and frozen, burn-in excluded. The Kalman spread is a one-step prediction error and almost always looks stationary, so a stationarity test on it is not evidence.

## 4. Signal

- **z-score from trailing mean and volatility only:** `qrkit meanrev zscore --hedge <spread.csv> --window W`.
- **Thresholds fitted in-sample and frozen:** entry, exit and stop (`pairs-weights --entry --exit --stop`) are parameters; each combination tried is a trial. Pre-register them when possible (2.0 / 0.5 is the conventional default).

## 5. Pitfalls

- **Bid-ask bounce and stale prices inflate short-horizon reversal.** Use mid quotes where available, and check with one bar of execution delay: `qrkit red-flags --backtest ... --weights ...` reports `edge_lost_with_one_bar_delay`.
- **Short leg:** include borrow cost (`costs.borrow_bps_annual`) and dividends (use total-return adjusted prices).
- **Report results by volatility regime:** walk-forward folds (`qrkit validate`) and net P&L by year; mean reversion often fails in trending, high-volatility regimes.
- **Structural breaks:** mergers, index changes and regulation break pairs permanently; a stop rule (`--stop`) limits, but does not remove, this risk.

## 6. References

- Engle, R. & Granger, C. (1987). Co-integration and error correction. *Econometrica* 55(2).
- MacKinnon, J. (2010). Critical values for cointegration tests. Queen's Economics Department WP 1227.
- Lo, A. & MacKinlay, C. (1988). Stock market prices do not follow random walks. *Review of Financial Studies* 1(1).
- Gatev, E., Goetzmann, W. & Rouwenhorst, G. (2006). Pairs trading. *Review of Financial Studies* 19(3).
- Avellaneda, M. & Lee, J.-H. (2010). Statistical arbitrage in the US equities market. *Quantitative Finance* 10(7).
- Do, B. & Faff, R. (2010). Does simple pairs trading still work? *Financial Analysts Journal* 66(4).
