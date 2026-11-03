"""Contracts, deterministic output files and the trial log.

Every qrkit command goes through :class:`Run`: it hashes inputs, writes one JSON
result to ``qr-output/`` and appends one row to ``qr-output/trials.csv``.
Output file names and contents depend only on inputs and parameters (no wall
clock), so a rerun produces byte-identical JSON.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import __version__


class ContractError(ValueError):
    """Input violates the data or strategy output contract."""


class RuleError(RuntimeError):
    """A research rule (lock, window, one-time OOS, seed) was violated."""


def output_dir() -> Path:
    d = Path(os.environ.get("QRKIT_OUTPUT", "qr-output"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------- JSON


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        if math.isnan(x) or math.isinf(x):
            return None
        return float(f"{x:.12g}")  # stable across tiny float noise
    if isinstance(obj, (pd.Timestamp, _dt.date)):
        return str(pd.Timestamp(obj).date())
    if isinstance(obj, Path):
        return str(obj)
    return obj


def dumps(obj: Any) -> str:
    return json.dumps(_clean(obj), indent=2, sort_keys=True)


# --------------------------------------------------------------------------- runs

TRIAL_FIELDS = [
    "timestamp_utc",
    "hypothesis_id",
    "command",
    "parameters",
    "input_hash",
    "seed",
    "output_file",
    "headline",
]


@dataclass
class Run:
    command: str
    params: dict
    inputs: dict = field(default_factory=dict)  # label -> path
    hypothesis_id: str | None = None
    seed: int | None = None

    def input_hashes(self) -> dict:
        return {k: sha256_file(v) for k, v in sorted(self.inputs.items()) if v}

    def input_hash(self) -> str:
        return sha256_text(json.dumps(self.input_hashes(), sort_keys=True))

    def run_key(self) -> str:
        payload = json.dumps(
            _clean(
                {
                    "c": self.command,
                    "p": self.params,
                    "i": self.input_hash(),
                    "h": self.hypothesis_id,
                    "s": self.seed,
                }
            ),
            sort_keys=True,
        )
        return sha256_text(payload)[:12]

    def stem(self) -> str:
        return f"{self.command.replace(' ', '-')}-{self.run_key()}"

    def series_path(self, suffix: str = "series") -> Path:
        d = output_dir() / "series"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.stem()}-{suffix}.csv"

    def write(self, result: dict, headline: str = "") -> Path:
        doc = {
            "qrkit_version": __version__,
            "command": self.command,
            "hypothesis_id": self.hypothesis_id,
            "parameters": self.params,
            "seed": self.seed,
            "inputs": {k: str(v) for k, v in sorted(self.inputs.items()) if v},
            "input_sha256": self.input_hashes(),
            "input_hash": self.input_hash(),
            "result": result,
        }
        path = output_dir() / f"{self.stem()}.json"
        path.write_text(dumps(doc) + "\n")
        append_trial(
            hypothesis_id=self.hypothesis_id,
            command=self.command,
            parameters=self.params,
            input_hash=self.input_hash(),
            seed=self.seed,
            output_file=str(path),
            headline=headline,
        )
        return path


def append_trial(**row: Any) -> None:
    path = output_dir() / "trials.csv"
    new = not path.exists()
    row = dict(row)
    row["timestamp_utc"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row["parameters"] = json.dumps(_clean(row.get("parameters") or {}), sort_keys=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRIAL_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in TRIAL_FIELDS})


def read_trials() -> pd.DataFrame:
    path = output_dir() / "trials.csv"
    if not path.exists():
        return pd.DataFrame(columns=TRIAL_FIELDS)
    return pd.read_csv(path, dtype=str).fillna("")


def require_seed(seed: int | None) -> int:
    if seed is None:
        raise RuleError("this command is random: pass --seed <int> so the result is reproducible")
    return int(seed)


# --------------------------------------------------------------------------- tables


def read_table(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise ContractError(f"{p}: file not found")
    if p.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(p)
    if p.suffix.lower() in (".csv", ".txt"):
        return pd.read_csv(p)
    raise ContractError(f"{p}: expected .csv or .parquet")


def _parse_dates(df: pd.DataFrame, path: str | Path, col: str = "date") -> pd.Series:
    try:
        d = pd.to_datetime(df[col], utc=False)
    except Exception as e:  # noqa: BLE001
        raise ContractError(f"{path}: column '{col}' is not parseable as dates ({e})") from e
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("UTC").dt.tz_localize(None)
    return d


PRICE_REQUIRED = ["date", "asset", "close"]
PRICE_OPTIONAL = ["open", "high", "low", "volume", "contract"]


def load_prices_raw(path: str | Path) -> pd.DataFrame:
    """Load a price panel, validate the contract, keep original order (for audit)."""
    df = read_table(path)
    missing = [c for c in PRICE_REQUIRED if c not in df.columns]
    if missing:
        raise ContractError(
            f"{path}: price panel must have columns {PRICE_REQUIRED} "
            f"(optional {PRICE_OPTIONAL}); missing {missing}. "
            "A single series is a panel with one asset."
        )
    df = df.copy()
    df["date_raw"] = df["date"].astype(str)
    df["date"] = _parse_dates(df, path)
    df["asset"] = df["asset"].astype(str)
    for c in ["close", "open", "high", "low", "volume"]:
        if c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]):
                conv = pd.to_numeric(df[c], errors="coerce")
                bad = conv.isna() & df[c].notna()
                if bad.any():
                    raise ContractError(f"{path}: column '{c}' has non-numeric values, e.g. {df.loc[bad, c].iloc[0]!r}")
                df[c] = conv
    return df


def load_prices(path: str | Path, window: tuple | None = None) -> pd.DataFrame:
    """Price panel sorted by asset/date, duplicates rejected, optional date window."""
    df = load_prices_raw(path)
    if df.duplicated(["date", "asset"]).any():
        raise ContractError(
            f"{path}: duplicate (date, asset) rows. Run `qrkit audit` and fix them with a script."
        )
    if (df["close"] <= 0).any():
        raise ContractError(f"{path}: non-positive close prices. Run `qrkit audit`.")
    df = df.sort_values(["asset", "date"]).reset_index(drop=True)
    if window is not None:
        lo, hi = window
        df = df[(df["date"] >= lo) & (df["date"] <= hi)]
    return df.drop(columns=["date_raw"])


def close_matrix(prices: pd.DataFrame, col: str = "close") -> pd.DataFrame:
    return prices.pivot(index="date", columns="asset", values=col).sort_index()


def load_weights(path: str | Path) -> pd.DataFrame:
    """Strategy output contract: target weights per date x asset."""
    df = read_table(path)
    missing = [c for c in ["date", "asset", "weight"] if c not in df.columns]
    if missing:
        raise ContractError(
            f"{path}: strategy output must have columns ['date', 'asset', 'weight'] "
            f"(target weight decided at the close of `date`); missing {missing}"
        )
    df = df[["date", "asset", "weight"]].copy()
    df["date"] = _parse_dates(df, path)
    df["asset"] = df["asset"].astype(str)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    if df["weight"].isna().any():
        raise ContractError(f"{path}: 'weight' has missing or non-numeric values")
    if df.duplicated(["date", "asset"]).any():
        raise ContractError(f"{path}: duplicate (date, asset) weight rows")
    return df


def load_series(path: str | Path, column: str | None = None, window: tuple | None = None) -> pd.Series:
    """A dated numeric series from a file with a `date` column."""
    df = read_table(path)
    if "date" not in df.columns:
        raise ContractError(f"{path}: series file needs a 'date' column")
    df = df.copy()
    df["date"] = _parse_dates(df, path)
    numeric = [c for c in df.columns if c != "date" and pd.api.types.is_numeric_dtype(df[c])]
    if column is None:
        if len(numeric) != 1:
            raise ContractError(f"{path}: pass --column, numeric columns are {numeric}")
        column = numeric[0]
    if column not in df.columns:
        raise ContractError(f"{path}: no column '{column}' (have {list(df.columns)})")
    s = df.set_index("date")[column].astype(float).sort_index()
    if s.index.duplicated().any():
        raise ContractError(f"{path}: duplicate dates in series")
    if window is not None:
        s = s[(s.index >= window[0]) & (s.index <= window[1])]
    return s.dropna()


def load_universe(path: str | Path) -> pd.DataFrame:
    df = read_table(path)
    missing = [c for c in ["asset", "start", "end"] if c not in df.columns]
    if missing:
        raise ContractError(f"{path}: universe file needs columns asset, start, end (end empty = still a member); missing {missing}")
    df = df.copy()
    df["asset"] = df["asset"].astype(str)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    return df


def load_factors(path: str | Path, window: tuple | None = None) -> pd.DataFrame:
    df = read_table(path)
    if "date" not in df.columns:
        raise ContractError(f"{path}: factor file needs a 'date' column plus numeric factor return columns")
    df = df.copy()
    df["date"] = _parse_dates(df, path)
    df = df.set_index("date").sort_index()
    cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not cols:
        raise ContractError(f"{path}: no numeric factor columns")
    df = df[cols]
    if window is not None:
        df = df[(df.index >= window[0]) & (df.index <= window[1])]
    return df
