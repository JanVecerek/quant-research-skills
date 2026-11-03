"""No estimate at time t changes when data after t is altered."""

import numpy as np
import pandas as pd
import pytest

from qrkit import backtest, meanrev, momentum

T_CUT = 400


def _perturb(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.iloc[T_CUT + 1:] = out.iloc[T_CUT + 1:] * np.exp(np.random.default_rng(99).normal(0, 0.3, out.iloc[T_CUT + 1:].shape))
    return out


@pytest.fixture
def closes():
    rng = np.random.default_rng(0)
    d = pd.bdate_range("2015-01-01", periods=700)
    return pd.DataFrame(50 * np.exp(np.cumsum(rng.normal(0, 0.01, (700, 6)), axis=0)), index=d, columns=[f"A{i}" for i in range(6)])


@pytest.mark.parametrize("mode,kw", [("static", {"formation": 100}), ("static", {"formation": 100, "refit_every": 30}),
                                     ("rolling", {"window": 60})])
def test_hedge_ratio_and_zscore(closes, mode, kw):
    def run(c):
        df = meanrev.hedge_ratio(np.log(c["A0"]), np.log(c["A1"]), mode=mode, **kw).set_index("date")
        df["z"] = meanrev.zscore(df["spread"], 20)
        return df

    a, b = run(closes), run(_perturb(closes))
    cut = closes.index[T_CUT]
    pd.testing.assert_frame_equal(a.loc[:cut], b.loc[:cut])


@pytest.mark.parametrize("kind", ["xs", "ts"])
def test_momentum_signal(closes, kind):
    a, _ = momentum.signal(closes, kind, 60, 21)
    b, _ = momentum.signal(_perturb(closes), kind, 60, 21)
    cut = closes.index[T_CUT]
    pd.testing.assert_frame_equal(a[a.date <= cut].reset_index(drop=True), b[b.date <= cut].reset_index(drop=True))


def test_backtest_returns(closes):
    w = []
    for d in closes.index[::5]:
        for i, c in enumerate(closes.columns):
            w.append((d, c, (-1) ** i * 0.1))
    W = pd.DataFrame(w, columns=["date", "asset", "weight"])
    vol = pd.DataFrame(1e6, index=closes.index, columns=closes.columns)
    costs = {"half_spread_bps": 2, "commission_bps": 1, "impact_coef": 0.1, "borrow_bps_annual": 50}
    a = backtest.run(closes, W, costs, 1e6, 0, vol)
    b = backtest.run(_perturb(closes), W, costs, 1e6, 0, vol)
    cut = closes.index[T_CUT]
    pd.testing.assert_frame_equal(a.loc[:cut], b.loc[:cut])


def test_missing_skip_is_flagged(closes):
    _, errors = momentum.signal(closes, "xs", 231, 0)
    assert errors and "skip period" in errors[0]


def test_tsmom_without_skip_is_allowed(closes):
    """Moskowitz-Ooi-Pedersen time-series momentum uses no skip period."""
    _, errors = momentum.signal(closes, "ts", 252, 0)
    assert errors == []
