"""JSON timestamps: midnight stays YYYY-MM-DD, other times keep the time of day."""

import datetime as dt
import json

import numpy as np
import pandas as pd

from qrkit.io import dumps


def _t(v):
    return json.loads(dumps({"t": v}))["t"]


def test_intraday_timestamp_round_trips():
    ts = pd.Timestamp("2026-10-02 13:00")
    s = _t(ts)
    assert s == "2026-10-02T13:00:00"
    assert pd.Timestamp(s) == ts


def test_midnight_stays_date_only():
    assert _t(pd.Timestamp("2026-10-02")) == "2026-10-02"
    assert _t(dt.date(2026, 10, 2)) == "2026-10-02"
    assert _t(dt.datetime(2026, 10, 2)) == "2026-10-02"
    assert _t(np.datetime64("2026-10-02")) == "2026-10-02"


def test_other_datetime_types_keep_time():
    assert _t(dt.datetime(2026, 10, 2, 9, 30, 5)) == "2026-10-02T09:30:05"
    assert _t(np.datetime64("2026-10-02T13:00")) == "2026-10-02T13:00:00"


def test_tz_aware_converted_to_utc_first():
    assert _t(pd.Timestamp("2026-10-02 09:30", tz="America/New_York")) == "2026-10-02T13:30:00"
    # midnight after conversion to UTC is date-only
    assert _t(pd.Timestamp("2026-10-02 02:00", tz="Europe/Prague")) == "2026-10-02"


def test_nested_and_nat():
    out = json.loads(dumps({"w": [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-09 23:00")], "n": pd.NaT}))
    assert out["w"] == ["2026-10-01", "2026-10-09T23:00:00"]
    assert out["n"] == "NaT"
