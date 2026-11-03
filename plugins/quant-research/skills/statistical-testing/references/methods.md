# Methods: question → test → assumptions → what to do when they fail

All commands read the locked hypothesis's in-sample window only. "File" means a CSV/Parquet with a `date` column (qrkit output series qualify).

## Contents
1. Mean return / alpha
2. Sharpe ratio uncertainty
3. Stationarity and mean reversion
4. Autocorrelation
5. Regression / exposure
6. Predictive signals (IC)
7. Multiple testing
8. Assumption failures: what to do
9. References

## 1. Is the mean (net) return positive?

- **Test:** `qrkit stats hac-mean --series <returns.csv> --column net [--lags L] [--alternative greater]`
- **H0:** mean = 0. Newey-West HAC standard errors; lags default to ⌊4 (n/100)^(2/9)⌋.
- **Assumptions:** weak stationarity; enough observations (n ≥ 30, prefer several hundred); lags long enough for the autocorrelation present.
- **If they fail:** returns overlap (holding period h > 1 bar) → `--lags` ≥ h. Heavy tails or n < 250 → also run `qrkit stats bootstrap --statistic mean --seed S` and report both. Structural break (Levene halves fails) → report sub-period results; do not pool silently.

## 2. How uncertain is the Sharpe ratio?

- **Test:** `qrkit stats sharpe --series <returns.csv> --column net`
- **Method:** Lo (2002). i.i.d. SE = √((1 + SR²/2)/T); HAC (GMM/delta-method) SE used for the CI and p-value. Annualised by √(periods per year).
- **Assumptions:** stationary returns; moments exist.
- **If they fail:** skewed / fat-tailed (Jarque-Bera rejects) → add `qrkit stats bootstrap --statistic sharpe --seed S`; for selection among variants use the deflated Sharpe (`qrkit validate`, see backtest-validation).

## 3. Is a series stationary / mean-reverting?

- **Test:** `qrkit stats stationarity --series <file> --column spread` runs ADF (H0 unit root) and KPSS (H0 stationary).
- **Decision:** stationary only if ADF rejects **and** KPSS does not; non-stationary only if KPSS rejects **and** ADF does not; otherwise inconclusive.
- **Supporting evidence:** `qrkit meanrev variance-ratio` (Lo-MacKinlay, robust; VR < 1 supports reversion) and `qrkit meanrev half-life`. The Hurst exponent is descriptive, never a test.
- **Pairs:** use `qrkit meanrev engle-granger` (both directions, MacKinnon critical values), not ADF on a spread built with a full-sample hedge ratio: ADF critical values are wrong for estimated residuals.
- **If they fail:** trend in the series → `regression="ct"` is not exposed; detrend explicitly in the hypothesis or treat as inconclusive. A Kalman-filter spread almost always looks stationary (it is a prediction error); a test on it is not evidence.

## 4. Is there autocorrelation?

- **Test:** `qrkit stats ljung-box --series <file> --column <c> --lags 10` (H0: no autocorrelation up to lag 10).
- **Use:** diagnostic for returns (affects standard errors) and for residuals of a model.
- **If present:** use HAC errors (already default) and a block bootstrap; never a plain t-test.

## 5. Does y depend on x? (regression, exposure)

- **Test:** `qrkit stats ols --series y.csv --column y --x x.csv:col1 --x f.csv:col2 [--lags L]` — OLS with Newey-West errors; reports each coefficient with t, p, CI, and R².
- **Exposure / alpha:** `qrkit exposure` (backtest-validation) regresses net returns on the market proxy and factor file.
- **Pooled panels** (many assets × dates): `qrkit momentum tsmom` uses Driscoll-Kraay errors, robust to cross-sectional correlation. Do not pool a panel with plain OLS errors.
- **If assumptions fail:** residual autocorrelation beyond lags → increase lags; non-stationary regressors (prices, not returns) → spurious regression: regress returns on returns, or test cointegration instead.

## 6. Does a signal predict returns? (rank IC)

- **Test:** `qrkit momentum ic --signal <signal.csv> --horizon H --step S` — Spearman rank IC per date, mean IC tested with Newey-West lags ≥ H/S.
- **Report:** mean IC, IC IR, t, p, CI, number of dates.
- **If assumptions fail:** few assets per date (< 20) → IC is noisy; report it and prefer a portfolio test.

## 7. Multiple testing

| Situation | Method | Command |
|---|---|---|
| A few confirmatory tests (both EG directions, 3 holding periods) | Holm (family-wise error) | `qrkit stats multiple --outputs a.json b.json --method holm` |
| A screen of many candidates (pairs, signals) | Benjamini-Hochberg FDR | `qrkit stats multiple --pvalues screen.csv --method bh` |
| Choosing the best of N strategy variants by Sharpe | Deflated Sharpe ratio | `qrkit validate --backtest ...` (uses N from trials.csv) |

Survivors of a BH screen are candidates, not discoveries: confirm them out of sample.

## 8. Assumption failures: what to do

| qrkit assumption check fails | Consequence | Action |
|---|---|---|
| `sample_size` | Asymptotic tests unreliable | Bootstrap; say the sample is short; check power in the hypothesis |
| `no_autocorrelation (Ljung-Box)` | Plain SEs too small | HAC errors (default), block bootstrap, lags ≥ overlap |
| `normality (Jarque-Bera)` | Sharpe SE and t-tests less accurate in small samples | Bootstrap CI; report skew and kurtosis; deflated Sharpe accounts for them |
| `constant_variance (Levene, halves)` | Regime change; pooled results mislead | HAC errors; report sub-periods and volatility regimes |
| ADF and KPSS disagree | No conclusion on stationarity | Report inconclusive; use variance ratio and half-life as supporting evidence only |

## 9. References

- Newey, W. & West, K. (1987, 1994): HAC covariance and lag selection. *Econometrica* 55(3); *Review of Economic Studies* 61(4).
- Lo, A. (2002): The Statistics of Sharpe Ratios. *Financial Analysts Journal* 58(4).
- Politis, D. & Romano, J. (1994): The Stationary Bootstrap. *JASA* 89(428); Politis & White (2004) block length, *Econometric Reviews* 23(1).
- Kwiatkowski, Phillips, Schmidt & Shin (1992): KPSS. *Journal of Econometrics* 54.
- Holm, S. (1979), *Scandinavian Journal of Statistics* 6(2); Benjamini, Y. & Hochberg, Y. (1995), *JRSS B* 57(1).
- Driscoll, J. & Kraay, A. (1998): panel HAC errors. *Review of Economics and Statistics* 80(4).
- Harvey, C., Liu, Y. & Zhu, H. (2016): …and the Cross-Section of Expected Returns. *RFS* 29(1).
