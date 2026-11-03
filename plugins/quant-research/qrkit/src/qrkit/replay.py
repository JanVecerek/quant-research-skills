"""Replay a qrkit weights chain over in-sample + out-of-sample data with frozen parameters.

Used only by `qrkit validate --oos --from <weights output JSON>`: the agent never
sees out-of-sample signals or spreads, only the one-time OOS result.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import meanrev, momentum
from .io import ContractError, close_matrix


def _json_for_series(series_path: str) -> dict:
    p = Path(series_path)
    stem = p.stem.rsplit("-", 1)[0]
    j = p.parent.parent / f"{stem}.json"
    if not j.exists():
        raise ContractError(f"cannot find the qrkit output that produced {series_path} (expected {j})")
    return json.loads(j.read_text())


def replay(out_json: str, prices: pd.DataFrame, ppy: int) -> tuple[pd.DataFrame, list[dict]]:
    doc = json.loads(Path(out_json).read_text())
    chain = [{"command": doc["command"], "parameters": doc["parameters"]}]
    P = close_matrix(prices)
    cmd, prm = doc["command"], doc["parameters"]
    if cmd == "meanrev pairs-weights":
        z = _json_for_series(doc["inputs"]["zscore"])
        hdoc = _json_for_series(z["inputs"]["hedge"])
        chain += [{"command": z["command"], "parameters": z["parameters"]}, {"command": hdoc["command"], "parameters": hdoc["parameters"]}]
        hp = hdoc["parameters"]
        tr = np.log if hp.get("levels", "log") == "log" else (lambda s: s)
        df = meanrev.hedge_ratio(tr(P[hp["a"]]), tr(P[hp["b"]]), hp.get("mode", "static"), hp.get("fit", "tls"),
                                 hp.get("formation", 252), hp.get("window", 120), hp.get("refit_every"))
        df["z"] = meanrev.zscore(df["spread"], z["parameters"].get("window", 60)).values
        W = meanrev.pairs_weights(df, hp["a"], hp["b"], prm.get("entry", 2.0), prm.get("exit", 0.5), prm.get("stop"))
    elif cmd == "momentum portfolio":
        s = _json_for_series(doc["inputs"]["signal"])
        chain.append({"command": s["command"], "parameters": s["parameters"]})
        sp = s["parameters"]
        sig, _ = momentum.signal(P, sp.get("kind", "xs"), sp.get("lookback", 231), sp.get("skip", 21), ppy)
        liq = None
        if prm.get("min_dollar_volume") and "volume" in prices.columns:
            liq = (P * close_matrix(prices, "volume")).rolling(20).mean()
        W = momentum.portfolio(sig, prm.get("kind", "xs"), prm.get("quantiles", 5), prm.get("holding", 1),
                               prm.get("rebalance", 21), prm.get("target_vol", 0.4), liq, prm.get("min_dollar_volume"))
    else:
        raise ContractError(f"--from must be a weights output of `meanrev pairs-weights` or `momentum portfolio`, got {cmd}")
    return W, chain
