"""qrkit command line. Run `qrkit <command> --help`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from . import audit as audit_mod
from . import backtest as bt_mod
from . import hypothesis as hyp
from . import meanrev, momentum, report, stats, synth, validate
from .io import (ContractError, RuleError, Run, append_trial, close_matrix, dumps, in_window, load_factors,
                 load_prices, load_series, load_weights, output_dir, read_table, require_seed)


RELEVANT = {
    "meanrev engle-granger": ["a", "b", "levels"],
    "meanrev hedge-ratio": ["a", "b", "levels", "mode", "fit", "formation", "window", "refit_every"],
    "meanrev zscore": ["hedge", "window"],
    "meanrev pairs-weights": ["zscore", "entry", "exit", "stop"],
    "meanrev variance-ratio": ["series", "column", "asset", "transform", "lags"],
    "meanrev half-life": ["series", "column", "asset", "transform", "holding_period"],
    "momentum signal": ["kind", "lookback", "skip"],
    "momentum portfolio": ["signal", "kind", "quantiles", "holding", "rebalance", "target_vol", "min_dollar_volume"],
    "momentum ic": ["signal", "horizon", "step"],
    "momentum tsmom": ["lookback_periods", "skip_periods", "period"],
}


def _params(cmd: str, args) -> dict:
    """Only the parameters that affect this command, so output files document the real chain."""
    keys = RELEVANT[cmd]
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}


def emit(path: Path, result: dict, keys: list[str] | None = None) -> None:
    show = {k: result[k] for k in keys if k in result} if keys else result
    print(dumps({"output_file": str(path), **show}))


def _h(args) -> hyp.Hypothesis:
    return hyp.load_locked(args.hypothesis)


def _is_prices(h: hyp.Hypothesis) -> pd.DataFrame:
    return load_prices(h.data_path("prices"), window=h.is_window)


def _ppy(h) -> int:
    return h.ppy


def _costs(h) -> dict:
    c = dict(h.spec["costs"])
    c["_ppy"] = h.ppy
    return c


def _write_series(run: Run, df: pd.DataFrame, suffix: str) -> Path:
    p = run.series_path(suffix)
    df.to_csv(p, index=df.index.name is not None, float_format="%.10g")
    return p


# ------------------------------------------------------------------ hypothesis


def cmd_hypothesis(args):
    if args.action == "check":
        spec, errs = hyp.check(args.file)
        if errs:
            print(dumps({"complete": False, "problems": errs}))
            return 1
        n = hyp.count_is_periods(spec, Path(args.file).parent)
        print(dumps({"complete": True, "power": hyp.power_analysis(spec, n),
                     "note": "not locked yet: run `qrkit hypothesis lock` before any test"}))
        return 0
    h, lp, pw = hyp.lock(args.file)
    print(dumps({"hypothesis_id": h.id, "lock_file": str(lp), "power": pw,
                 "note": "any edit to the file creates a new hypothesis id; trials are counted per id"}))
    return 0


def cmd_log_event(args):
    h = _h(args)
    append_trial(hypothesis_id=h.id, command=f"log-event {args.kind}", parameters={"note": args.note},
                 input_hash="", seed=None, output_file="", headline=args.note)
    print(dumps({"logged": args.kind, "hypothesis_id": h.id}))
    return 0


# ------------------------------------------------------------------ audit


def cmd_audit(args):
    hid = None
    prices, universe, factors = args.prices, args.universe, args.factors
    if Path(args.hypothesis).exists():
        spec = hyp.parse(args.hypothesis)
        try:
            hid = hyp.load_locked(args.hypothesis).id
        except RuleError:
            hid = None
        d = spec.get("data") or {}
        base = Path(args.hypothesis).parent
        res = lambda v: (str(base / v) if v and not Path(v).exists() and (base / v).exists() else v)  # noqa: E731
        prices = prices or res(d.get("prices"))
        universe = universe or res(d.get("universe"))
        factors = factors or res(d.get("factors"))
    if not prices:
        raise ContractError("pass --prices or a hypothesis file with data.prices")
    result = audit_mod.audit(prices, universe, factors)
    run = Run("audit", {"outlier_z": 10, "stale_run": 5}, {"prices": prices, "universe": universe, "factors": factors}, hid)
    p = run.write(result, headline=result["status"])
    emit(p, result, ["status", "failed", "warned", "checks"])
    return 2 if result["status"] == "FAIL" else 0


# ------------------------------------------------------------------ stats


def _series_arg(h, args) -> pd.Series:
    if args.series:
        return load_series(args.series, args.column, window=h.is_window)
    if args.asset:
        P = close_matrix(_is_prices(h))
        if args.asset not in P.columns:
            raise ContractError(f"asset {args.asset} not in prices")
        x = np.log(P[args.asset].dropna()) if args.transform in ("log", "logret") else P[args.asset].dropna()
        if args.transform == "logret":
            x = x.diff().dropna()
        return x
    raise ContractError("pass --series FILE [--column C] or --asset NAME")


def cmd_stats(args):
    h = _h(args)
    t = args.test
    params = {k: v for k, v in vars(args).items() if k not in ("func", "hypothesis") and v is not None}
    inputs = {"hypothesis": args.hypothesis}
    if getattr(args, "series", None):
        inputs["series"] = args.series
    if t == "multiple":
        pv = {}
        for f in args.outputs or []:
            d = json.loads(Path(f).read_text())
            r = d["result"]
            p = r.get("p_value", r.get("p_value_greater_than_zero"))
            pv[f"{d['command']}:{Path(f).stem}"] = p
            inputs[f"out:{Path(f).name}"] = f
        if args.pvalues:
            tab = read_table(args.pvalues)
            pv.update(dict(zip(tab["name"].astype(str), tab["p_value"].astype(float))))
            inputs["pvalues"] = args.pvalues
        if not pv:
            raise ContractError("pass --outputs qr-output/*.json and/or --pvalues FILE (columns name,p_value)")
        result = stats.multiple(pv, args.method, h.alpha)
        head = f"{result['n_rejected']}/{result['n_tests']} rejected ({args.method})"
    elif t == "ols":
        y = load_series(args.series, args.column, window=h.is_window)
        X = pd.concat([load_series(f.split(":")[0], f.split(":")[1] if ":" in f else None, window=h.is_window).rename(f.split(":")[-1])
                       for f in args.x], axis=1)
        for f in args.x:
            inputs[f"x:{f}"] = f.split(":")[0]
        result = stats.ols_hac(y, X, args.lags, h.alpha)
        key = list(result["coefficients"])[-1]
        result["p_value"] = result["coefficients"][key]["p_value"]
        result["statistic"] = result["coefficients"][key]["t"]
        head = f"t={result['statistic']:.3f}"
    else:
        x = _series_arg(h, args)
        if t == "adf":
            result = stats.adf(x)
        elif t == "kpss":
            result = stats.kpss_test(x)
        elif t == "stationarity":
            result = stats.stationarity(x, h.alpha)
        elif t == "ljung-box":
            result = stats.ljung_box(x, args.lags or 10)
        elif t == "hac-mean":
            result = stats.hac_mean(x, args.lags, args.alternative, h.alpha, h.ppy)
        elif t == "bootstrap":
            seed = require_seed(args.seed)
            result = stats.block_bootstrap(x, args.statistic, args.reps, seed, h.alpha, ppy=h.ppy)
            result["p_value"] = result["p_value_greater_than_zero"]
        elif t == "sharpe":
            result = stats.sharpe(x, h.ppy, h.alpha, args.lags)
            result["p_value"] = result["p_value_greater_than_zero"]
        else:
            raise ContractError(f"unknown test {t}")
        head = f"p={result.get('p_value', float('nan'))}"
    run = Run(f"stats {t}", params, inputs, h.id, getattr(args, "seed", None))
    p = run.write(result, head)
    emit(p, result)
    return 0


# ------------------------------------------------------------------ meanrev


def cmd_meanrev(args):
    h = _h(args)
    m = args.method_name
    params = _params(f"meanrev {m}", args)
    inputs = {"hypothesis": args.hypothesis, "prices": h.data_path("prices")}
    run = None
    if m in ("engle-granger", "hedge-ratio"):
        P = close_matrix(_is_prices(h))
        for a in (args.a, args.b):
            if a not in P.columns:
                raise ContractError(f"asset {a} not in prices")
        tr = np.log if args.levels == "log" else (lambda s: s)
        A, B = tr(P[args.a]), tr(P[args.b])
    if m == "engle-granger":
        result = meanrev.engle_granger(A, B, h.alpha)
        result["spread_construction"] = f"{args.levels} prices; spread = {args.a} - alpha - beta * {args.b}"
        head = result["verdict"]
    elif m == "hedge-ratio":
        df = meanrev.hedge_ratio(A, B, args.mode, args.fit, args.formation, args.window, args.refit_every)
        run = Run(f"meanrev {m}", params, inputs, h.id)
        df = df.assign(asset_a=args.a, asset_b=args.b)
        sp = _write_series(run, df.set_index("date"), "spread")
        result = {"series_file": str(sp), "mode": args.mode, "fit": args.fit, "levels": args.levels,
                  "hedge_turnover": meanrev.hedge_turnover(df["beta"], h.ppy),
                  "beta_first": float(df["beta"].iloc[0]), "beta_last": float(df["beta"].iloc[-1]),
                  "n": int(len(df)), "start": df["date"].min(), "end": df["date"].max(),
                  "spread_construction": f"{args.levels} prices; spread = {args.a} - alpha_t - beta_t * {args.b}; "
                                         "beta_t estimated on bars before t only",
                  "trial_note": "each mode/window/formation tried is a separate trial"}
        if args.mode == "rolling":
            result["warning"] = "rolling window length is a parameter: every length tried counts as a trial"
        head = f"hedge turnover/yr {result['hedge_turnover']['abs_dbeta_per_year']:.3f}"
    elif m == "zscore":
        inputs["hedge"] = args.hedge
        df = pd.read_csv(args.hedge, parse_dates=["date"])
        df = df[in_window(df["date"], h.is_window)]
        df["z"] = meanrev.zscore(df["spread"], args.window).values
        run = Run(f"meanrev {m}", params, inputs, h.id)
        zp = _write_series(run, df.set_index("date"), "zscore")
        result = {"series_file": str(zp), "window": args.window, "n": int(df["z"].notna().sum()),
                  "note": "trailing mean/std over the last `window` bars up to t; thresholds must be fixed in-sample and frozen"}
        head = f"zscore window {args.window}"
    elif m == "pairs-weights":
        inputs["zscore"] = args.zscore
        df = pd.read_csv(args.zscore, parse_dates=["date"])
        a, b = df["asset_a"].iloc[0], df["asset_b"].iloc[0]
        W = meanrev.pairs_weights(df, a, b, args.entry, args.exit, args.stop)
        run = Run(f"meanrev {m}", params, inputs, h.id)
        wp = run.series_path("weights")
        W.to_csv(wp, index=False, float_format="%.10g")
        result = {"weights_file": str(wp), "entry": args.entry, "exit": args.exit, "stop": args.stop,
                  "fraction_in_market": float((W.groupby("date")["weight"].apply(lambda s: s.abs().sum()) > 0).mean()),
                  "note": "leg weights move with beta_t, so hedge rebalancing is charged by `qrkit backtest`"}
        head = "pairs weights"
    elif m in ("variance-ratio", "half-life"):
        x = _series_arg(h, args)
        if m == "variance-ratio":
            result = meanrev.variance_ratio(x, args.lags or 5)
        else:
            result = meanrev.half_life(x, args.holding_period)
        head = m
    else:
        raise ContractError(m)
    run = run or Run(f"meanrev {m}", params, inputs, h.id)
    p = run.write(result, head)
    emit(p, result)
    return 0


# ------------------------------------------------------------------ momentum


def cmd_momentum(args):
    h = _h(args)
    m = args.method_name
    params = _params(f"momentum {m}", args)
    inputs = {"hypothesis": args.hypothesis, "prices": h.data_path("prices")}
    prices = _is_prices(h)
    P = close_matrix(prices)
    if m == "signal":
        sig, errors = momentum.signal(P, args.kind, args.lookback, args.skip, h.ppy)
        run = Run(f"momentum {m}", params, inputs, h.id)
        sp = run.series_path("signal")
        sig.to_csv(sp, index=False, float_format="%.10g")
        result = {"signal_file": str(sp), "kind": args.kind, "lookback": args.lookback, "skip": args.skip,
                  "errors": errors, "n_rows": int(len(sig)),
                  "definition": f"past return close[t-{args.skip}]/close[t-{args.skip + args.lookback}] - 1"
                                + (" scaled: sign / ex-ante EWMA vol (com 60)" if args.kind == "ts" else "")}
        head = "ERROR: no skip period" if errors else "signal"
        if errors:
            print("ERROR: " + errors[0], file=sys.stderr)
    elif m == "portfolio":
        inputs["signal"] = args.signal
        sig = pd.read_csv(args.signal, parse_dates=["date"])
        sig = sig[in_window(sig["date"], h.is_window)]
        liq = None
        if args.min_dollar_volume and "volume" in prices.columns:
            liq = (P * close_matrix(prices, "volume")).rolling(20).mean()
        W = momentum.portfolio(sig, args.kind, args.quantiles, args.holding, args.rebalance, args.target_vol, liq,
                               args.min_dollar_volume)
        run = Run(f"momentum {m}", params, inputs, h.id)
        wp = run.series_path("weights")
        W.to_csv(wp, index=False, float_format="%.10g")
        result = {"weights_file": str(wp), "kind": args.kind, "quantiles": args.quantiles, "holding": args.holding,
                  "rebalance": args.rebalance, "n_rebalances": int(W["date"].nunique()),
                  "note": "equal-weight legs; check a liquidity-filtered variant (--min-dollar-volume) because micro-caps dominate equal weighting"}
        head = "portfolio"
    elif m == "ic":
        inputs["signal"] = args.signal
        sig = pd.read_csv(args.signal, parse_dates=["date"])
        sig = sig[in_window(sig["date"], h.is_window)]
        result = momentum.rank_ic(sig, P, args.horizon, args.step)
        ics = result.pop("series")
        run = Run(f"momentum {m}", params, inputs, h.id)
        result["ic_series_file"] = str(_write_series(run, ics.rename("ic").rename_axis("date").to_frame(), "ic"))
        head = f"IC={result['mean_ic']:.4f} p={result['p_value']:.4g}"
    elif m == "tsmom":
        result = momentum.tsmom_regression(P, args.lookback_periods, args.skip_periods, args.period, h.ppy)
        head = f"slope t={result['statistic']:.3f}"
    else:
        raise ContractError(m)
    run = locals().get("run") or Run(f"momentum {m}", params, inputs, h.id)
    p = run.write(result, head)
    emit(p, result)
    return 0


# ------------------------------------------------------------------ backtest / costs


def _bt(h, weights_path, prices, delay=0, cost_multiplier=1.0):
    W = load_weights(weights_path)
    P = close_matrix(prices)
    V = close_matrix(prices, "volume") if "volume" in prices.columns else None
    W = W[W["date"] <= P.index.max()]
    return bt_mod.run(P, W, _costs(h), float(h.spec["capital"]), delay, V, cost_multiplier), P


def cmd_backtest(args):
    h = _h(args)
    prices = _is_prices(h)
    bt, P = _bt(h, args.weights, prices, args.delay)
    params = {"delay": args.delay, "costs": h.spec["costs"], "capital": h.spec["capital"]}
    run = Run("backtest", params, {"hypothesis": args.hypothesis, "weights": args.weights, "prices": h.data_path("prices")}, h.id)
    sp = _write_series(run, bt, "returns")
    summary = bt_mod.summarize(bt, h.ppy, bt_mod.market_proxy(P))
    result = {"returns_file": str(sp), "summary": summary, "window": "in-sample",
              "timing": "weight dated t earns the return t -> t+1" + (f", plus {args.delay} bar(s) delay" if args.delay else "")}
    p = run.write(result, f"net SR {summary['net']['sharpe_annualised']:.3f}")
    emit(p, result)
    return 0


def cmd_costs(args):
    h = _h(args)
    bt = pd.read_csv(args.backtest, parse_dates=["date"], index_col="date")
    bt = bt[in_window(bt.index, h.is_window)]
    summary = bt_mod.summarize(bt, h.ppy)
    result = {"cost_assumptions": h.spec["costs"], "capital": h.spec["capital"],
              "costs_per_year": summary["costs_per_year"], "turnover_per_year": summary["turnover_per_year"],
              "break_even_cost_bps_per_unit_turnover": summary["break_even_cost_bps_per_unit_turnover"],
              "assumed_linear_cost_bps": float(h.spec["costs"]["half_spread_bps"]) + float(h.spec["costs"]["commission_bps"]),
              "sweep": bt_mod.cost_sweep(bt, h.ppy)}
    be = result["break_even_cost_bps_per_unit_turnover"]
    result["margin_of_safety"] = (be / result["assumed_linear_cost_bps"]) if be is not None and result["assumed_linear_cost_bps"] > 0 else None
    run = Run("costs", {}, {"hypothesis": args.hypothesis, "backtest": args.backtest}, h.id)
    p = run.write(result, f"break-even {be}")
    emit(p, result)
    return 0


# ------------------------------------------------------------------ validate / exposure / red flags


def _trial_sharpes(hid: str, ppy: int) -> list[float]:
    t = hyp.read_trials()
    rows = t[(t["hypothesis_id"] == hid) & (t["command"] == "backtest")].drop_duplicates("input_hash", keep="last")
    out = []
    for f in rows["output_file"]:
        try:
            d = json.loads(Path(f).read_text())
            out.append(d["result"]["summary"]["net"]["sharpe_annualised"] / np.sqrt(ppy))
        except Exception:  # noqa: BLE001
            pass
    return out


def cmd_validate(args):
    h = _h(args)
    if args.oos:
        marker = output_dir() / "oos" / f"{h.id}.json"
        if marker.exists():
            raise RuleError(f"out-of-sample validation already ran for {h.id} ({marker}). It runs once per hypothesis id: "
                            "a second look turns the OOS window into in-sample data. A new idea needs a new hypothesis "
                            "and fresh out-of-sample data.")
        prices = load_prices(h.data_path("prices"), window=(h.is_window[0], h.oos_window[1]))
        chain = None
        if args.from_output:
            from .replay import replay

            W, chain = replay(args.from_output, prices, h.ppy)
            wpath = output_dir() / "oos" / f"{h.id}-weights.csv"
            wpath.parent.mkdir(parents=True, exist_ok=True)
            W.to_csv(wpath, index=False, float_format="%.10g")
        elif args.weights:
            wpath = args.weights
        else:
            raise ContractError("--oos needs --from <qrkit weights output JSON> (replayed with frozen parameters) "
                                "or --weights <your engine's weights covering the OOS window>")
        bt, P = _bt(h, wpath, prices)
        bt = bt[in_window(bt.index, h.oos_window)]
        if len(bt) < 20:
            raise ContractError("fewer than 20 OOS periods with positions: check the weights cover the OOS window")
        res = {"oos": validate.oos_result(bt["net"], h.alpha, h.ppy), "summary": bt_mod.summarize(bt, h.ppy, bt_mod.market_proxy(P)),
               "window": [h.oos_window[0], h.oos_window[1]], "one_time": True, "replayed_chain": chain}
        run = Run("validate oos", {"from": args.from_output}, {"hypothesis": args.hypothesis, "weights": str(wpath), "prices": h.data_path("prices")}, h.id)
        res["returns_file"] = str(_write_series(run, bt, "oos-returns"))
        p = run.write(res, f"OOS {'PASS' if res['oos']['passed'] else 'FAIL'} SR {res['oos']['sharpe_annualised']:.3f}")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(dumps({"hypothesis_id": h.id, "output_file": str(p)}) + "\n")
        emit(p, res, ["oos", "window"])
        return 0
    if not args.backtest:
        raise ContractError("pass --backtest qr-output/series/backtest-...-returns.csv (or --oos --weights for the one-time OOS run)")
    bt = pd.read_csv(args.backtest, parse_dates=["date"], index_col="date")
    bt = bt[in_window(bt.index, h.is_window)]
    tc = hyp.trial_count(h.id)
    n_trials = max(tc["strategy_variants"], 1)
    res = {"walk_forward": validate.walk_forward(bt["net"], args.folds, h.ppy),
           "deflated_sharpe": validate.deflated_sharpe(bt["net"], n_trials, _trial_sharpes(h.id, h.ppy)),
           "dsr_threshold": h.dsr_threshold, "trials": tc}
    res["dsr_passed"] = res["deflated_sharpe"]["dsr"] >= h.dsr_threshold
    run = Run("validate", {"folds": args.folds, "n_trials": n_trials}, {"hypothesis": args.hypothesis, "backtest": args.backtest}, h.id)
    p = run.write(res, f"DSR {res['deflated_sharpe']['dsr']:.3f}")
    emit(p, res)
    return 0


def cmd_exposure(args):
    h = _h(args)
    bt = pd.read_csv(args.backtest, parse_dates=["date"], index_col="date")
    bt = bt[in_window(bt.index, h.is_window)]
    P = close_matrix(_is_prices(h))
    fpath = args.factors or h.data_path("factors")
    F = load_factors(fpath, window=h.is_window) if fpath else None
    res = validate.exposure(bt["net"], bt_mod.market_proxy(P), F)
    run = Run("exposure", {}, {"hypothesis": args.hypothesis, "backtest": args.backtest, "factors": fpath}, h.id)
    p = run.write(res, f"{res['status']} alpha t={res['alpha_t']:.2f}")
    emit(p, res, ["status", "regressors", "alpha_per_period", "alpha_t", "alpha_p_value", "note"])
    return 0


def cmd_red_flags(args):
    h = _h(args)
    bt = pd.read_csv(args.backtest, parse_dates=["date"], index_col="date")
    bt = bt[in_window(bt.index, h.is_window)]
    delayed = None
    inputs = {"hypothesis": args.hypothesis, "backtest": args.backtest}
    if args.weights:
        inputs["weights"] = args.weights
        bd, _ = _bt(h, args.weights, _is_prices(h), delay=1)
        sd = bd["net"].std(ddof=1)
        delayed = float(bd["net"].mean() / sd * np.sqrt(h.ppy)) if sd > 0 else 0.0
    sweep = None
    if args.sweep:
        inputs["sweep"] = args.sweep
        sweep = read_table(args.sweep)
    flags = validate.red_flags(bt, h.ppy, delayed, sweep)
    res = {"flags": flags, "n_flags": len(flags), "net_sharpe_with_one_bar_delay": delayed,
           "checked": ["sharpe_above_2_daily", "driven_by_one_period"]
           + (["edge_lost_with_one_bar_delay"] if args.weights else [])
           + (["driven_by_one_parameter_value"] if args.sweep else []),
           "not_checked": ([] if args.weights else ["edge_lost_with_one_bar_delay (pass --weights)"])
           + ([] if args.sweep else ["driven_by_one_parameter_value (pass --sweep param,metric CSV)"])}
    run = Run("red-flags", {}, inputs, h.id)
    p = run.write(res, f"{len(flags)} flags")
    emit(p, res)
    return 0


def cmd_report(args):
    h = _h(args)
    over = {"test": args.test, "backtest": args.backtest_out, "oos": args.oos_out}
    computed, md = report.build(h, over, args.review, args.interpretation)
    run = Run("report", {}, {"hypothesis": args.hypothesis, "review": args.review, "interpretation": args.interpretation}, h.id)
    mdp = output_dir() / f"report-{h.id}.md"
    mdp.write_text(md)
    computed["markdown_file"] = str(mdp)
    p = run.write(computed, computed["conclusion"])
    emit(p, computed, ["conclusion", "suggested_decision", "reasons", "red_flags", "markdown_file"])
    return 0


def cmd_synth(args):
    seed = require_seed(args.seed)
    res = synth.make(args.kind, seed, Path(args.out))
    print(dumps(res))
    return 0


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qrkit", description="Deterministic quant research computations. Every command writes JSON to qr-output/ and logs to qr-output/trials.csv.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def hyp_arg(p):
        p.add_argument("--hypothesis", default="hypothesis.yaml", help="locked hypothesis file (default hypothesis.yaml)")

    p = sub.add_parser("hypothesis", help="check or lock a pre-registered hypothesis")
    p.add_argument("action", choices=["check", "lock"])
    p.add_argument("file", nargs="?", default="hypothesis.yaml")
    p.set_defaults(func=cmd_hypothesis)

    p = sub.add_parser("log-event", help="log an event such as an early look at OOS data")
    p.add_argument("--kind", required=True, choices=["oos_peek", "data_fix", "note"])
    p.add_argument("--note", required=True)
    hyp_arg(p)
    p.set_defaults(func=cmd_log_event)

    p = sub.add_parser("audit", help="data quality audit (full period)")
    p.add_argument("--prices")
    p.add_argument("--universe")
    p.add_argument("--factors")
    hyp_arg(p)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("stats", help="statistical tests (in-sample window only)")
    p.add_argument("test", choices=["adf", "kpss", "stationarity", "ljung-box", "hac-mean", "ols", "bootstrap", "multiple", "sharpe"])
    p.add_argument("--series", help="file with a date column")
    p.add_argument("--column")
    p.add_argument("--asset", help="use an asset's price from the hypothesis data instead of --series")
    p.add_argument("--transform", choices=["log", "level", "logret"], default="log")
    p.add_argument("--lags", type=int)
    p.add_argument("--alternative", choices=["greater", "less", "two-sided"], default="greater")
    p.add_argument("--x", action="append", help="regressor FILE:column (repeatable) for ols")
    p.add_argument("--statistic", choices=["sharpe", "mean"], default="sharpe")
    p.add_argument("--reps", type=int, default=5000)
    p.add_argument("--seed", type=int)
    p.add_argument("--method", choices=["holm", "bh", "bonferroni"], default="holm")
    p.add_argument("--outputs", nargs="*", help="qrkit output JSON files whose p-values to correct")
    p.add_argument("--pvalues", help="CSV with name,p_value")
    hyp_arg(p)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("meanrev", help="mean-reversion methods (in-sample window only)")
    p.add_argument("method_name", choices=["engle-granger", "variance-ratio", "half-life", "hedge-ratio", "zscore", "pairs-weights"])
    p.add_argument("--a")
    p.add_argument("--b")
    p.add_argument("--levels", choices=["log", "price"], default="log")
    p.add_argument("--series")
    p.add_argument("--column")
    p.add_argument("--asset")
    p.add_argument("--transform", choices=["log", "level", "logret"], default="log")
    p.add_argument("--lags", type=int)
    p.add_argument("--holding-period", type=int)
    p.add_argument("--mode", choices=["static", "rolling"], default="static")
    p.add_argument("--fit", choices=["ols", "tls"], default="tls")
    p.add_argument("--formation", type=int, default=252)
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--refit-every", type=int)
    p.add_argument("--hedge", help="hedge-ratio series CSV")
    p.add_argument("--zscore", help="zscore series CSV")
    p.add_argument("--entry", type=float, default=2.0)
    p.add_argument("--exit", type=float, default=0.5)
    p.add_argument("--stop", type=float)
    hyp_arg(p)
    p.set_defaults(func=cmd_meanrev)

    p = sub.add_parser("momentum", help="momentum methods (in-sample window only)")
    p.add_argument("method_name", choices=["signal", "portfolio", "ic", "tsmom"])
    p.add_argument("--kind", choices=["ts", "xs"], default="xs")
    p.add_argument("--lookback", type=int, default=231)
    p.add_argument("--skip", type=int, default=21)
    p.add_argument("--signal")
    p.add_argument("--quantiles", type=int, default=5)
    p.add_argument("--holding", type=int, default=1, help="number of overlapping cohorts (Jegadeesh-Titman)")
    p.add_argument("--rebalance", type=int, default=21)
    p.add_argument("--target-vol", type=float, default=0.4)
    p.add_argument("--min-dollar-volume", type=float)
    p.add_argument("--horizon", type=int, default=21)
    p.add_argument("--step", type=int, default=21)
    p.add_argument("--lookback-periods", type=int, default=12)
    p.add_argument("--skip-periods", type=int, default=0)
    p.add_argument("--period", type=int, default=21)
    hyp_arg(p)
    p.set_defaults(func=cmd_momentum)

    p = sub.add_parser("backtest", help="weights x prices -> gross and net returns (in-sample)")
    p.add_argument("--weights", required=True)
    p.add_argument("--delay", type=int, default=0)
    hyp_arg(p)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("costs", help="cost breakdown, sweep and break-even cost")
    p.add_argument("--backtest", required=True, help="returns CSV written by qrkit backtest")
    hyp_arg(p)
    p.set_defaults(func=cmd_costs)

    p = sub.add_parser("validate", help="walk-forward, PSR/DSR in-sample; --oos for the one-time out-of-sample run")
    p.add_argument("--backtest")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--oos", action="store_true")
    p.add_argument("--weights", help="--oos: your engine's weights covering the OOS window")
    p.add_argument("--from", dest="from_output", help="--oos: qrkit weights output JSON to replay with frozen parameters")
    hyp_arg(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("exposure", help="regression on market proxy and factors")
    p.add_argument("--backtest", required=True)
    p.add_argument("--factors")
    hyp_arg(p)
    p.set_defaults(func=cmd_exposure)

    p = sub.add_parser("red-flags", help="results too good, fragile or delay-sensitive")
    p.add_argument("--backtest", required=True)
    p.add_argument("--weights")
    p.add_argument("--sweep", help="CSV: parameter value, metric")
    hyp_arg(p)
    p.set_defaults(func=cmd_red_flags)

    p = sub.add_parser("report", help="final report: Markdown + JSON with computed conclusion")
    p.add_argument("--test")
    p.add_argument("--backtest-out")
    p.add_argument("--oos-out")
    p.add_argument("--review")
    p.add_argument("--interpretation")
    hyp_arg(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("synth", help="synthetic data with known truth")
    p.add_argument("kind", choices=list(synth.KINDS))
    p.add_argument("--seed", type=int)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_synth)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ContractError as e:
        print(f"qrkit: input rejected: {e}", file=sys.stderr)
        return 3
    except RuleError as e:
        print(f"qrkit: research rule: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
