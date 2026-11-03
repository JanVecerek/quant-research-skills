"""Synthetic datasets with known truth, for the quickstart and the eval suites."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

KINDS = ("ou-pair", "rw-pair", "momentum-panel", "noise-panel")


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2010-01-04", periods=n)


def ou_pair(rng, n=3000, half_life=5.0, sigma=0.02, beta=1.0):
    theta = np.log(2) / half_life
    phi = np.exp(-theta)
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + rng.normal(0, sigma)
    lb = np.log(40) + np.cumsum(rng.normal(0.0002, 0.012, n))
    la = 0.3 + beta * lb + s
    d = _dates(n)
    vol = rng.integers(2_000_000, 6_000_000, size=(2, n))
    df = pd.DataFrame({"date": np.r_[d, d], "asset": ["AAA"] * n + ["BBB"] * n,
                       "close": np.r_[np.exp(la), np.exp(lb)], "volume": np.r_[vol[0], vol[1]]})
    truth = {"cointegrated": True, "half_life": half_life, "beta": beta, "ar1_phi": phi}
    return df, truth


def rw_pair(rng, n=3000):
    f = np.cumsum(rng.normal(0, 0.01, n))
    a = np.cumsum(rng.normal(0, 0.008, n))
    b = np.cumsum(rng.normal(0, 0.008, n))
    d = _dates(n)
    vol = rng.integers(2_000_000, 6_000_000, size=(2, n))
    df = pd.DataFrame({"date": np.r_[d, d], "asset": ["AAA"] * n + ["BBB"] * n,
                       "close": np.r_[50 * np.exp(f + a), 30 * np.exp(f + b)], "volume": np.r_[vol[0], vol[1]]})
    return df, {"cointegrated": False}


def momentum_panel(rng, n=3000, assets=100, strength=1.0, monthly_rho=0.95, drift_vol=0.004):
    """Persistent expected returns -> past winners keep winning (planted momentum).

    mu_i follows a monthly AR(1) with persistence `monthly_rho`; daily returns = mu_i/21 + noise.
    strength=0 gives the noise panel with identical marginal properties.
    """
    months = n // 21 + 2
    mu = np.zeros((months, assets))
    sd_stat = drift_vol / np.sqrt(1 - monthly_rho**2)
    mu[0] = rng.normal(0, sd_stat, assets)
    for m in range(1, months):
        mu[m] = monthly_rho * mu[m - 1] + rng.normal(0, drift_vol, assets)
    mu_daily = np.repeat(mu, 21, axis=0)[:n] / 21 * strength
    r = 0.0003 + mu_daily + rng.normal(0, 0.015, (n, assets))
    p = 20 * np.exp(np.cumsum(r, axis=0))
    d = _dates(n)
    names = [f"S{i:03d}" for i in range(assets)]
    df = pd.DataFrame(p, index=d, columns=names).stack().rename("close").reset_index()
    df.columns = ["date", "asset", "close"]
    df["volume"] = rng.integers(500_000, 3_000_000, len(df))
    return df, {"momentum": strength > 0, "monthly_rho": monthly_rho, "drift_vol": drift_vol}


def noise_panel(rng, n=3000, assets=100):
    df, _ = momentum_panel(rng, n, assets, strength=0.0)
    # shuffle each asset's returns in time: destroys any serial structure
    out = []
    for a, g in df.groupby("asset"):
        lr = np.diff(np.log(g["close"].values))
        lr = rng.permutation(lr)
        g = g.copy()
        g["close"] = g["close"].values[0] * np.exp(np.r_[0, np.cumsum(lr)])
        out.append(g)
    return pd.concat(out).sort_values(["date", "asset"]), {"momentum": False}


def hypothesis_template(kind: str, dates: pd.DatetimeIndex) -> dict:
    n = len(dates)
    is_end = dates[int(n * 0.7)]
    oos_start = dates[int(n * 0.7) + 1]
    base = {
        "data": {"prices": "prices.csv", "universe": "universe.csv"},
        "periods_per_year": 252,
        "alpha": 0.05,
        "in_sample": {"start": str(dates[0].date()), "end": str(is_end.date())},
        "out_of_sample": {"start": str(oos_start.date()), "end": str(dates[-1].date())},
        "capital": 1_000_000,
        "costs": {"half_spread_bps": 2, "commission_bps": 1, "impact_coef": 0.5, "borrow_bps_annual": 50},
        "budget": {"max_trials": 10},
        "dsr_threshold": 0.95,
    }
    if kind in ("ou-pair", "rw-pair"):
        base.update({
            "title": "AAA/BBB spread mean reversion",
            "rationale": "AAA and BBB share the same cash-flow driver; temporary liquidity shocks push the spread away from its long-run level and arbitrage capital pulls it back.",
            "edge": {"source": "structural", "counterparty": "liquidity demanders who trade one leg urgently and pay for immediacy",
                     "why_not_arbitraged": "capacity is small and holding periods of weeks tie up capital"},
            "h0": "log(AAA) and log(BBB) are not cointegrated",
            "h1": "log(AAA) - beta log(BBB) is stationary in both regression directions",
            "metric": "cointegration", "test": "meanrev engle-granger", "min_effect": 0.1, "min_sharpe": 1.0,
            "kill_criteria": ["Engle-Granger not significant in both directions in-sample",
                              "net OOS Sharpe CI includes 0", "half-life longer than 60 bars"],
        })
    else:
        base.update({
            "title": "Cross-sectional 12-1 momentum",
            "rationale": "Investors under-react to news and then herd, so past 12-month winners keep outperforming losers over the next month.",
            "edge": {"source": "behavioural", "counterparty": "investors who under-react to information and sell winners too early (disposition effect)",
                     "why_not_arbitraged": "crash risk and high turnover limit arbitrage capital"},
            "h0": "mean rank IC of the 12-1 signal against next-month returns is 0",
            "h1": "mean rank IC is positive",
            "metric": "rank_ic", "test": "momentum ic", "min_effect": 0.15,
            "kill_criteria": ["rank IC not significant in-sample", "net OOS Sharpe CI includes 0",
                              "break-even cost below the assumed cost"],
        })
    return base


def make(kind: str, seed: int, out: Path) -> dict:
    rng = np.random.default_rng(seed)
    if kind == "ou-pair":
        df, truth = ou_pair(rng)
    elif kind == "rw-pair":
        df, truth = rw_pair(rng)
    elif kind == "momentum-panel":
        df, truth = momentum_panel(rng)
    elif kind == "noise-panel":
        df, truth = noise_panel(rng)
    else:
        raise ValueError(f"kind must be one of {KINDS}")
    out.mkdir(parents=True, exist_ok=True)
    df = df.sort_values(["date", "asset"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.to_csv(out / "prices.csv", index=False, float_format="%.6f")
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(df["date"].unique())))
    uni = pd.DataFrame({"asset": sorted(df["asset"].unique()), "start": str(dates[0].date()), "end": ""})
    uni.to_csv(out / "universe.csv", index=False)
    hyp = hypothesis_template(kind, dates)
    (out / "hypothesis.yaml").write_text(yaml.safe_dump(hyp, sort_keys=False, width=100))
    return {"kind": kind, "seed": seed, "out": str(out), "truth": truth, "n_dates": len(dates),
            "n_assets": int(df["asset"].nunique())}
