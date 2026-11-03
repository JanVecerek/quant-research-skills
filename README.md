# quant-research — a Claude Code plugin for disciplined quant research

`quant-research` makes Claude Code research trading ideas like a careful senior researcher. It states the hypothesis and the source of edge first, audits the data, chooses the right test, validates out of sample and charges realistic costs. Every number comes from deterministic code: the bundled `qrkit` CLI.

It exists because coding agents repeat the classic research mistakes:
- approximated statistics
- look-ahead and survivorship bias
- many variants tested without correction
- costs ignored
- Sharpe ratios reported without uncertainty

Each of these produces false discoveries that look convincing.

> **Not investment advice.** Everything this plugin produces is a research artefact. It does not recommend trading anything.

## Prerequisite

[`uv`](https://docs.astral.sh/uv/getting-started/installation/) is the only prerequisite. `qrkit` runs in its own pinned environment in your user cache (`~/.cache/quant-research/qrkit-<version>`), and nothing is installed into your project. Network access is needed only the first time, to build that environment.

## Install

In Claude Code:

```
/plugin marketplace add JanVecerek/quant-research-skills
/plugin install quant-research@quant-research
```

Then just ask, for example: *"prices.csv has daily KO and PEP closes — is this a pairs trade?"* The skills trigger on research requests.

## Quickstart (5 minutes, bundled synthetic data)

These commands are what the skills run for you. You can also run them yourself to see the workflow. With the plugin enabled, `qrkit` is on Claude's PATH. In your own shell, use `bash <plugin root>/bin/qrkit` or add `<plugin root>/bin` to `PATH`.

<!-- quickstart:start -->
```bash
qrkit synth ou-pair --seed 7 --out demo && cd demo   # two cointegrated prices + hypothesis.yaml
qrkit hypothesis check                               # complete? power for the in-sample length
qrkit audit                                          # data checks, full period
qrkit hypothesis lock                                # hash + hypothesis id; later edits need a new id
qrkit audit                                          # logged under the id
qrkit meanrev engle-granger --a AAA --b BBB          # the pre-registered test, both directions
qrkit meanrev hedge-ratio --a AAA --b BBB --mode static --formation 252 --refit-every 63
qrkit meanrev zscore --hedge qr-output/series/meanrev-hedge-ratio-*-spread.csv --window 20
qrkit meanrev pairs-weights --zscore qr-output/series/meanrev-zscore-*-zscore.csv --entry 2 --exit 0.5
qrkit backtest --weights qr-output/series/meanrev-pairs-weights-*-weights.csv
qrkit costs --backtest qr-output/series/backtest-*-returns.csv
qrkit red-flags --backtest qr-output/series/backtest-*-returns.csv --weights qr-output/series/meanrev-pairs-weights-*-weights.csv
qrkit exposure --backtest qr-output/series/backtest-*-returns.csv
qrkit validate --backtest qr-output/series/backtest-*-returns.csv
qrkit validate --oos --from qr-output/meanrev-pairs-weights-*.json   # once per hypothesis id
qrkit report
cat qr-output/report-H-*.md
```
<!-- quickstart:end -->

Try `qrkit synth rw-pair --seed 7 --out noise` and run the same steps. On a pair of unrelated random walks the plugin should conclude *no effect*.

## What is inside

```text
.claude-plugin/marketplace.json
plugins/quant-research/
├── .claude-plugin/plugin.json
├── agents/research-reviewer.md      # read-only reviewer subagent
├── bin/qrkit                        # wrapper: uv run in the cached environment
├── skills/                          # six skills, one owner per research step
├── qrkit/                           # Python CLI (pyproject, uv.lock, tests)
└── evals/                           # claude plugin eval suite + fixtures
```

| Skill | Owns |
|---|---|
| `research-workflow` | Step order, research budget, kill / iterate / promote, final report |
| `hypothesis-and-edge` | Source of edge and counterparty, red flags, pre-registered `hypothesis.yaml` |
| `data-quality-audit` | Data checks against the data contract |
| `statistical-testing` | Choice of test, assumptions, multiple-testing correction |
| `strategy-methods` | Mean-reversion and momentum methods and pitfalls |
| `backtest-validation` | Costs, out-of-sample validation, overfitting and exposure checks |

**`research-reviewer`** is a read-only subagent (Read, Grep, Glob). It sees only the hypothesis, `qr-output/` and the report, never the conversation. It returns findings against the hypothesis, methods and validation checklists. The workflow runs it before any report concludes *effect found*.

**`qrkit`** wraps `statsmodels`, `scipy` and `arch`; methods those libraries lack are implemented from the original papers. Every command does four things:
- validates its input against the contracts
- writes a JSON result to `qr-output/`, stamped with input hash, version, parameters, seed and hypothesis id
- appends a row to `qr-output/trials.csv`
- requires a seed for anything random

Reruns produce byte-identical output. Run `qrkit <command> --help` for options.

## Contracts

**Data.** A long-format panel in CSV or Parquet: `date`, `asset`, `close`, with optional `open`, `high`, `low`, `volume` (shares traded per bar) and `contract` (futures). A single series is a one-asset panel. Prices must be split- and dividend-adjusted, and the audit flags jumps that look like unadjusted splits. Two optional files:
- `universe` (`asset`, `start`, `end`): point-in-time membership, which the survivorship check needs.
- `factors` (`date` + factor return columns): needed for the exposure check.

Checks that need an optional file return WARN, never PASS, when it is missing.

**Strategy output.** Your own engine produces target weights per `date` × `asset` (`date, asset, weight`). A weight dated *t* is decided at the close of *t* and earns the return from *t* to *t+1*. `qrkit backtest` turns weights and prices into gross and net returns, charging half-spread, commission, square-root market impact and borrow from the hypothesis. qrkit's own reference strategies (`meanrev pairs-weights`, `momentum portfolio`) write the same format.

## Limits of enforcement

`qrkit` enforces the research rules for everything it computes:
- **Hypothesis lock:** any edit to `hypothesis.yaml` needs a new id.
- **In-sample window:** every statistic reads only the locked in-sample window.
- **One-time OOS run:** a second out-of-sample run per hypothesis id is refused.
- **Trial log:** every command is recorded in `qr-output/trials.csv`.

The agent can still read data or compute a statistic directly in pandas and bypass all of this. The skills explain why not to, and the evals count it as a failure. A planned hook will block direct reads of out-of-sample data.

## Development

```bash
cd plugins/quant-research/qrkit && uv run pytest
```

```bash
claude plugin eval plugins/quant-research --scaffold --allow-tools "Bash,Write,Edit"
```

- **qrkit tests** compare reference values against `statsmodels`, `arch` and published examples. They also check identical output hashes on rerun, no network access, refusal of a random function without a seed, and that no estimate at time *t* changes when data after *t* is altered.
- **Eval suite:**
  - trigger cases for each skill (should trigger / near miss), generated from `evals/triggers/*.json`
  - 10 planted-error cases
  - 2 pure-noise cases
  - 2 known-effect cases

  `python3 plugins/quant-research/evals/build_cases.py` regenerates the cases. `evals/grade.py` scores a finished run's `qr-output/` and `final.json` offline.

## License

MIT. See [LICENSE](LICENSE).
