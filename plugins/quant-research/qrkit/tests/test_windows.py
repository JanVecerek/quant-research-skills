"""Window bounds: a date-only end covers the whole calendar day (intraday data)."""

import numpy as np
import pandas as pd
import pytest
import yaml

from qrkit import hypothesis as hyp
from qrkit.io import in_window, load_factors, load_prices, load_series
from conftest import make_panel


def _hourly(workdir, days=("2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03")):
    idx = pd.date_range(days[0], periods=24 * len(days), freq="h")
    n = len(idx)
    df = pd.DataFrame({"date": idx, "asset": "A0", "close": 100 + np.arange(n) * 0.01})
    p = workdir / "hourly.csv"
    df.to_csv(p, index=False)
    pd.DataFrame({"date": idx, "x": np.arange(n, dtype=float)}).to_csv(workdir / "series.csv", index=False)
    pd.DataFrame({"date": idx, "mkt": np.arange(n, dtype=float)}).to_csv(workdir / "factors.csv", index=False)
    return p


W = (pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02"))


def test_hourly_date_only_window_contains_whole_days(workdir):
    p = _hourly(workdir)
    df = load_prices(p, window=W)
    assert len(df) == 48
    assert df["date"].min() == pd.Timestamp("2026-10-01 00:00")
    assert df["date"].max() == pd.Timestamp("2026-10-02 23:00")
    assert len(load_series(workdir / "series.csv", "x", window=W)) == 48
    assert len(load_factors(workdir / "factors.csv", window=W)) == 48


def test_time_explicit_end_is_inclusive_as_written(workdir):
    p = _hourly(workdir)
    df = load_prices(p, window=(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02 13:00")))
    assert df["date"].max() == pd.Timestamp("2026-10-02 13:00")
    assert len(df) == 24 + 14


def test_start_unchanged(workdir):
    p = _hourly(workdir)
    df = load_prices(p, window=(pd.Timestamp("2026-10-01 06:00"), pd.Timestamp("2026-10-01")))
    assert df["date"].min() == pd.Timestamp("2026-10-01 06:00")
    assert len(df) == 18


def test_in_window_on_index_and_series():
    idx = pd.date_range("2026-10-01", periods=72, freq="h")
    assert in_window(idx, W).sum() == 48
    assert in_window(pd.Series(idx), W).sum() == 48
    assert in_window(idx, ("2026-10-01", "2026-10-02")).sum() == 48


def test_daily_panel_unchanged(workdir):
    df = make_panel(n=300)
    df.to_csv(workdir / "p.csv", index=False)
    lo, hi = pd.Timestamp("2015-03-02"), pd.Timestamp("2015-06-30")
    got = load_prices(workdir / "p.csv", window=(lo, hi))
    full = load_prices(workdir / "p.csv")
    old = full[(full["date"] >= lo) & (full["date"] <= hi)]
    pd.testing.assert_frame_equal(got, old)
    assert got["date"].max() == hi


def _spec(is_end, oos_start):
    return {
        "title": "t", "rationale": "r",
        "edge": {"source": "behavioural", "counterparty": "c", "why_not_arbitraged": "w"},
        "h0": "mean = 0", "h1": "mean > 0", "metric": "sharpe", "test": "stats hac-mean", "alpha": 0.05,
        "min_effect": 0.5, "data": {"prices": "hourly.csv"},
        "in_sample": {"start": "2026-09-30", "end": is_end},
        "out_of_sample": {"start": oos_start, "end": "2026-10-03"},
        "capital": 1e6, "costs": {"half_spread_bps": 2, "commission_bps": 1, "impact_coef": 0.1, "borrow_bps_annual": 50},
        "budget": {"max_trials": 5}, "kill_criteria": ["k"],
    }


OVERLAP = "out_of_sample must start after in_sample ends (no overlap)"


@pytest.mark.parametrize("is_end,oos_start,overlap", [
    ("2026-10-01", "2026-10-02", False),
    ("2026-10-01", "2026-10-01", True),
    ("2026-10-01", "2026-10-01 12:00", True),
    ("2026-10-01 23:00", "2026-10-02", False),
    ("2026-10-01 12:00", "2026-10-01 13:00", False),
    ("2026-10-01 12:00", "2026-10-01 12:00", True),
])
def test_validate_spec_overlap_uses_effective_bounds(is_end, oos_start, overlap):
    # through YAML, as a real hypothesis file is read (dates become datetime.date)
    spec = yaml.safe_load(yaml.safe_dump(_spec(is_end, oos_start)).replace("'", ""))
    assert (OVERLAP in hyp.validate_spec(spec)) is overlap


def test_count_is_periods_counts_last_is_day(workdir):
    _hourly(workdir)
    spec = _spec("2026-10-01", "2026-10-02")
    assert hyp.count_is_periods(spec, workdir) == 48 - 1
