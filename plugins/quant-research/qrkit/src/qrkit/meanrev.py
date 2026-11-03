"""Mean-reversion methods: Engle-Granger, variance ratio, half-life, hedge ratio, z-score.

Point-in-time rule: every estimate dated t uses data dated <= t only, and every
hedge ratio applied at t was estimated on data dated < t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint


def _fit(y: np.ndarray, x: np.ndarray, method: str) -> tuple[float, float]:
    """Return (alpha, beta) for y = alpha + beta x."""
    if method == "ols":
        X = np.column_stack([np.ones(len(x)), x])
        a, b = np.linalg.lstsq(X, y, rcond=None)[0]
        return float(a), float(b)
    if method == "tls":
        xm, ym = x.mean(), y.mean()
        sxx, syy = np.var(x), np.var(y)
        sxy = np.mean((x - xm) * (y - ym))
        if sxy == 0:
            return float(ym), 0.0
        b = (syy - sxx + np.sqrt((syy - sxx) ** 2 + 4 * sxy**2)) / (2 * sxy)
        return float(ym - b * xm), float(b)
    raise ValueError("method must be ols or tls")


def engle_granger(a: pd.Series, b: pd.Series, alpha: float = 0.05) -> dict:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    res = {}
    for name, y, x in (("a_on_b", df["a"], df["b"]), ("b_on_a", df["b"], df["a"])):
        stat, p, crit = coint(y, x, trend="c", autolag="aic")
        al, be = _fit(y.values, x.values, "ols")
        res[name] = {"statistic": float(stat), "p_value": float(p), "critical_values": {"1%": float(crit[0]), "5%": float(crit[1]), "10%": float(crit[2])},
                     "beta": be, "alpha": al}
    both = res["a_on_b"]["p_value"] < alpha and res["b_on_a"]["p_value"] < alpha
    either = res["a_on_b"]["p_value"] < alpha or res["b_on_a"]["p_value"] < alpha
    verdict = ("cointegrated in both directions" if both else
               "direction-dependent result: treat as not cointegrated" if either else "not cointegrated")
    return {"test": "Engle-Granger (MacKinnon critical values), both directions", "h0": "no cointegration",
            "results": res, "p_value": max(res["a_on_b"]["p_value"], res["b_on_a"]["p_value"]),
            "statistic": max(res["a_on_b"]["statistic"], res["b_on_a"]["statistic"]),
            "statistic_note": "the weaker (less negative) of the two directions; p_value is the larger of the two",
            "verdict": verdict, "alpha": alpha, "n": int(len(df)),
            "reference": "Engle & Granger (1987); MacKinnon (2010) critical values"}


def variance_ratio(levels: pd.Series, lags: int = 5) -> dict:
    """Lo-MacKinlay variance ratio on a level series (log price or spread), heteroskedasticity-robust."""
    from arch.unitroot import VarianceRatio

    vr = VarianceRatio(np.asarray(levels, float), lags=lags, trend="c", robust=True, overlap=True)
    z = float(vr.stat)
    from scipy.stats import norm

    return {"test": "Lo-MacKinlay variance ratio (robust)", "h0": "random walk (VR = 1)", "vr": float(vr.vr), "statistic": z,
            "p_value": float(vr.pvalue), "p_value_vr_below_1": float(norm.cdf(z)), "p_value_vr_above_1": float(1 - norm.cdf(z)),
            "lags": lags, "n": int(len(levels)),
            "interpretation": "VR < 1 supports mean reversion, VR > 1 supports momentum",
            "reference": "Lo & MacKinlay (1988) Review of Financial Studies 1(1)"}


def half_life(s: pd.Series, holding_period: int | None = None) -> dict:
    s = pd.Series(np.asarray(s, float)).dropna()
    ds = s.diff().dropna()
    lag = s.shift(1).dropna().loc[ds.index]
    m = sm.OLS(ds.values, sm.add_constant(lag.values)).fit()
    lam = float(m.params[1])
    hl = float(-np.log(2) / lam) if lam < 0 else None
    n = len(s)
    checks = [
        {"check": "lambda_negative_and_significant", "passed": bool(lam < 0 and m.pvalues[1] < 0.05),
         "detail": f"lambda {lam:.5f}, t {m.tvalues[1]:.2f} (plain OLS t; use ADF p-values for inference)"},
        {"check": "half_life_short_vs_sample", "passed": bool(hl is not None and hl < n / 10),
         "detail": f"half-life {hl if hl is None else round(hl, 1)} vs sample {n}; need < n/10 for many independent reversions"},
    ]
    if holding_period:
        checks.append({"check": "half_life_vs_holding_period", "passed": bool(hl is not None and hl <= 2 * holding_period),
                       "detail": f"half-life {hl} vs holding period {holding_period}"})
    return {"method": "AR(1): dS_t = c + lambda S_(t-1) + e; half-life = -ln 2 / lambda", "lambda": lam, "half_life": hl,
            "lambda_t": float(m.tvalues[1]), "n": n, "checks": checks}


def hedge_ratio(a: pd.Series, b: pd.Series, mode: str = "static", method: str = "ols", formation: int = 252,
                window: int = 120, refit_every: int | None = None) -> pd.DataFrame:
    """Point-in-time hedge ratio. Spread = a - alpha - beta * b (inputs usually log prices).

    static : fit on the first `formation` bars, frozen; if refit_every is set, refit
             walk-forward every `refit_every` bars on the previous `formation` bars.
    rolling: refit every bar on the previous `window` bars (window is a parameter: every
             length tried is a separate trial).
    Rows inside the first formation/window are dropped (no estimate exists yet).
    """
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    n = len(df)
    A, B = df["a"].values, df["b"].values
    alpha = np.full(n, np.nan)
    beta = np.full(n, np.nan)
    if mode == "static":
        step = refit_every or n
        for start in range(formation, n, step):
            al, be = _fit(A[start - formation:start], B[start - formation:start], method)
            alpha[start:start + step] = al
            beta[start:start + step] = be
    elif mode == "rolling":
        for t in range(window, n):
            alpha[t], beta[t] = _fit(A[t - window:t], B[t - window:t], method)
    else:
        raise ValueError("mode must be static or rolling")
    out = pd.DataFrame({"date": df.index, "a": A, "b": B, "alpha": alpha, "beta": beta})
    out["spread"] = out["a"] - out["alpha"] - out["beta"] * out["b"]
    return out.dropna().reset_index(drop=True)


def hedge_turnover(beta: pd.Series, ppy: int = 252) -> dict:
    d = beta.diff().abs().dropna()
    yrs = max(len(beta) / ppy, 1e-9)
    return {"sum_abs_dbeta": float(d.sum()), "abs_dbeta_per_year": float(d.sum() / yrs), "n_changes": int((d > 0).sum())}


def zscore(spread: pd.Series, window: int = 60) -> pd.Series:
    """Trailing z-score: mean and std from the last `window` bars up to and including t."""
    m = spread.rolling(window, min_periods=window).mean()
    s = spread.rolling(window, min_periods=window).std(ddof=1)
    return (spread - m) / s


def pairs_weights(df: pd.DataFrame, asset_a: str, asset_b: str, entry: float = 2.0, exit: float = 0.5,
                  stop: float | None = None) -> pd.DataFrame:
    """Weights from a z-scored spread. z > entry: short spread; z < -entry: long spread; |z| < exit: flat.

    Leg weights: w_a = pos / (1 + |beta|), w_b = -pos * beta / (1 + |beta|), so every change in
    beta changes both legs and is charged as turnover by the backtest.
    """
    pos = 0
    rows = []
    for r in df.itertuples():
        z = r.z
        if np.isnan(z):
            p = 0
        elif pos == 0:
            p = -1 if z > entry else 1 if z < -entry else 0
        else:
            p = 0 if abs(z) < exit or (stop is not None and abs(z) > stop) else pos
        pos = p
        g = 1 + abs(r.beta)
        rows.append((r.date, asset_a, pos / g))
        rows.append((r.date, asset_b, -pos * r.beta / g))
    return pd.DataFrame(rows, columns=["date", "asset", "weight"])
