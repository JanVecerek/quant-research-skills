"""Contracts, lock, in-sample window, one-time OOS, seeds and deterministic output."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from qrkit.cli import main
from conftest import make_panel


def _hyp(workdir, **over):
    make_panel().to_csv(workdir / "prices.csv", index=False)
    spec = {
        "title": "t", "rationale": "r",
        "edge": {"source": "behavioural", "counterparty": "c", "why_not_arbitraged": "w"},
        "h0": "mean = 0", "h1": "mean > 0", "metric": "sharpe", "test": "stats hac-mean", "alpha": 0.05,
        "min_effect": 0.5, "data": {"prices": "prices.csv"},
        "in_sample": {"start": "2015-01-01", "end": "2016-06-30"},
        "out_of_sample": {"start": "2016-07-01", "end": "2017-04-30"},
        "capital": 1e6, "costs": {"half_spread_bps": 2, "commission_bps": 1, "impact_coef": 0.1, "borrow_bps_annual": 50},
        "budget": {"max_trials": 5}, "kill_criteria": ["k"],
    }
    spec.update(over)
    (workdir / "hypothesis.yaml").write_text(yaml.safe_dump(spec))
    return spec


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def test_incomplete_hypothesis_rejected(workdir, capsys):
    _hyp(workdir)
    spec = yaml.safe_load((workdir / "hypothesis.yaml").read_text())
    del spec["kill_criteria"]
    spec["edge"].pop("counterparty")
    (workdir / "hypothesis.yaml").write_text(yaml.safe_dump(spec))
    assert main(["hypothesis", "check"]) == 1
    probs = _out(capsys)["problems"]
    assert any("kill_criteria" in p for p in probs)
    assert main(["hypothesis", "lock"]) == 3


def test_commands_require_lock_and_new_id_after_edit(workdir, capsys):
    _hyp(workdir)
    assert main(["stats", "adf", "--asset", "A0"]) == 4
    assert main(["hypothesis", "lock"]) == 0
    hid1 = _out(capsys)["hypothesis_id"]
    assert main(["stats", "adf", "--asset", "A0"]) == 0
    capsys.readouterr()
    p = workdir / "hypothesis.yaml"
    p.write_text(p.read_text().replace("min_effect: 0.5", "min_effect: 0.4"))
    assert main(["stats", "adf", "--asset", "A0"]) == 4  # edited -> refused
    assert main(["hypothesis", "lock"]) == 0
    assert _out(capsys)["hypothesis_id"] != hid1
    trials = pd.read_csv(workdir / "qr-output" / "trials.csv")
    assert trials["hypothesis_id"].nunique() == 2


def test_in_sample_window_enforced(workdir, capsys):
    _hyp(workdir)
    main(["hypothesis", "lock"]); capsys.readouterr()
    d = pd.bdate_range("2015-01-01", periods=600)
    pd.DataFrame({"date": d, "r": np.random.default_rng(0).normal(size=600)}).to_csv(workdir / "s.csv", index=False)
    assert main(["stats", "hac-mean", "--series", "s.csv"]) == 0
    n = _out(capsys)["n"]
    assert n == int(((d >= "2015-01-01") & (d <= "2016-06-30")).sum())


def test_oos_runs_once(workdir, capsys):
    _hyp(workdir)
    main(["hypothesis", "lock"]); capsys.readouterr()
    d = pd.bdate_range("2015-01-01", periods=600)
    W = pd.DataFrame([(x, "A0", 0.5) for x in d[::5]] + [(x, "A1", -0.5) for x in d[::5]], columns=["date", "asset", "weight"])
    W.to_csv(workdir / "w.csv", index=False)
    assert main(["validate", "--oos", "--weights", "w.csv"]) == 0
    capsys.readouterr()
    assert main(["validate", "--oos", "--weights", "w.csv"]) == 4


def test_random_function_requires_seed(workdir, capsys):
    _hyp(workdir)
    main(["hypothesis", "lock"]); capsys.readouterr()
    assert main(["stats", "bootstrap", "--asset", "A0", "--transform", "logret", "--reps", "200"]) == 4
    assert main(["synth", "noise-panel", "--out", "x"]) == 4


def test_contract_violations_rejected(workdir, capsys):
    _hyp(workdir)
    main(["hypothesis", "lock"]); capsys.readouterr()
    pd.DataFrame({"date": ["2015-01-02"], "ticker": ["A0"], "w": [1]}).to_csv(workdir / "bad.csv", index=False)
    assert main(["backtest", "--weights", "bad.csv"]) == 3
    assert "date" in capsys.readouterr().err
    pd.DataFrame({"date": ["2015-01-02"], "price": [1.0]}).to_csv(workdir / "badp.csv", index=False)
    assert main(["audit", "--prices", "badp.csv"]) == 3


def test_identical_output_hashes_on_rerun(workdir, capsys):
    _hyp(workdir)
    main(["hypothesis", "lock"]); capsys.readouterr()
    cmds = [["audit"], ["stats", "stationarity", "--asset", "A0"],
            ["stats", "bootstrap", "--asset", "A0", "--transform", "logret", "--reps", "300", "--seed", "7"],
            ["meanrev", "engle-granger", "--a", "A0", "--b", "A1"]]

    def run_all():
        hashes = []
        for c in cmds:
            main(c)
            f = json.loads(capsys.readouterr().out)["output_file"]
            hashes.append(hashlib.sha256(Path(f).read_bytes()).hexdigest())
        return hashes

    assert run_all() == run_all()
