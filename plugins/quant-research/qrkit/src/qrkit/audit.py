"""Data quality audit against the data contract. Checks the full period."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .io import load_factors, load_prices_raw, load_universe

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
SPLIT_RATIOS = np.array([2, 3, 4, 5, 10, 1.5, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2 / 3])


def _chk(name, status, detail, examples=None):
    return {"check": name, "status": status, "detail": detail, "examples": (examples or [])[:10]}


def _robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median()
    if not mad or np.isnan(mad):
        return pd.Series(0.0, index=x.index)
    return 0.6745 * (x - med) / mad


def audit(prices_path, universe_path=None, factors_path=None, outlier_z=10.0, stale_run=5) -> dict:
    raw = load_prices_raw(prices_path)
    checks = []

    # index monotonicity (as delivered)
    nonmono = [a for a, g in raw.groupby("asset", sort=True) if not g["date"].is_monotonic_increasing]
    checks.append(
        _chk("index_monotonic", WARN if nonmono else PASS,
             f"{len(nonmono)} assets not sorted by date in the file (qrkit sorts them; your own code may not)", nonmono)
    )

    # duplicates
    dup = raw[raw.duplicated(["date", "asset"], keep=False)]
    ex = [f"{r.asset} {r.date.date()}" for r in dup.drop_duplicates(["date", "asset"]).itertuples()]
    checks.append(_chk("duplicates", FAIL if len(dup) else PASS, f"{len(dup)} rows share a (date, asset) key", ex))

    df = raw.drop_duplicates(["date", "asset"]).sort_values(["asset", "date"]).reset_index(drop=True)

    # missing values
    n_nan = int(df["close"].isna().sum())
    ex = [f"{r.asset} {r.date.date()}" for r in df[df["close"].isna()].itertuples()]
    nonpos = df[df["close"] <= 0]
    ex += [f"{r.asset} {r.date.date()} close={r.close}" for r in nonpos.itertuples()]
    checks.append(_chk("missing_values", FAIL if n_nan or len(nonpos) else PASS,
                       f"{n_nan} missing and {len(nonpos)} non-positive close values", ex))

    # calendar gaps: per asset, dates missing from the union calendar inside its own life
    cal = pd.DatetimeIndex(sorted(df["date"].unique()))
    gap_ex, worst = [], 0.0
    for a, g in df.groupby("asset"):
        life = cal[(cal >= g["date"].min()) & (cal <= g["date"].max())]
        miss = len(life) - g["date"].nunique()
        frac = miss / max(len(life), 1)
        if miss > 0:
            gap_ex.append(f"{a}: {miss} missing days ({frac:.1%})")
        worst = max(worst, frac)
    big_gaps = pd.Series(cal).diff().dt.days
    long_breaks = [f"{cal[i - 1].date()} -> {cal[i].date()}" for i in np.where(big_gaps > 7)[0]]
    status = FAIL if worst > 0.05 else WARN if (worst > 0 or long_breaks) else PASS
    checks.append(_chk("calendar_gaps", status,
                       f"worst asset misses {worst:.2%} of panel dates; {len(long_breaks)} breaks > 7 calendar days",
                       gap_ex + long_breaks))

    c = df.dropna(subset=["close"])
    c = c[c["close"] > 0]
    c = c.assign(lr=np.log(c["close"]).groupby(c["asset"]).diff())

    # stale prices: runs of identical closes
    stale_ex = []
    for a, g in c.groupby("asset"):
        same = (g["close"].diff() == 0).astype(int).values
        run, best = 0, 0
        for s in same:
            run = run + 1 if s else 0
            best = max(best, run)
        if best + 1 >= stale_run:
            stale_ex.append(f"{a}: {best + 1} identical closes in a row")
    checks.append(_chk("stale_prices", WARN if stale_ex else PASS,
                       f"{len(stale_ex)} assets with >= {stale_run} identical consecutive closes", stale_ex))

    # unadjusted splits: jumps whose ratio matches a split ratio and are extreme for that asset
    split_ex = []
    split_keys = set()
    for a, g in c.groupby("asset"):
        z = _robust_z(g["lr"].dropna())
        ratio = np.exp(g["lr"])
        for idx in z.index[z.abs() > 5]:
            r = ratio.loc[idx]
            if np.min(np.abs(SPLIT_RATIOS / r - 1)) < 0.03:
                split_ex.append(f"{a} {g.loc[idx, 'date'].date()} price ratio {r:.3f}")
                split_keys.add(idx)
    checks.append(_chk("unadjusted_splits", FAIL if split_ex else PASS,
                       f"{len(split_ex)} jumps matching a split ratio (2:1, 3:1, 3:2 ...)", split_ex))

    # outliers (MAD), excluding the split candidates already reported
    out_ex = []
    for a, g in c.groupby("asset"):
        z = _robust_z(g["lr"].dropna())
        for idx in z.index[(z.abs() > outlier_z)]:
            if idx not in split_keys:
                out_ex.append(f"{a} {g.loc[idx, 'date'].date()} log-return {g.loc[idx, 'lr']:.3f} (robust z {z.loc[idx]:.1f})")
    checks.append(_chk("outliers_mad", WARN if out_ex else PASS,
                       f"{len(out_ex)} returns with robust (MAD) z-score > {outlier_z}", out_ex))

    # invalid OHLC
    if {"open", "high", "low"}.issubset(df.columns):
        o, h, l, cl = df["open"], df["high"], df["low"], df["close"]
        bad = df[(h < np.maximum(o, cl)) | (l > np.minimum(o, cl)) | (h < l)]
        checks.append(_chk("invalid_ohlc", FAIL if len(bad) else PASS, f"{len(bad)} rows violate low <= open,close <= high",
                           [f"{r.asset} {r.date.date()}" for r in bad.itertuples()]))
    else:
        checks.append(_chk("invalid_ohlc", SKIP, "no open/high/low columns"))

    # time zones / timestamps
    times = raw["date"].dt.time.astype(str)
    has_time = (times != "00:00:00").any()
    weekend = df[df["date"].dt.day_of_week >= 5]
    tz_strings = raw["date_raw"].str.contains(r"[+-]\d\d:?\d\d$|Z$", regex=True).any()
    detail = []
    if has_time:
        detail.append(f"{(times != '00:00:00').sum()} timestamps have a time of day (daily data expected)")
    if len(weekend):
        detail.append(f"{len(weekend)} rows dated on a weekend (possible time-zone shift)")
    if tz_strings:
        detail.append("timestamps carry UTC offsets; converted to UTC dates")
    checks.append(_chk("time_zones", WARN if detail else PASS, "; ".join(detail) or "dates are plain calendar dates",
                       [f"{r.asset} {r.date}" for r in weekend.head(10).itertuples()]))

    # futures roll jumps
    if "contract" in df.columns:
        roll_ex = []
        for a, g in c.assign(contract=df.loc[c.index, "contract"]).groupby("asset"):
            roll = g["contract"].ne(g["contract"].shift()) & g["contract"].shift().notna()
            z = _robust_z(g["lr"].dropna()).reindex(g.index)
            for idx in g.index[roll & (z.abs() > 4)]:
                roll_ex.append(f"{a} {g.loc[idx, 'date'].date()} jump {g.loc[idx, 'lr']:.3f} at contract change")
        checks.append(_chk("futures_roll_jumps", FAIL if roll_ex else PASS,
                           f"{len(roll_ex)} large price jumps on contract changes (series not back-adjusted?)", roll_ex))
    else:
        checks.append(_chk("futures_roll_jumps", SKIP, "no 'contract' column (not a futures panel)"))

    # survivorship
    end_all = df["date"].max()
    last = df.groupby("asset")["date"].max()
    ended = int((last < end_all - pd.Timedelta(days=10)).sum())
    if universe_path is None:
        checks.append(_chk("survivorship", WARN,
                           f"no universe membership file: survivorship cannot be checked ({ended} of {len(last)} assets stop before the panel end). "
                           "Results may be inflated by survivor-only data."))
    else:
        u = load_universe(universe_path)
        ex = []
        not_in_prices = sorted(set(u["asset"]) - set(df["asset"]))
        not_in_universe = sorted(set(df["asset"]) - set(u["asset"]))
        if not_in_prices:
            ex.append(f"{len(not_in_prices)} universe members have no prices (e.g. {not_in_prices[:5]}) — delisted names dropped?")
        if not_in_universe:
            ex.append(f"{len(not_in_universe)} assets in prices are not in the universe file (e.g. {not_in_universe[:5]})")
        delisted = u["end"].notna() & (u["end"] < end_all)
        if delisted.sum() == 0:
            ex.append("universe file has no member that leaves before the panel end: looks survivor-only")
        status = FAIL if not_in_prices else WARN if ex else PASS
        checks.append(_chk("survivorship", status,
                           f"universe has {len(u)} rows, {int(delisted.sum())} leave before panel end", ex))

    if factors_path is not None:
        f = load_factors(factors_path)
        cover = f.index.min() <= df["date"].min() and f.index.max() >= df["date"].max()
        checks.append(_chk("factor_coverage", PASS if cover else WARN,
                           f"factor file {f.index.min().date()}..{f.index.max().date()} vs prices "
                           f"{df['date'].min().date()}..{df['date'].max().date()}; columns {list(f.columns)}"))
    else:
        checks.append(_chk("factor_coverage", WARN, "no factor file: exposure checks will be limited to the market proxy"))

    statuses = [x["status"] for x in checks]
    overall = FAIL if FAIL in statuses else WARN if WARN in statuses else PASS
    return {
        "status": overall,
        "n_rows": int(len(raw)),
        "n_assets": int(df["asset"].nunique()),
        "start": df["date"].min(),
        "end": df["date"].max(),
        "checks": checks,
        "failed": [x["check"] for x in checks if x["status"] == FAIL],
        "warned": [x["check"] for x in checks if x["status"] == WARN],
    }
