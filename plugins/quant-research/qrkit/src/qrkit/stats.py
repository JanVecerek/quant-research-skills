"""Statistical tests. Every result: statistic, p-value, CI or effect size, assumption checks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as st
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import adfuller, kpss


def nw_lags(n: int) -> int:
    """Newey-West (1994) rule of thumb."""
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def _assume(name, passed, detail, statistic=None, p_value=None):
    return {"check": name, "passed": bool(passed), "detail": detail, "statistic": statistic, "p_value": p_value}


def basic_assumptions(x: np.ndarray, lags: int | None = None) -> list[dict]:
    x = np.asarray(x, float)
    n = len(x)
    out = [_assume("sample_size", n >= 30, f"n = {n}")]
    if n > 10:
        lb = acorr_ljungbox(x, lags=[min(10, n // 5)], return_df=True)
        p = float(lb["lb_pvalue"].iloc[0])
        out.append(_assume("no_autocorrelation (Ljung-Box)", p > 0.05,
                           "autocorrelation present: use HAC errors / block bootstrap" if p <= 0.05 else "no evidence of autocorrelation",
                           float(lb["lb_stat"].iloc[0]), p))
        jb = st.jarque_bera(x)
        out.append(_assume("normality (Jarque-Bera)", jb.pvalue > 0.05,
                           f"skew {st.skew(x):.2f}, excess kurtosis {st.kurtosis(x):.2f}", float(jb.statistic), float(jb.pvalue)))
        half = n // 2
        lev = st.levene(x[:half], x[half:])
        out.append(_assume("constant_variance (Levene, halves)", lev.pvalue > 0.05,
                           "variance differs between halves: prefer HAC/robust errors" if lev.pvalue <= 0.05 else "no evidence of variance change",
                           float(lev.statistic), float(lev.pvalue)))
    return out


# ------------------------------------------------------------------ stationarity


def adf(x: pd.Series, regression: str = "c") -> dict:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        r = adfuller(np.asarray(x, float), regression=regression, autolag="AIC")
    return {"test": "ADF", "h0": "unit root (non-stationary)", "statistic": float(r[0]), "p_value": float(r[1]),
            "lags_used": int(r[2]), "n": int(r[3]), "critical_values": {k: float(v) for k, v in r[4].items()},
            "regression": regression}


def kpss_test(x: pd.Series, regression: str = "c") -> dict:
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = kpss(np.asarray(x, float), regression=regression, nlags="auto")
    note = "p-value is at the edge of the lookup table (true p is beyond it)" if w else ""
    return {"test": "KPSS", "h0": "stationary", "statistic": float(r[0]), "p_value": float(r[1]), "lags_used": int(r[2]),
            "critical_values": {k: float(v) for k, v in r[3].items()}, "regression": regression, "note": note}


def stationarity(x: pd.Series, alpha: float = 0.05, regression: str = "c") -> dict:
    a, k = adf(x, regression), kpss_test(x, regression)
    adf_rej, kpss_rej = a["p_value"] < alpha, k["p_value"] < alpha
    if adf_rej and not kpss_rej:
        verdict = "stationary (ADF and KPSS agree)"
    elif kpss_rej and not adf_rej:
        verdict = "non-stationary (ADF and KPSS agree)"
    else:
        verdict = "inconclusive (ADF and KPSS disagree): do not conclude either way"
    return {"adf": a, "kpss": k, "verdict": verdict, "agree": adf_rej != kpss_rej, "alpha": alpha,
            "assumptions": basic_assumptions(np.diff(np.asarray(x, float)))}


def ljung_box(x: pd.Series, lags: int = 10) -> dict:
    lb = acorr_ljungbox(np.asarray(x, float), lags=[lags], return_df=True)
    return {"test": "Ljung-Box", "h0": f"no autocorrelation up to lag {lags}", "statistic": float(lb["lb_stat"].iloc[0]),
            "p_value": float(lb["lb_pvalue"].iloc[0]), "lags": lags, "n": int(len(x))}


# ------------------------------------------------------------------ mean / regression


def hac_mean(x: pd.Series, lags: int | None = None, alternative: str = "greater", alpha: float = 0.05,
             ppy: int = 252) -> dict:
    """Test the mean of a return series with Newey-West HAC standard errors."""
    y = np.asarray(x, float)
    n = len(y)
    L = nw_lags(n) if lags is None else int(lags)
    m = sm.OLS(y, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    mean, se = float(m.params[0]), float(m.bse[0])
    t = mean / se if se > 0 else np.nan
    if alternative == "greater":
        p = float(1 - st.norm.cdf(t))
    elif alternative == "less":
        p = float(st.norm.cdf(t))
    else:
        p = float(2 * (1 - st.norm.cdf(abs(t))))
    z = st.norm.ppf(1 - alpha / 2)
    sd = float(np.std(y, ddof=1))
    return {
        "test": "mean with Newey-West HAC errors",
        "h0": "mean = 0",
        "alternative": alternative,
        "statistic": t,
        "p_value": p,
        "mean_per_period": mean,
        "se_per_period": se,
        "ci_per_period": [mean - z * se, mean + z * se],
        "mean_annualised": mean * ppy,
        "ci_annualised": [(mean - z * se) * ppy, (mean + z * se) * ppy],
        "effect_size_sharpe_annualised": mean / sd * np.sqrt(ppy) if sd > 0 else None,
        "hac_lags": L,
        "n": n,
        "assumptions": basic_assumptions(y),
    }


def ols_hac(y: pd.Series, X: pd.DataFrame, lags: int | None = None, alpha: float = 0.05) -> dict:
    df = pd.concat([y.rename("y"), X], axis=1, join="inner").dropna()
    n = len(df)
    L = nw_lags(n) if lags is None else int(lags)
    Xc = sm.add_constant(df[X.columns])
    m = sm.OLS(df["y"], Xc).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    ci = m.conf_int(alpha)
    coefs = {
        k: {"coef": float(m.params[k]), "se": float(m.bse[k]), "t": float(m.tvalues[k]), "p_value": float(m.pvalues[k]),
            "ci": [float(ci.loc[k, 0]), float(ci.loc[k, 1])]}
        for k in m.params.index
    }
    return {"test": "OLS with Newey-West HAC errors", "coefficients": coefs, "r2": float(m.rsquared), "n": n,
            "hac_lags": L, "assumptions": basic_assumptions(np.asarray(m.resid))}


# ------------------------------------------------------------------ bootstrap


def block_bootstrap(x: pd.Series, statistic: str = "sharpe", reps: int = 5000, seed: int = 0, alpha: float = 0.05,
                    block: float | None = None, ppy: int = 252) -> dict:
    """Stationary block bootstrap (Politis-Romano 1994) CI; block length by Politis-White (2004)."""
    from arch.bootstrap import StationaryBootstrap, optimal_block_length

    y = np.asarray(x, float)
    if block is None:
        block = float(optimal_block_length(y)["stationary"].iloc[0])
        block = max(block, 1.0)

    def f(a):
        if statistic == "mean":
            return np.array([a.mean() * ppy])
        sd = a.std(ddof=1)
        return np.array([a.mean() / sd * np.sqrt(ppy) if sd > 0 else 0.0])

    bs = StationaryBootstrap(block, y, seed=np.random.default_rng(seed))
    ci = bs.conf_int(f, reps=reps, method="percentile", size=1 - alpha)
    # one-sided p-value for stat > 0 via centred bootstrap distribution
    bs2 = StationaryBootstrap(block, y - y.mean(), seed=np.random.default_rng(seed + 1))
    null = np.array([f(d[0][0])[0] for d in bs2.bootstrap(reps)])
    est = float(f(y)[0])
    p = float((np.sum(null >= est) + 1) / (reps + 1))
    return {"test": f"stationary block bootstrap of {statistic}", "estimate": est, "ci": [float(ci[0, 0]), float(ci[1, 0])],
            "p_value_greater_than_zero": p, "block_length": block, "reps": reps, "seed": seed, "n": int(len(y)),
            "assumptions": basic_assumptions(y)}


# ------------------------------------------------------------------ multiple testing


def multiple(pvalues: dict[str, float], method: str = "holm", alpha: float = 0.05) -> dict:
    names = list(pvalues)
    p = np.array([pvalues[k] for k in names], float)
    meth = {"holm": "holm", "bh": "fdr_bh", "bonferroni": "bonferroni"}[method]
    rej, padj, _, _ = multipletests(p, alpha=alpha, method=meth)
    return {"method": method, "alpha": alpha, "n_tests": len(p),
            "results": [{"name": n, "p_value": float(pi), "p_adjusted": float(pa), "reject": bool(r)}
                        for n, pi, pa, r in zip(names, p, padj, rej)],
            "n_rejected": int(rej.sum())}


# ------------------------------------------------------------------ Sharpe ratio


def sharpe(x: pd.Series, ppy: int = 252, alpha: float = 0.05, lags: int | None = None) -> dict:
    """Sharpe ratio with Lo (2002) standard errors.

    iid:     Var(SR) = (1 + SR^2/2) / T
    non-iid: GMM / delta method on (mu, sigma^2) with Newey-West covariance of the
             moment conditions (Lo 2002, section 3). Used for the CI and p-value.
    Annualised by sqrt(periods_per_year); the SE scales the same way.
    """
    y = np.asarray(x, float)
    T = len(y)
    mu, sd = y.mean(), y.std(ddof=1)
    sr = mu / sd if sd > 0 else np.nan
    se_iid = np.sqrt((1 + 0.5 * sr**2) / T)
    L = nw_lags(T) if lags is None else int(lags)
    u = np.column_stack([y - mu, (y - mu) ** 2 - sd**2])
    S = u.T @ u / T
    for k in range(1, L + 1):
        w = 1 - k / (L + 1)
        G = u[k:].T @ u[:-k] / T
        S += w * (G + G.T)
    grad = np.array([1 / sd, -mu / (2 * sd**3)])
    se_gmm = float(np.sqrt(grad @ S @ grad / T))
    a = np.sqrt(ppy)
    z = st.norm.ppf(1 - alpha / 2)
    return {
        "sharpe_per_period": sr,
        "sharpe_annualised": sr * a,
        "se_iid_annualised": se_iid * a,
        "se_hac_annualised": se_gmm * a,
        "ci_annualised_hac": [(sr - z * se_gmm) * a, (sr + z * se_gmm) * a],
        "statistic": sr / se_gmm if se_gmm > 0 else None,
        "p_value_greater_than_zero": float(1 - st.norm.cdf(sr / se_gmm)) if se_gmm > 0 else None,
        "n": T,
        "hac_lags": L,
        "skew": float(st.skew(y)),
        "excess_kurtosis": float(st.kurtosis(y)),
        "reference": "Lo, A. (2002) The Statistics of Sharpe Ratios, Financial Analysts Journal 58(4)",
        "assumptions": basic_assumptions(y),
    }
