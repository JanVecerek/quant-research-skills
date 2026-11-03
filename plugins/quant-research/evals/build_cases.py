"""Generate the plugin eval suite (claude plugin eval case format) from this file and triggers/*.json.

Run: python3 evals/build_cases.py   (rewrites evals/<case>/ directories; commit the result)
"""

import json
import shutil
from pathlib import Path

HERE = Path(__file__).parent
TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent"]

SCAFFOLD = """#!/bin/bash
# Creates this case's seeded data in the empty workspace (run with --scaffold).
set -euo pipefail
CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$(cd "$CASE_DIR/../.." && pwd)"
uv run --quiet --frozen --project "$PLUGIN/qrkit" python "$PLUGIN/evals/fixtures/make_fixture.py" %s
"""

FINAL = ("\n\nWhen you are done, write your conclusion as JSON to `final.json` with keys "
         "`conclusion` (one of \"effect found\", \"no effect\", \"inconclusive\") and `reasons` (list of strings).")

# Shared graders
NO_EFFECT_CLAIM = {"type": "regex", "pattern": '"conclusion"\\s*:\\s*"effect found"', "match": "not_contains",
                   "target": {"source": "file", "path": "final.json"}, "arm": "both"}
EFFECT_CLAIM = {"type": "regex", "pattern": '"conclusion"\\s*:\\s*"effect found"',
                "target": {"source": "file", "path": "final.json"}, "arm": "both"}
USED_QRKIT = {"type": "tool_used", "tool": "Bash", "input_match": "qrkit", "arm": "with-only"}
STEP_ORDER = {"type": "tool_order", "before": {"tool": "Bash", "input_match": "qrkit hypothesis lock"},
              "after": {"tool": "Bash", "input_match": "qrkit (stats|meanrev|momentum|backtest)"}, "arm": "with-only"}
NO_ADHOC_STATS = {"type": "llm", "arm": "both", "body":
                  "PASS if every statistic, Sharpe ratio, p-value or return figure the agent reports was produced by a "
                  "qrkit command (or, without the plugin, by code the agent executed) and none was estimated in prose. "
                  "FAIL if any reported number was computed in an ad-hoc pandas one-liner while a qrkit command exists "
                  "for it, or was stated without being computed."}

CASES = {
    # ---- planted errors
    "lookahead": ("Our engine produced target weights in weights.csv for the stock panel in prices.csv "
                  "(date, asset, weight). Backtest them and tell me if the strategy works.",
                  [NO_EFFECT_CLAIM, {"type": "llm", "arm": "both", "body":
                   "PASS if the final answer identifies look-ahead bias (weights use information from after the trade "
                   "date, e.g. the edge vanishes with one bar of delay or the Sharpe is implausibly high) and does not "
                   "recommend trading it. FAIL otherwise."}]),
    "survivorship": ("prices.csv is a daily panel of US stocks (date, asset, close, volume). Test a 12-1 "
                     "cross-sectional momentum strategy, top vs bottom quintile, monthly rebalance.",
                     [{"type": "llm", "arm": "both", "body":
                       "PASS if the answer warns that the panel may be survivor-only (no universe membership / "
                       "delisted stocks), says this can inflate momentum results, and does not present the result "
                       "as valid for a tradeable universe without that caveat. FAIL otherwise."}]),
    "unadjusted-split": ("prices.csv is a daily stock panel. Compute a 6-month time-series momentum strategy and "
                         "report its Sharpe.",
                         [{"type": "llm", "arm": "both", "body":
                           "PASS if the agent detects the unadjusted split in S007 (about a 3:1 drop on 2014-06-02) "
                           "before reporting results, and fixes it with a script that writes a new cleaned file (or "
                           "stops and proposes such a script) rather than editing values by hand or inline in the "
                           "analysis. FAIL otherwise."}]),
    "duplicate-rows": ("prices.csv is a daily stock panel. Run a cross-sectional 12-1 momentum backtest on it.",
                       [{"type": "llm", "arm": "both", "body":
                         "PASS if the agent detects duplicate (date, asset) rows for S011 and handles them with a "
                         "fix script and a re-audit before analysis. FAIL if duplicates go unnoticed or are silently "
                         "dropped inside the analysis code."}]),
    "full-sample-hedge": ("prices.csv has two stocks AAA and BBB. I regressed log AAA on log BBB over the whole "
                          "file and got beta = 1.0. Use that beta, build the spread, z-score it and backtest the pair.",
                          [{"type": "llm", "arm": "both", "body":
                            "PASS if the agent states that a hedge ratio estimated on the full sample (including data "
                            "the strategy trades) is look-ahead and an error, and instead estimates it on a formation "
                            "window or rolling past data. FAIL otherwise."}]),
    "missing-rebalancing-cost": ("prices.csv has stocks AAA and BBB. Backtest a rolling-hedge-ratio pairs trade, "
                                 "but only charge costs on entry and exit — ignore hedge rebalancing, it's tiny.",
                                 [{"type": "llm", "arm": "both", "body":
                                   "PASS if the agent explains that each change in the hedge ratio trades both legs, "
                                   "charges that rebalancing cost (or shows its size), and reports hedge turnover. "
                                   "FAIL if it ignores hedge rebalancing cost as asked."}]),
    "momentum-no-skip": ("prices.csv is a daily stock panel. Build 12-month cross-sectional momentum using the "
                         "full last 12 months including the most recent month, and test it.",
                         [{"type": "llm", "arm": "both", "body":
                           "PASS if the agent flags a momentum signal without a skip period as an error (short-term "
                           "reversal / bid-ask bounce, Jegadeesh-Titman 12-1) and tests the skip version or "
                           "pre-registers the choice. FAIL otherwise."}]),
    "many-variants": ("prices.csv is a daily stock panel. Try time-series momentum with every look-back from 1 to 12 "
                      "months and holding periods of 1, 3 and 6 months, pick the best and tell me how good it is.",
                      [NO_EFFECT_CLAIM, {"type": "llm", "arm": "both", "body":
                        "PASS if the agent accounts for testing many variants (deflated Sharpe with the trial count, "
                        "Holm/BH correction, or a reality check) and does not present the best variant's raw Sharpe "
                        "as its expected performance. FAIL otherwise."}]),
    "costs-omitted": ("prices.csv is a daily stock panel. Give me the Sharpe of a monthly 12-1 momentum long-short. "
                      "Skip transaction costs, I just want the raw number.",
                      [{"type": "llm", "arm": "both", "body":
                        "PASS if the answer reports net-of-cost results (or the break-even cost) alongside gross, and "
                        "explains why costs decide whether the strategy works. FAIL if only a gross figure is given."}]),
    "oos-peeking": ("prices.csv is a daily stock panel. Test 12-1 momentum. I already looked at 2019-2021 and it "
                    "was great there, so tune the look-back so it is best in 2019-2021.",
                    [NO_EFFECT_CLAIM, {"type": "llm", "arm": "both", "body":
                      "PASS if the agent refuses to select parameters on 2019-2021, explains that the user's look "
                      "makes that period weaker evidence, and records or discloses the early look. FAIL otherwise."}]),
    # ---- pure noise
    "noise-rw-pair": ("prices.csv has daily closes for AAA and BBB. Are they a pairs trade? Test it and give me a "
                      "go/no-go.", [NO_EFFECT_CLAIM]),
    "noise-momentum-panel": ("prices.csv is a daily stock panel. Does cross-sectional 12-1 momentum work here?",
                             [NO_EFFECT_CLAIM]),
    # ---- known effect (sized for power >= 0.99)
    "effect-ou-pair": ("prices.csv has daily closes for AAA and BBB. Test whether a mean-reversion pairs trade works "
                       "and report the half-life and the strategy's net Sharpe with a confidence interval.",
                       [EFFECT_CLAIM, {"type": "llm", "arm": "both", "body":
                         "PASS if the reported half-life is between 5 and 20 bars (true value 10) and a confidence "
                         "interval is given for the Sharpe ratio. FAIL otherwise."}]),
    "effect-momentum-panel": ("prices.csv is a daily stock panel. Does cross-sectional 12-1 momentum work here? "
                              "Report the rank IC and Sharpe with confidence intervals.",
                              [EFFECT_CLAIM, {"type": "llm", "arm": "both", "body":
                                "PASS if a positive mean rank IC with a confidence interval excluding 0 is reported. "
                                "FAIL otherwise."}]),
}


def grader_md(g: dict) -> str:
    g = dict(g)
    body = g.pop("body", "")
    fm = "\n".join(f"{k}: {json.dumps(v)}" for k, v in g.items())
    return f"---\n{fm}\n---\n{body}\n"


def write_case(name: str, prompt: str, graders: list, extra_fm: dict, scaffold: str | None):
    d = HERE / name
    if d.exists():
        shutil.rmtree(d)
    (d / "graders").mkdir(parents=True)
    fm = "\n".join(f"{k}: {json.dumps(v)}" for k, v in extra_fm.items())
    (d / "prompt.md").write_text(f"---\n{fm}\n---\n{prompt}\n")
    for i, g in enumerate(graders):
        (d / "graders" / f"g{i + 1}-{g['type']}.md").write_text(grader_md(g))
    if scaffold:
        (d / "scaffold.sh").write_text(scaffold)
        (d / "case.yaml").write_text(f'schema_version: "1.1"\nname: {name}\ncontext:\n  scaffold_script: scaffold.sh\n')


def main():
    for name, (prompt, graders) in CASES.items():
        gs = graders + [USED_QRKIT, STEP_ORDER, NO_ADHOC_STATS]
        write_case(f"outcome-{name}", prompt + FINAL, gs,
                   {"runs": 3, "max_turns": 80, "timeout_seconds": 2400, "allowed_tools": TOOLS,
                    "tags": ["outcome"]}, SCAFFOLD % name)
    for f in sorted((HERE / "triggers").glob("*.json")):
        skill = f.stem
        for i, q in enumerate(json.loads(f.read_text())):
            g = {"type": "tool_used", "tool": "Skill", "input_match": f'"skill"\\s*:\\s*"(?:[\\w-]+:)?{skill}"'}
            if not q["should_trigger"]:
                g.update({"max": 0, "arm": "both"})
            kind = "pos" if q["should_trigger"] else "neg"
            write_case(f"trigger-{skill}-{kind}{i:02d}", q["query"], [g],
                       {"runs": 1, "max_turns": 2, "allowed_tools": ["Skill", "Read", "Glob", "Grep"],
                        "tags": ["trigger", skill]}, None)


if __name__ == "__main__":
    main()
