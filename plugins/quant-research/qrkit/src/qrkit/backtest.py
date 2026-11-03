"""Minimal reference backtester: target weights x prices -> gross and net returns.

Timing: a weight dated t is decided at the close of t and earns the return from
t to t+1 (plus `delay` extra bars of execution lag). Trades happen at the close
where the held weight changes, and are charged there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from .io import ContractError
from .stats import sharpe as sharpe_stats

COST_COLS = ["cost_spread", "cost_commission", "cost_impact", "cost_borrow"]


def weight_matrix(weights: pd.DataFrame, index: pd.DatetimeIndex, columns) -> pd.DataFrame:
    unknown = sorted(set(weights["asset"]) - set(columns))
    if unknown:
        raise ContractError(f"weights reference assets with no prices: {unknown[:10]}")
    W = weights.pivot(index="date", columns="asset", values="weight").reindex(columns=columns)
    # a listed date defines the full target book: unlisted assets on that date are 0
    W = W.fillna(0.0)
    off = W.index.difference(index)
    if len(off):
        # snap to the last price date <= weight date (weights on non-trading days)
        pos = index.searchsorted(off, side="right") - 1
        if (pos < 0).any():
            raise ContractError("weights dated before the first price date")
        W = W.rename(index=dict(zip(off, index[pos])))
        W = W.groupby(level=0).last()
    W = W.reindex(index).ffill().fillna(0.0)
    return W


def market_proxy(close: pd.DataFrame) -> pd.Series:
    return close.pct_change(fill_method=None).mean(axis=1).rename("market")


def run(close: pd.DataFrame, weights: pd.DataFrame, costs: dict, capital: float, delay: int = 0,
        volume: pd.DataFrame | None = None, cost_multiplier: float = 1.0) -> pd.DataFrame:
    R = close.pct_change(fill_method=None)
    W = weight_matrix(weights, close.index, close.columns).shift(delay).fillna(0.0)
    held = W.shift(1).fillna(0.0)
    missing_ret = (held != 0) & R.isna()
    gross = (held * R.fillna(0.0)).sum(axis=1)
    dW = (W - W.shift(1).fillna(0.0)).abs()
    turnover = dW.sum(axis=1)
    k = cost_multiplier * 1e-4
    out = pd.DataFrame(index=close.index)
    out["gross"] = gross
    out["turnover"] = turnover
    out["cost_spread"] = k * float(costs.get("half_spread_bps", 0)) * turnover
    out["cost_commission"] = k * float(costs.get("commission_bps", 0)) * turnover
    impact_coef = float(costs.get("impact_coef", 0))
    if impact_coef and volume is not None:
        sig = R.rolling(20, min_periods=10).std().shift(1)
        adv = (close * volume).rolling(20, min_periods=10).mean().shift(1)
        part = (dW * capital / adv).clip(lower=0)
        imp = cost_multiplier * impact_coef * sig * np.sqrt(part) * dW
        out["cost_impact"] = imp.fillna(0.0).sum(axis=1)
    else:
        out["cost_impact"] = 0.0
    ppy = int(costs.get("_ppy", 252))
    out["cost_borrow"] = k * float(costs.get("borrow_bps_annual", 0)) / ppy * held.clip(upper=0).abs().sum(axis=1)
    out["net"] = out["gross"] - out[COST_COLS].sum(axis=1)
    out["gross_exposure"] = held.abs().sum(axis=1)
    out["net_exposure"] = held.sum(axis=1)
    out["held_on_missing_price"] = missing_ret.sum(axis=1)
    out = out.iloc[1 + delay:]
    # drop leading period before any position is held
    active = (out["gross_exposure"] > 0) | (out["turnover"] > 0)
    if active.any():
        out = out.loc[active.idxmax():]
    out.index.name = "date"
    return out


def max_drawdown(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def summarize(bt: pd.DataFrame, ppy: int = 252, market: pd.Series | None = None) -> dict:
    res = {}
    for col in ("gross", "net"):
        r = bt[col]
        s = sharpe_stats(r, ppy=ppy)
        res[col] = {
            "mean_annualised": float(r.mean() * ppy),
            "vol_annualised": float(r.std(ddof=1) * np.sqrt(ppy)),
            "sharpe_annualised": s["sharpe_annualised"],
            "sharpe_ci_95_hac": s["ci_annualised_hac"],
            "max_drawdown": max_drawdown(r),
            "skew": float(st.skew(r)),
            "excess_kurtosis": float(st.kurtosis(r)),
            "hit_rate": float((r > 0).mean()),
        }
    yrs = len(bt) / ppy
    res["turnover_per_year"] = float(bt["turnover"].sum() / yrs)
    res["costs_per_year"] = {c: float(bt[c].sum() / yrs) for c in COST_COLS}
    lin = (bt["cost_spread"] + bt["cost_commission"]).sum()
    nonlin = (bt["cost_impact"] + bt["cost_borrow"]).sum()
    to = bt["turnover"].sum()
    res["break_even_cost_bps_per_unit_turnover"] = float((bt["gross"].sum() - nonlin) / to * 1e4) if to > 0 else None
    res["break_even_note"] = "spread+commission (bps per unit of one-way turnover) at which mean net return = 0, impact and borrow held fixed"
    res["linear_cost_share_of_gross"] = float(lin / bt["gross"].sum()) if bt["gross"].sum() != 0 else None
    by_year = bt["net"].groupby(bt.index.year).sum()
    res["net_by_year"] = {str(k): float(v) for k, v in by_year.items()}
    res["n_periods"] = int(len(bt))
    res["start"], res["end"] = bt.index.min(), bt.index.max()
    res["periods_with_position_on_missing_price"] = int((bt["held_on_missing_price"] > 0).sum())
    if market is not None:
        m = market.reindex(bt.index)
        mm = m.rolling(ppy * 2, min_periods=ppy).sum().shift(1)
        rebound = (mm < 0) & (m.rolling(21).sum() > 0)
        res["crash_diagnostics"] = {
            "mean_net_after_bear_market_rebound": float(bt["net"][rebound].mean() * ppy) if rebound.any() else None,
            "mean_net_otherwise": float(bt["net"][~rebound].mean() * ppy),
            "n_rebound_periods": int(rebound.sum()),
            "note": "rebound = trailing 2y equal-weight market return < 0 and market up over the last 21 bars (Daniel & Moskowitz 2016)",
        }
    return res


def cost_sweep(bt: pd.DataFrame, ppy: int = 252, multipliers=(0, 0.5, 1, 2, 3, 5)) -> list[dict]:
    out = []
    for m in multipliers:
        net = bt["gross"] - m * bt[COST_COLS].sum(axis=1)
        sd = net.std(ddof=1)
        out.append({"cost_multiplier": m, "net_mean_annualised": float(net.mean() * ppy),
                    "net_sharpe_annualised": float(net.mean() / sd * np.sqrt(ppy)) if sd > 0 else None})
    return out
