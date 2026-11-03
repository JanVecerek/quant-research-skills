---
name: statistical-testing
description: Use when choosing or running a statistical test on financial time series — t-test or significance of returns, Sharpe ratio confidence interval or standard error, stationarity (ADF, KPSS), autocorrelation (Ljung-Box), regression with Newey-West / HAC errors, bootstrap, or multiple-testing correction (Holm, Benjamini-Hochberg, many variants, p-hacking). Also use when checking a test's assumptions on autocorrelated or fat-tailed returns.
---

# Statistical testing

This skill owns **the choice of test, its assumptions, and multiple-testing correction** (`qrkit stats ...`). Step order belongs to `quant-research:research-workflow`; strategy-specific tests (cointegration, variance ratio, rank IC) are run via `quant-research:strategy-methods` but chosen with the decision tree here.

**Core principle:** financial returns are autocorrelated, heteroskedastic and fat-tailed, and you rarely run only one test. A test that ignores either fact reports confidence you do not have.

`qrkit` means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled). All `stats` commands read only the in-sample window of the locked hypothesis.

## Choose the test

Read `references/methods.md` for the full decision tree (question → test → assumptions → what to do when they fail). Short version:

| Question | qrkit command | Never use |
|---|---|---|
| Is the mean return > 0? | `qrkit stats hac-mean --series f.csv --column net` | plain t-test on daily returns |
| How uncertain is the Sharpe ratio? | `qrkit stats sharpe --series f.csv --column net` (Lo 2002, HAC) | a Sharpe without an interval |
| Same, with fat tails / short sample | `qrkit stats bootstrap --series f.csv --column net --seed 1` | i.i.d. bootstrap (destroys autocorrelation) |
| Is this series stationary? | `qrkit stats stationarity --series f.csv --column spread` (ADF + KPSS) | ADF alone; Hurst exponent as a test |
| Is there autocorrelation? | `qrkit stats ljung-box --series ... --lags 10` | eyeballing an ACF plot |
| Does y depend on x? | `qrkit stats ols --series y.csv --column y --x x.csv:col` (HAC errors) | OLS with default standard errors |
| Several tests or variants | `qrkit stats multiple --outputs qr-output/*.json --method holm` (or `bh` for screens) | reporting the best p-value alone |

`--asset NAME --transform log|logret|level` uses a price from the hypothesis data instead of a file.

## Rules

1. **The pre-registered test is the one in `hypothesis.yaml`.** Run it once, on the in-sample window, and report its p-value against `alpha`. Other tests are diagnostics; they do not replace it if it fails. Why: switching to whichever test passes is p-hacking.
2. **Report every result with statistic, p-value, confidence interval or effect size, and the assumption checks** from the qrkit output. A p-value alone says nothing about size; a Sharpe alone says nothing about uncertainty.
3. **Read the `assumptions` block and act on failures** using the table in `references/methods.md`. Example: Ljung-Box rejects → you are already using HAC errors; if the sample is short too, add the block bootstrap.
4. **Correct for multiple testing whenever you ran more than one test of the same question**: several windows, both directions, several assets, several parameter values. Use Holm to control the family-wise error for a handful of confirmatory tests and BH-FDR for screens (many pairs, many signals); survivors of a screen still need confirmation out of sample. Why: twenty tests at α = 0.05 produce one false positive on average.
5. **Count tests you ran before locking too.** Exploratory looks are trials. Mention them, and prefer the stricter correction when there were many.
6. **Stationarity: conclude only when ADF and KPSS agree.** qrkit's `stationarity` verdict says *inconclusive* when they disagree; report it as inconclusive.
7. **Random procedures need `--seed`.** qrkit refuses to run a bootstrap without one, so results are reproducible.

## Interpretation

| Output | Say | Do not say |
|---|---|---|
| p = 0.03, CI [0.1, 1.9] | "significant at 5%, but the interval is wide: the true Sharpe could be 0.1" | "the strategy has a Sharpe of 1.0" |
| p = 0.2, power 0.9 | "no evidence of an effect; the test had power to detect the minimum effect" | "the strategy doesn't work" (if power is low) |
| p = 0.2, power 0.4 | "inconclusive: the sample is too short to detect the minimum effect" | "no effect" |
| 1 of 12 variants with p < 0.05 | "after Holm correction none is significant" | "variant 7 is significant" |

## Common mistakes

| Mistake | Fix |
|---|---|
| Plain t-stat alongside the HAC one, then quoting the larger | Quote only HAC; plain errors are wrong for autocorrelated returns. |
| Newey-West lags shorter than the holding period with overlapping returns | Lags ≥ holding period (qrkit's `momentum ic` sets this automatically). |
| Rolling-window cointegration tests "to check stability", uncorrected | Each window is a test; correct them or treat as descriptive only. |
| Ignoring a warning from the test library | qrkit reports edge-of-table KPSS p-values in `note`; mention it. |
| Annualising Sharpe without an interval | `qrkit stats sharpe` gives the Lo (2002) HAC interval. |
