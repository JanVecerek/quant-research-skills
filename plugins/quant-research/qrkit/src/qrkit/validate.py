"""Validation: walk-forward stability, PSR, deflated Sharpe, exposure, red flags."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from .stats import hac_mean, ols_hac, sharpe

EULER_GAMMA = 0.5772156649015329


def psr(r: pd.Series, sr_benchmark_per_period: float = 0.0) -> float:
    """Probabilistic Sharpe ratio (Bailey & Lopez de Prado 2012), per-period units."""
    y = np.asarray(r, float)
    T = len(y)
    sr = y.mean() / y.std(ddof=1)
    g3 = st.skew(y)
    g4 = st.kurtosis(y, fisher=False)
    den = np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    return float(st.norm.cdf((sr - sr_benchmark_per_period) * np.sqrt(T - 1) / den))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] under the null across N independent trials (Bailey & Lopez de Prado 2014, eq. 2)."""
    if n_trials <= 1:
        return 0.0
    z1 = st.norm.ppf(1 - 1 / n_trials)
    z2 = st.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(np.sqrt(var_sr) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe(r: pd.Series, n_trials: int, trial_sharpes_per_period: list[float] | None = None) -> dict:
    y = np.asarray(r, float)
    T = len(y)
    sr = y.mean() / y.std(ddof=1)
    if trial_sharpes_per_period and len(trial_sharpes_per_period) >= 2:
        var_sr = float(np.var(trial_sharpes_per_period, ddof=1))
        src = "variance of Sharpe ratios across logged trials"
    else:
        var_sr = float((1 + 0.5 * sr**2) / T)
        src = "estimator variance (1 + SR^2/2)/T: fewer than 2 logged trial Sharpes"
    sr0 = expected_max_sharpe(n_trials, var_sr)
    return {"dsr": psr(y, sr0), "psr_vs_zero": psr(y, 0.0), "n_trials": int(n_trials),
            "sr0_per_period": sr0, "sharpe_per_period": float(sr), "var_sr_source": src, "var_sr": var_sr,
            "reference": "Bailey & Lopez de Prado (2014) The Deflated Sharpe Ratio, Journal of Portfolio Management 40(5)"}


def walk_forward(r: pd.Series, folds: int = 5, ppy: int = 252) -> dict:
    parts = np.array_split(np.arange(len(r)), folds)
    rows = []
    for i, idx in enumerate(parts):
        seg = r.iloc[idx]
        sd = seg.std(ddof=1)
        rows.append({"fold": i + 1, "start": seg.index.min(), "end": seg.index.max(),
                     "sharpe_annualised": float(seg.mean() / sd * np.sqrt(ppy)) if sd > 0 else None,
                     "mean_annualised": float(seg.mean() * ppy)})
    pos = sum(1 for x in rows if (x["sharpe_annualised"] or 0) > 0)
    return {"folds": rows, "fraction_positive": pos / folds,
            "stable": pos >= int(np.ceil(0.6 * folds)),
            "note": "sequential in-sample folds; fitted parameters must be re-estimated per fold by the strategy engine (qrkit meanrev hedge-ratio does this for hedge ratios)"}


def exposure(r: pd.Series, market: pd.Series, factors: pd.DataFrame | None = None) -> dict:
    X = market.rename("market").to_frame()
    if factors is not None:
        X = factors if "market" in factors.columns or "mkt" in factors.columns else pd.concat([X, factors], axis=1)
    res = ols_hac(r, X)
    alpha = res["coefficients"]["const"]
    status = "PASS" if factors is not None else "WARN"
    return {"status": status, "regressors": list(X.columns), "alpha_per_period": alpha["coef"],
            "alpha_t": alpha["t"], "alpha_p_value": alpha["p_value"], "regression": res,
            "note": ("factor file supplied" if factors is not None else
                     "no factor file: only the equal-weight market proxy was controlled for; do not call the result alpha")}


def red_flags(bt: pd.DataFrame, ppy: int, sharpe_delayed_net: float | None = None, sweep: pd.DataFrame | None = None) -> list[dict]:
    flags = []
    net = bt["net"]
    sd = net.std(ddof=1)
    srn = float(net.mean() / sd * np.sqrt(ppy)) if sd > 0 else 0.0
    if ppy >= 200 and srn > 2:
        flags.append({"flag": "sharpe_above_2_daily", "detail": f"net Sharpe {srn:.2f} on daily data: look for look-ahead, stale prices, missing costs or survivorship before believing it"})
    by_year = net.groupby(net.index.year).sum()
    total = by_year.sum()
    if total > 0 and len(by_year) >= 2:
        best = by_year.idxmax()
        rest = total - by_year.max()
        if by_year.max() > 0.5 * total or rest <= 0:
            flags.append({"flag": "driven_by_one_period", "detail": f"{best} contributes {by_year.max() / total:.0%} of net P&L; without it the total is {rest:.4f}"})
    if sharpe_delayed_net is not None and srn > 0:
        if sharpe_delayed_net <= 0 or sharpe_delayed_net < 0.5 * srn:
            flags.append({"flag": "edge_lost_with_one_bar_delay", "detail": f"net Sharpe {srn:.2f} -> {sharpe_delayed_net:.2f} with one extra bar of execution delay"})
    if sweep is not None and len(sweep) >= 3:
        s = sweep.sort_values(sweep.columns[0]).reset_index(drop=True)
        mcol = s.columns[-1]
        i = int(s[mcol].idxmax())
        nb = [s.loc[j, mcol] for j in (i - 1, i + 1) if 0 <= j < len(s)]
        best = s.loc[i, mcol]
        if best > 0 and nb and max(nb) < 0.5 * best:
            flags.append({"flag": "driven_by_one_parameter_value", "detail": f"best {s.columns[0]}={s.loc[i, s.columns[0]]} ({best:.3f}) but neighbours reach only {max(nb):.3f}"})
    return flags


def oos_result(net: pd.Series, alpha: float, ppy: int) -> dict:
    t = hac_mean(net, alternative="greater", alpha=alpha, ppy=ppy)
    s = sharpe(net, ppy=ppy, alpha=alpha)
    return {"passed": bool(t["p_value"] < alpha), "mean_test": t, "sharpe": s,
            "sharpe_annualised": s["sharpe_annualised"], "sharpe_ci": s["ci_annualised_hac"]}
