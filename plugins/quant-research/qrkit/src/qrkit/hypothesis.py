"""Pre-registered hypothesis: validation, power and lock.

The hypothesis id is derived from the file hash, so any edit to the file
produces a new id and trials are counted per id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats as st

from .io import ContractError, RuleError, Run, dumps, output_dir, read_trials, sha256_file

EDGE_SOURCES = {"risk_premium", "behavioural", "structural"}
METRICS = {"sharpe", "mean_return", "rank_ic", "cointegration", "variance_ratio", "beta"}
TESTS = {
    "stats hac-mean",
    "stats ols",
    "meanrev engle-granger",
    "meanrev variance-ratio",
    "momentum ic",
    "momentum tsmom",
}

REQUIRED = {
    "title": str,
    "rationale": str,
    "edge": dict,
    "h0": str,
    "h1": str,
    "metric": str,
    "test": str,
    "alpha": float,
    "min_effect": float,
    "data": dict,
    "in_sample": dict,
    "out_of_sample": dict,
    "capital": float,
    "costs": dict,
    "budget": dict,
    "kill_criteria": list,
}
COST_KEYS = ["half_spread_bps", "commission_bps", "impact_coef", "borrow_bps_annual"]


@dataclass
class Hypothesis:
    path: Path
    spec: dict
    id: str
    sha256: str

    @property
    def is_window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return pd.Timestamp(self.spec["in_sample"]["start"]), pd.Timestamp(self.spec["in_sample"]["end"])

    @property
    def oos_window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return pd.Timestamp(self.spec["out_of_sample"]["start"]), pd.Timestamp(self.spec["out_of_sample"]["end"])

    @property
    def ppy(self) -> int:
        return int(self.spec.get("periods_per_year", 252))

    @property
    def alpha(self) -> float:
        return float(self.spec["alpha"])

    @property
    def dsr_threshold(self) -> float:
        return float(self.spec.get("dsr_threshold", 0.95))

    def data_path(self, key: str) -> str | None:
        v = (self.spec.get("data") or {}).get(key)
        if not v:
            return None
        p = Path(v)
        if not p.is_absolute() and not p.exists():
            alt = self.path.parent / p
            if alt.exists():
                return str(alt)
        return str(p)


def hypothesis_id(sha: str) -> str:
    return "H-" + sha[:10]


def parse(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise ContractError(f"{p}: hypothesis file not found. Write it first (see hypothesis-and-edge skill).")
    try:
        spec = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise ContractError(f"{p}: invalid YAML ({e})") from e
    if not isinstance(spec, dict):
        raise ContractError(f"{p}: expected a YAML mapping")
    return spec


def validate_spec(spec: dict) -> list[str]:
    """Return a list of problems; empty means complete."""
    errs: list[str] = []
    for k, typ in REQUIRED.items():
        if k not in spec or spec[k] in (None, "", [], {}):
            errs.append(f"missing '{k}'")
            continue
        v = spec[k]
        if typ is float:
            try:
                float(v)
            except (TypeError, ValueError):
                errs.append(f"'{k}' must be a number")
        elif not isinstance(v, typ):
            errs.append(f"'{k}' must be a {typ.__name__}")
    if errs:
        return errs
    edge = spec["edge"]
    if edge.get("source") not in EDGE_SOURCES:
        errs.append(f"edge.source must be one of {sorted(EDGE_SOURCES)}")
    if not edge.get("counterparty"):
        errs.append("edge.counterparty is required: who loses money to this strategy, and why do they accept it?")
    if not edge.get("why_not_arbitraged"):
        errs.append("edge.why_not_arbitraged is required")
    if spec["metric"] not in METRICS:
        errs.append(f"metric must be one of {sorted(METRICS)}")
    if spec["test"] not in TESTS:
        errs.append(f"test must be one of {sorted(TESTS)}")
    a = float(spec["alpha"])
    if not 0 < a < 0.5:
        errs.append("alpha must be in (0, 0.5)")
    if float(spec["min_effect"]) <= 0:
        errs.append("min_effect must be > 0 (smallest effect worth trading, in units of `metric`)")
    if not (spec.get("data") or {}).get("prices"):
        errs.append("data.prices is required")
    try:
        i0, i1 = pd.Timestamp(spec["in_sample"]["start"]), pd.Timestamp(spec["in_sample"]["end"])
        o0, o1 = pd.Timestamp(spec["out_of_sample"]["start"]), pd.Timestamp(spec["out_of_sample"]["end"])
        if not i0 < i1:
            errs.append("in_sample.start must be before in_sample.end")
        if not o0 < o1:
            errs.append("out_of_sample.start must be before out_of_sample.end")
        if not i1 < o0:
            errs.append("out_of_sample must start after in_sample ends (no overlap)")
    except (KeyError, TypeError, ValueError):
        errs.append("in_sample and out_of_sample need start and end dates (YYYY-MM-DD)")
    if float(spec["capital"]) <= 0:
        errs.append("capital must be > 0 (used for market impact)")
    for k in COST_KEYS:
        if k not in spec["costs"]:
            errs.append(f"costs.{k} is required (use 0 explicitly if it does not apply)")
    if "max_trials" not in spec["budget"]:
        errs.append("budget.max_trials is required (research budget)")
    if not all(isinstance(x, str) and x.strip() for x in spec["kill_criteria"]):
        errs.append("kill_criteria must be a list of non-empty strings")
    thr = spec.get("dsr_threshold", 0.95)
    if not 0.5 <= float(thr) < 1:
        errs.append("dsr_threshold must be in [0.5, 1)")
    return errs


def power_analysis(spec: dict, n_is: int) -> dict:
    """Power of a one-sided test for the minimum effect over the IS sample.

    For metric 'sharpe' the effect is an annualised Sharpe ratio and the test
    statistic is approximately SR_period * sqrt(n). For 'rank_ic' it is the mean
    IC with n cross-sections (t = IC * sqrt(n) / sd, sd ~ 1/sqrt(N_assets) unknown,
    so we use the conservative IC-IR form with min_effect as IC-IR per period).
    Other metrics: min_effect is interpreted as a standardised effect per sqrt(period).
    """
    alpha = float(spec["alpha"])
    eff = float(spec["min_effect"])
    ppy = int(spec.get("periods_per_year", 252))
    if spec["metric"] in ("sharpe", "mean_return"):
        per = eff / np.sqrt(ppy)
        note = "min_effect read as annualised Sharpe ratio"
    else:
        per = eff
        note = "min_effect read as standardised effect per period (e.g. IC information ratio per period)"
    z_a = st.norm.ppf(1 - alpha)
    ncp = per * np.sqrt(max(n_is, 0))
    power = float(1 - st.norm.cdf(z_a - ncp))
    # sample size for 80% power
    z_b = st.norm.ppf(0.8)
    n80 = int(np.ceil(((z_a + z_b) / per) ** 2)) if per > 0 else None
    mde = float((z_a + z_b) / np.sqrt(n_is) * (np.sqrt(ppy) if spec["metric"] in ("sharpe", "mean_return") else 1)) if n_is > 0 else None
    return {
        "n_in_sample_periods": int(n_is),
        "power_at_min_effect": power,
        "periods_needed_for_80pct_power": n80,
        "min_detectable_effect_80pct": mde,
        "adequate": power >= 0.8,
        "note": note,
    }


def count_is_periods(spec: dict, base: Path) -> int:
    from .io import load_prices

    p = Path(spec["data"]["prices"])
    if not p.exists() and (base / p).exists():
        p = base / p
    prices = load_prices(p)
    lo, hi = pd.Timestamp(spec["in_sample"]["start"]), pd.Timestamp(spec["in_sample"]["end"])
    d = prices["date"]
    return int(d[(d >= lo) & (d <= hi)].nunique()) - 1


def check(path: str | Path) -> tuple[dict, list[str]]:
    spec = parse(path)
    errs = validate_spec(spec)
    return spec, errs


def lock_dir() -> Path:
    d = output_dir() / "hypotheses"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock(path: str | Path) -> tuple[Hypothesis, Path, dict]:
    spec, errs = check(path)
    if errs:
        raise ContractError("hypothesis incomplete:\n  - " + "\n  - ".join(errs))
    sha = sha256_file(path)
    hid = hypothesis_id(sha)
    n_is = count_is_periods(spec, Path(path).parent)
    pw = power_analysis(spec, n_is)
    rec = {"hypothesis_id": hid, "file": str(path), "sha256": sha, "spec": spec, "power": pw}
    lp = lock_dir() / f"{hid}.json"
    already = lp.exists()
    lp.write_text(dumps(rec) + "\n")
    h = Hypothesis(Path(path), spec, hid, sha)
    if not already:
        run = Run("hypothesis lock", {"file": str(path)}, {"hypothesis": path}, hid)
        run.write({"hypothesis_id": hid, "sha256": sha, "power": pw}, headline=f"locked {hid}")
    return h, lp, pw


def load_locked(path: str | Path = "hypothesis.yaml") -> Hypothesis:
    """Return the locked hypothesis for this file or refuse.

    Refuses when the file was never locked or changed after locking: an edited
    hypothesis is a new hypothesis and must get a new id.
    """
    p = Path(path)
    if not p.exists():
        raise RuleError(f"{p}: no hypothesis file. Write and lock one first: `qrkit hypothesis lock {p}`.")
    sha = sha256_file(p)
    hid = hypothesis_id(sha)
    lp = lock_dir() / f"{hid}.json"
    if not lp.exists():
        locked_ids = sorted(x.stem for x in lock_dir().glob("H-*.json"))
        hint = (
            " The file changed after it was locked; a changed hypothesis needs a new id: run "
            f"`qrkit hypothesis lock {p}`. Trials from earlier ids still count against the research budget."
            if locked_ids
            else f" Run `qrkit hypothesis lock {p}` first."
        )
        raise RuleError(f"{p}: hypothesis is not locked in its current form (sha {sha[:10]}).{hint}")
    spec = json.loads(lp.read_text())["spec"]
    return Hypothesis(p, spec, hid, sha)


def trial_count(hid: str) -> dict:
    t = read_trials()
    mine = t[t["hypothesis_id"] == hid]
    variants = mine[mine["command"] == "backtest"]["input_hash"].unique()
    return {
        "commands_run": int(len(mine)),
        "strategy_variants": int(len(variants)),
        "all_ids": sorted(x for x in t["hypothesis_id"].unique() if x),
        "total_commands_all_ids": int((t["hypothesis_id"] != "").sum()),
    }
