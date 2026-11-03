"""Momentum methods: time-series and cross-sectional signals, quantile portfolios, rank IC, TSMOM regression.

Point-in-time rule: the signal dated t uses closes dated <= t - skip.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as st

from .stats import nw_lags


def ex_ante_vol(close: pd.DataFrame, com: int = 60, ppy: int = 252) -> pd.DataFrame:
    """EWMA volatility of daily returns, annualised (Moskowitz, Ooi & Pedersen 2012 use com=60)."""
    r = close.pct_change(fill_method=None)
    return r.ewm(com=com, min_periods=com).std() * np.sqrt(ppy)


def past_return(close: pd.DataFrame, lookback: int, skip: int) -> pd.DataFrame:
    return close.shift(skip) / close.shift(skip + lookback) - 1


def signal(close: pd.DataFrame, kind: str, lookback: int, skip: int, ppy: int = 252) -> tuple[pd.DataFrame, list[str]]:
    errors = []
    if skip == 0:
        errors.append(
            "momentum signal without skip period: the latest bar(s) carry short-term reversal and bid-ask bounce "
            "(Jegadeesh & Titman 1993 skip one month; 12-1 = lookback 231, skip 21 on daily data)"
        )
    pr = past_return(close, lookback, skip)
    out = pr.stack(future_stack=True).rename("past_return").to_frame()
    if kind == "ts":
        vol = ex_ante_vol(close, ppy=ppy)
        out["vol"] = vol.stack(future_stack=True)
        out["signal"] = np.sign(out["past_return"]) / out["vol"]
    elif kind == "xs":
        out["signal"] = out["past_return"]
    else:
        raise ValueError("kind must be ts or xs")
    out = out.dropna(subset=["signal"]).reset_index()
    out.columns = ["date", "asset"] + list(out.columns[2:])
    return out, errors


def _rebalance_dates(dates: pd.DatetimeIndex, every: int) -> pd.DatetimeIndex:
    return dates[::every]


def portfolio(sig: pd.DataFrame, kind: str, quantiles: int = 5, holding: int = 1, rebalance: int = 21,
              target_vol: float = 0.4, liquidity: pd.DataFrame | None = None, min_liquidity: float | None = None) -> pd.DataFrame:
    """Target weights from a signal file.

    xs: long the top quantile, short the bottom (each leg 0.5 gross), equal weight.
    ts: w = sign(past return) * target_vol / vol / N (Moskowitz-Ooi-Pedersen).
    holding > 1: Jegadeesh-Titman overlapping portfolios, average of the last `holding` cohorts.
    """
    S = sig.pivot(index="date", columns="asset", values="signal").sort_index()
    if liquidity is not None and min_liquidity is not None:
        liq = liquidity.reindex_like(S)
        S = S.where(liq >= min_liquidity)
    rdates = _rebalance_dates(S.index, rebalance)
    cohorts = []
    for d in rdates:
        s = S.loc[d].dropna()
        w = pd.Series(0.0, index=S.columns)
        if kind == "xs":
            if len(s) < quantiles * 2:
                cohorts.append(w)
                continue
            q = pd.qcut(s.rank(method="first"), quantiles, labels=False)
            top, bot = s.index[q == quantiles - 1], s.index[q == 0]
            w[top] = 0.5 / len(top)
            w[bot] = -0.5 / len(bot)
        else:
            if len(s):
                w[s.index] = s * target_vol / len(s)
        cohorts.append(w)
    W = pd.DataFrame(cohorts, index=rdates)
    if holding > 1:
        W = W.rolling(holding, min_periods=1).mean()
    out = W.stack().rename("weight").reset_index()
    out.columns = ["date", "asset", "weight"]
    return out


def rank_ic(sig: pd.DataFrame, close: pd.DataFrame, horizon: int = 21, step: int | None = None) -> dict:
    fwd = close.shift(-horizon) / close - 1
    S = sig.pivot(index="date", columns="asset", values="signal").sort_index()
    dates = S.index[:: (step or 1)]
    ics = {}
    for d in dates:
        if d not in fwd.index:
            continue
        x, y = S.loc[d], fwd.loc[d]
        m = x.notna() & y.notna()
        if m.sum() >= 5:
            ics[d] = st.spearmanr(x[m], y[m]).statistic
    ic = pd.Series(ics).dropna()
    n = len(ic)
    overlap = horizon // (step or 1)
    L = max(overlap, nw_lags(n))
    m = sm.OLS(ic.values, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    return {"test": "mean rank IC with Newey-West errors", "h0": "mean IC = 0", "mean_ic": float(ic.mean()),
            "ic_std": float(ic.std()), "ic_ir": float(ic.mean() / ic.std()) if ic.std() > 0 else None,
            "statistic": float(m.tvalues[0]), "p_value": float(1 - st.norm.cdf(m.tvalues[0])),
            "ci": [float(x) for x in m.conf_int()[0]], "n_dates": n, "horizon": horizon, "hac_lags": L,
            "note": "overlapping forward returns: Newey-West lags >= holding horizon", "series": ic}


def tsmom_regression(close: pd.DataFrame, lookback_periods: int = 12, skip_periods: int = 0, period: int = 21,
                     ppy: int = 252) -> dict:
    """Pooled regression of vol-scaled period returns on lagged vol-scaled look-back returns.

    y_{i,s} = r_{i,s} / sigma_{i,s-1};  x_{i,s} = R_{i, s-skip-L .. s-skip-1} / sigma_{i,s-1}.
    Driscoll-Kraay (time-clustered HAC) errors because residuals correlate across assets.
    Reference: Moskowitz, Ooi & Pedersen (2012), Journal of Financial Economics 104(2).
    """
    vol = ex_ante_vol(close, ppy=ppy)
    idx = close.index[::period]
    P = close.loc[idx]
    V = vol.loc[idx]
    r = P.pct_change(fill_method=None)
    past = P.shift(1 + skip_periods) / P.shift(1 + skip_periods + lookback_periods) - 1
    y = r / V.shift(1)
    x = past / V.shift(1)
    df = pd.DataFrame({"y": y.stack(future_stack=True), "x": x.stack(future_stack=True)}).dropna()
    df = df[np.isfinite(df).all(axis=1)]
    times = pd.factorize(df.index.get_level_values(0))[0]
    T = len(np.unique(times))
    L = max(nw_lags(T), 1)
    m = sm.OLS(df["y"].values, sm.add_constant(df["x"].values)).fit(cov_type="hac-groupsum",
                                                                    cov_kwds={"time": times, "maxlags": L})
    return {"test": "pooled TSMOM regression, Driscoll-Kraay errors", "h0": "slope = 0", "slope": float(m.params[1]),
            "statistic": float(m.tvalues[1]), "p_value": float(1 - st.norm.cdf(m.tvalues[1])),
            "ci": [float(v) for v in m.conf_int()[1]], "n_obs": int(len(df)), "n_periods": T, "hac_lags": L,
            "lookback_periods": lookback_periods, "skip_periods": skip_periods, "period_bars": period,
            "reference": "Moskowitz, Ooi & Pedersen (2012)"}
