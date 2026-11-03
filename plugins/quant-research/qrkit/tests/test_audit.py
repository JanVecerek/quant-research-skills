import numpy as np
import pandas as pd

from qrkit.audit import audit
from conftest import make_panel


def status(res, name):
    return next(c["status"] for c in res["checks"] if c["check"] == name)


def test_clean_panel(tmp_path):
    p = tmp_path / "p.csv"
    make_panel().to_csv(p, index=False)
    r = audit(p)
    for c in ["duplicates", "missing_values", "unadjusted_splits", "stale_prices", "calendar_gaps"]:
        assert status(r, c) == "PASS", c
    assert status(r, "survivorship") == "WARN"  # never PASS without a universe file


def test_planted_errors(tmp_path):
    df = make_panel()
    a1 = df.asset == "A1"
    idx = df[a1].index
    df.loc[idx[300:], "close"] /= 2  # unadjusted 2:1 split
    a2 = df[df.asset == "A2"].index
    df.loc[a2[100:110], "close"] = df.loc[a2[100], "close"]  # stale
    df = pd.concat([df, df[df.asset == "A3"].iloc[50:52]])  # duplicates
    df = df.drop(df[df.asset == "A0"].index[200:240])  # gap
    p = tmp_path / "p.csv"
    df.to_csv(p, index=False)
    r = audit(p)
    assert r["status"] == "FAIL"
    assert status(r, "unadjusted_splits") == "FAIL"
    assert status(r, "duplicates") == "FAIL"
    assert status(r, "stale_prices") == "WARN"
    assert status(r, "calendar_gaps") == "FAIL"


def test_ohlc_and_survivorship(tmp_path):
    df = make_panel()
    df["open"], df["high"], df["low"] = df.close, df.close * 1.01, df.close * 0.99
    df.loc[5, "high"] = df.loc[5, "close"] * 0.9
    p = tmp_path / "p.csv"
    df.to_csv(p, index=False)
    u = tmp_path / "u.csv"
    pd.DataFrame({"asset": ["A0", "A1", "A2", "A3", "DEAD"], "start": "2015-01-01", "end": ["", "", "", "", "2015-06-01"]}).to_csv(u, index=False)
    r = audit(p, u)
    assert status(r, "invalid_ohlc") == "FAIL"
    assert status(r, "survivorship") == "FAIL"  # DEAD is in the universe but has no prices
