"""Create the data for one eval case in the current directory.

Usage (from a case's scaffold.sh):
  uv run --project <plugin>/qrkit python <plugin>/evals/fixtures/make_fixture.py <case-name>
Every fixture is seeded, so all runs of a case see identical data.
"""

import sys

import numpy as np
import pandas as pd

from qrkit import synth


def write(df, name="prices.csv"):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.sort_values(["date", "asset"]).to_csv(name, index=False, float_format="%.6f")


def momentum_noise(seed=101):
    df, _ = synth.noise_panel(np.random.default_rng(seed), n=3000, assets=60)
    return df


def main(case):
    if case == "noise-rw-pair":
        df, _ = synth.rw_pair(np.random.default_rng(201)); write(df)
    elif case == "noise-momentum-panel":
        write(momentum_noise(202))
    elif case == "effect-ou-pair":
        df, _ = synth.ou_pair(np.random.default_rng(203)); write(df)
    elif case == "effect-momentum-panel":
        df, _ = synth.momentum_panel(np.random.default_rng(204)); write(df)
    elif case == "unadjusted-split":
        df = momentum_noise(205)
        m = (df.asset == "S007") & (pd.to_datetime(df.date) >= "2014-06-02")
        df.loc[m, "close"] /= 3  # unadjusted 3:1 split
        write(df)
    elif case == "duplicate-rows":
        df = momentum_noise(206)
        dup = df[df.asset == "S011"].iloc[400:415]
        write(pd.concat([df, dup]))
    elif case == "survivorship":
        # planted momentum panel, but the worst 20% of assets by final price were removed (survivors only)
        df, _ = synth.momentum_panel(np.random.default_rng(207), assets=80)
        last = df.sort_values("date").groupby("asset")["close"].last()
        keep = last[last > last.quantile(0.2)].index
        write(df[df.asset.isin(keep)])
    elif case == "lookahead":
        df = momentum_noise(208)
        write(df)
        P = df.pivot(index="date", columns="asset", values="close").sort_index()
        nxt = P.pct_change(fill_method=None).shift(-1)  # tomorrow's return: look-ahead
        w = np.sign(nxt).fillna(0) / P.shape[1]
        W = w.stack().rename("weight").reset_index()
        W.columns = ["date", "asset", "weight"]
        write(W, "weights.csv")
    elif case in ("full-sample-hedge", "missing-rebalancing-cost"):
        df, _ = synth.ou_pair(np.random.default_rng(209)); write(df)
    elif case in ("momentum-no-skip", "many-variants", "costs-omitted", "oos-peeking"):
        write(momentum_noise({"momentum-no-skip": 210, "many-variants": 211, "costs-omitted": 212, "oos-peeking": 213}[case]))
    else:
        raise SystemExit(f"unknown case {case}")


if __name__ == "__main__":
    main(sys.argv[1])
