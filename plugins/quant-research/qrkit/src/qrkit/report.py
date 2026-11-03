"""Final research report: computed conclusion, separate from the agent's interpretation."""

from __future__ import annotations

import json
from pathlib import Path

from .hypothesis import Hypothesis, trial_count
from .io import read_trials

STEP_COMMANDS = {
    "audit": ["audit"],
    "test": None,  # the hypothesis's own test
    "backtest": ["backtest"],
    "validate_is": ["validate"],
    "oos": ["validate oos"],
    "red_flags": ["red-flags"],
    "exposure": ["exposure"],
    "costs": ["costs"],
}


def latest_outputs(hid: str) -> dict[str, list[str]]:
    t = read_trials()
    t = t[t["hypothesis_id"] == hid]
    out: dict[str, list[str]] = {}
    for r in t.itertuples():
        out.setdefault(r.command, []).append(r.output_file)
    return out


def _load(path: str | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def build(h: Hypothesis, overrides: dict[str, str | None], review: str | None, interpretation: str | None) -> tuple[dict, str]:
    outs = latest_outputs(h.id)
    spec = h.spec

    used: dict[str, str] = {}

    def pick(step: str) -> dict | None:
        if overrides.get(step):
            used[step] = overrides[step]
            return _load(overrides[step])
        cmds = [spec["test"]] if step == "test" else STEP_COMMANDS[step]
        for c in cmds:
            if outs.get(c):
                used[step] = outs[c][-1]
                return _load(outs[c][-1])
        return None

    audit, test, bt, vis, oos, rf, ex, costs = (pick(s) for s in
                                                ("audit", "test", "backtest", "validate_is", "oos", "red_flags", "exposure", "costs"))
    lock = json.loads((Path("qr-output") / "hypotheses" / f"{h.id}.json").read_text()) if (Path("qr-output") / "hypotheses" / f"{h.id}.json").exists() else {}
    power = lock.get("power", {})
    trials = trial_count(h.id)
    alpha = h.alpha

    missing = [name for name, doc in (("audit", audit), ("in-sample test", test), ("backtest", bt),
                                      ("in-sample validation (DSR)", vis), ("out-of-sample validation", oos)) if doc is None]
    reasons = []
    audit_ok = audit is not None and audit["result"]["status"] != "FAIL"
    if audit is not None and not audit_ok:
        reasons.append(f"data audit FAILED: {audit['result']['failed']}")
    test_p = test["result"].get("p_value") if test else None
    test_pass = test_p is not None and test_p < alpha
    dsr = vis["result"]["deflated_sharpe"]["dsr"] if vis else None
    dsr_pass = dsr is not None and dsr >= h.dsr_threshold
    oos_pass = bool(oos and oos["result"]["oos"]["passed"])
    powered = bool(power.get("adequate"))

    test_failed_powered = test is not None and not test_pass and audit_ok
    if test_failed_powered:
        # the pre-registered test failed: "effect found" is impossible, so later steps (and spending
        # the OOS window) cannot change the conclusion
        missing = [m for m in missing if m not in ("backtest", "in-sample validation (DSR)", "out-of-sample validation")]
        if missing:
            conclusion = "inconclusive"
            reasons.append(f"steps missing: {missing}")
        elif powered:
            conclusion = "no effect"
            reasons.append(f"pre-registered in-sample test failed (p = {test_p:.4g} >= alpha {alpha}) with adequate power")
        else:
            conclusion = "inconclusive"
            reasons.append(f"pre-registered in-sample test failed (p = {test_p:.4g}) but power at the minimum effect is "
                           f"{power.get('power_at_min_effect', 0):.2f} < 0.80: not evidence of no effect")
    elif missing or not audit_ok:
        conclusion = "inconclusive"
        if missing:
            reasons.append(f"steps missing: {missing}")
    elif test_pass and oos_pass and dsr_pass:
        conclusion = "effect found"
    elif not powered:
        conclusion = "inconclusive"
        reasons.append(f"in-sample power {power.get('power_at_min_effect', 0):.2f} < 0.80 at the minimum effect: a negative result is not evidence of no effect")
    else:
        conclusion = "no effect"
    if conclusion != "effect found" and not missing and audit_ok and not test_failed_powered:
        reasons += [f"in-sample test p = {test_p:.4g} vs alpha {alpha}" + (" (pass)" if test_pass else " (fail)"),
                    f"deflated Sharpe {dsr:.3f} vs threshold {h.dsr_threshold}" + (" (pass)" if dsr_pass else " (fail)"),
                    "OOS " + ("pass" if oos_pass else "fail")]

    review_doc = Path(review).read_text() if review and Path(review).exists() else None
    review_status = "attached" if review_doc else "missing"
    if conclusion == "effect found" and review_status == "missing":
        reasons.append("research-reviewer findings not attached: run the research-reviewer subagent before relying on this conclusion")

    max_trials = int(spec["budget"]["max_trials"])
    budget_reached = trials["strategy_variants"] >= max_trials
    if conclusion == "effect found":
        decision = "promote"
    elif conclusion == "no effect" or budget_reached:
        decision = "kill"
    else:
        decision = "iterate"

    t = read_trials()
    peeks = t[(t["hypothesis_id"] == h.id) & (t["command"] == "log-event oos_peek")]

    flags = rf["result"]["flags"] if rf else []
    computed = {
        "hypothesis_id": h.id,
        "title": spec["title"],
        "h0": spec["h0"],
        "h1": spec["h1"],
        "conclusion": conclusion,
        "suggested_decision": decision,
        "reasons": reasons,
        "red_flags": flags,
        "red_flags_checked": rf is not None,
        "oos_peeks_logged": int(len(peeks)),
        "trials": trials,
        "budget": {"max_trials": max_trials, "used": trials["strategy_variants"], "reached": budget_reached},
        "power": power,
        "audit_status": audit["result"]["status"] if audit else None,
        "in_sample_test": {"command": spec["test"], "p_value": test_p, "alpha": alpha, "passed": test_pass,
                           "statistic": test["result"].get("statistic") if test else None,
                           "file": overrides.get("test") or (outs.get(spec["test"]) or [None])[-1]},
        "deflated_sharpe": {"dsr": dsr, "threshold": h.dsr_threshold, "passed": dsr_pass,
                            "n_trials": vis["result"]["deflated_sharpe"]["n_trials"] if vis else None},
        "in_sample_backtest": {"gross": bt["result"]["summary"]["gross"], "net": bt["result"]["summary"]["net"],
                               "break_even_cost_bps": bt["result"]["summary"]["break_even_cost_bps_per_unit_turnover"]} if bt else None,
        "oos": {"passed": oos_pass, "sharpe_annualised_net": oos["result"]["oos"]["sharpe_annualised"],
                "sharpe_ci_95": oos["result"]["oos"]["sharpe_ci"],
                "mean_annualised_net_ci_95": oos["result"]["oos"]["mean_test"]["ci_annualised"],
                "gross": oos["result"]["summary"]["gross"], "net": oos["result"]["summary"]["net"]} if oos else None,
        "exposure": {"status": ex["result"]["status"], "alpha_t": ex["result"]["alpha_t"], "note": ex["result"]["note"]} if ex else {"status": "WARN", "note": "exposure not checked"},
        "review_status": review_status,
        "sources": used,
    }
    md = render_md(computed, review_doc, Path(interpretation).read_text() if interpretation and Path(interpretation).exists() else None)
    return computed, md


def _f(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(_f(v, nd) for v in x) + "]"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_md(c: dict, review: str | None, interp: str | None) -> str:
    L = [f"# Research report — {c['title']}", "", f"Hypothesis id: `{c['hypothesis_id']}`", ""]
    if c["red_flags"]:
        L += ["## RED FLAGS", ""] + [f"- **{f['flag']}**: {f['detail']}" for f in c["red_flags"]] + [""]
    elif not c["red_flags_checked"]:
        L += ["## RED FLAGS", "", "- red flags were **not checked** (`qrkit red-flags` not run)", ""]
    L += ["## Conclusion (computed)", "", f"**{c['conclusion'].upper()}** — suggested decision: **{c['suggested_decision']}**", ""]
    L += [f"- {r}" for r in c["reasons"]] + [""]
    L += ["## Computed results", "", f"- H0: {c['h0']}", f"- H1: {c['h1']}",
          f"- Trials (strategy variants) for this id: {c['trials']['strategy_variants']} of budget {c['budget']['max_trials']}; commands run: {c['trials']['commands_run']}",
          f"- OOS peeks logged: {c['oos_peeks_logged']}",
          f"- Power at minimum effect (in-sample): {_f(c['power'].get('power_at_min_effect'))}",
          f"- Data audit: {c['audit_status']}",
          f"- In-sample test `{c['in_sample_test']['command']}`: statistic {_f(c['in_sample_test']['statistic'])}, p = {_f(c['in_sample_test']['p_value'], 4)} (alpha {c['in_sample_test']['alpha']})",
          f"- Deflated Sharpe: {_f(c['deflated_sharpe']['dsr'])} (threshold {c['deflated_sharpe']['threshold']}, trials {c['deflated_sharpe']['n_trials']})"]
    if c["in_sample_backtest"]:
        g, n = c["in_sample_backtest"]["gross"], c["in_sample_backtest"]["net"]
        L.append(f"- In-sample Sharpe gross {_f(g['sharpe_annualised'])} {_f(g['sharpe_ci_95_hac'])}, net {_f(n['sharpe_annualised'])} {_f(n['sharpe_ci_95_hac'])}; break-even cost {_f(c['in_sample_backtest']['break_even_cost_bps'], 1)} bps")
    if c["oos"]:
        o = c["oos"]
        L.append(f"- OOS net Sharpe {_f(o['sharpe_annualised_net'])}, 95% CI {_f(o['sharpe_ci_95'])}; gross Sharpe {_f(o['gross']['sharpe_annualised'])} {_f(o['gross']['sharpe_ci_95_hac'])}; {'PASS' if o['passed'] else 'FAIL'}")
    L.append(f"- Exposure: {c['exposure']['status']} — {c['exposure']['note']}")
    L += ["", "### Source files", ""] + [f"- `{k}`: `{v}`" for k, v in sorted(c["sources"].items())]
    L += ["", "## Reviewer findings", "", review.strip() if review else "_Not attached._", ""]
    L += ["## Interpretation (agent, not computed)", "", interp.strip() if interp else "_None supplied._", ""]
    L += ["---", "Research artefact, not investment advice."]
    return "\n".join(L) + "\n"
