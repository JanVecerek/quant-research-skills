# Costs and validation: models used by qrkit

## Contents
1. Return timing
2. Cost model
3. Break-even cost and sweep
4. Walk-forward folds
5. PSR and deflated Sharpe
6. Exposure
7. One-time OOS
8. References

## 1. Return timing

gross_{t+1} = Σ_a w_{a,t} · r_{a,t+1}, with r the simple close-to-close return. `--delay d` shifts execution by d extra bars. Turnover at t = Σ_a |w_{a,t} − w_{a,t−1}|, charged at t. Positions held on a missing price earn 0 and are counted in `periods_with_position_on_missing_price` (often delistings without a delisting return).

## 2. Cost model (from `hypothesis.yaml`)

| Component | Formula per period | Parameter |
|---|---|---|
| Half-spread | half_spread_bps · 1e-4 · turnover | `costs.half_spread_bps` |
| Commission | commission_bps · 1e-4 · turnover | `costs.commission_bps` |
| Market impact | Σ_a Y · σ_a · √(|Δw_a| · capital / ADV_a) · |Δw_a| | `costs.impact_coef` (Y), `capital`; σ = trailing 20-bar return volatility, ADV = trailing 20-bar dollar volume, both lagged one bar |
| Borrow | borrow_bps_annual · 1e-4 / periods_per_year · Σ short weights | `costs.borrow_bps_annual` |

Square-root impact with Y of order 0.5–1 is the standard empirical law (Almgren, Thum, Hauptmann & Li 2005; Tóth et al. 2011). Impact is skipped (0) when the price file has no volume; qrkit's output then shows `cost_impact` = 0 and you must say impact was not modelled.

Indicative half-spreads: large-cap US equities 1–5 bps; small caps 10–50+ bps; liquid futures ≈ 1 tick. Use the project's own estimates where available.

## 3. Break-even cost and sweep

`break_even_cost_bps_per_unit_turnover` = (Σ gross − Σ impact − Σ borrow) / Σ turnover × 1e4: the spread+commission level at which the mean net return is zero. `margin_of_safety` = break-even / assumed linear cost. The sweep scales all costs by 0, 0.5, 1, 2, 3, 5.

## 4. Walk-forward folds

`qrkit validate --folds k` splits the in-sample net returns into k sequential blocks and reports each block's Sharpe; `stable` = at least 60% of folds positive. This is a stability check of a frozen rule; any fitted parameter must be re-estimated inside each fold by the strategy itself.

## 5. PSR and deflated Sharpe

- PSR(SR*) = Φ( (SR − SR*) √(T−1) / √(1 − γ₃ SR + (γ₄ − 1)/4 · SR²) ), per-period SR, skewness γ₃, kurtosis γ₄ (Bailey & López de Prado 2012).
- DSR = PSR(SR₀) with SR₀ = √V[SR] · ((1−γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))), γ ≈ 0.5772 (Bailey & López de Prado 2014).
- N = distinct strategy variants (weights files) backtested under this hypothesis id, from `trials.csv`. V[SR] = variance of their per-period Sharpe ratios when at least two exist, otherwise the estimator variance (1 + SR²/2)/T.
- qrkit reproduces the published example (N = 100, V = 0.5/250 → SR₀ ≈ 0.1132 per day) in its test suite.

## 6. Exposure

OLS of net returns on the equal-weight market proxy (mean of the panel's asset returns) and, if supplied, the factor file's columns, with Newey-West errors. Reports alpha per period with t and p, and each beta. Status WARN without a factor file.

## 7. One-time OOS

`validate --oos` runs the backtest from the in-sample start through the OOS end and keeps only OOS periods. With `--from <weights output JSON>` it replays the recorded qrkit chain (hedge ratio → z-score → pairs weights, or signal → portfolio) with frozen parameters over IS+OOS prices, so the agent never sees OOS signals. Pass criterion: HAC t-test of the mean net OOS return, one-sided, p < α. Also reported: OOS net Sharpe with Lo (2002) HAC interval, gross and net summaries. A marker in `qr-output/oos/` blocks a second run for the same id.

## 8. References

- Almgren, R., Thum, C., Hauptmann, E. & Li, H. (2005). Direct estimation of equity market impact. *Risk* 18(7).
- Tóth, B. et al. (2011). Anomalous price impact and the critical nature of liquidity in financial markets. *Physical Review X* 1(2).
- Bailey, D. & López de Prado, M. (2012). The Sharpe ratio efficient frontier. *Journal of Risk* 15(2).
- Bailey, D. & López de Prado, M. (2014). The deflated Sharpe ratio. *Journal of Portfolio Management* 40(5).
- Bailey, D., Borwein, J., López de Prado, M. & Zhu, Q. (2017). The probability of backtest overfitting. *Journal of Computational Finance* 20(4). (PBO via CSCV is [P1].)
- Lo, A. (2002). The statistics of Sharpe ratios. *Financial Analysts Journal* 58(4).
