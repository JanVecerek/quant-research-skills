# Baseline and skill-iteration notes

Three scenarios were run with fresh subagents, first **without** the plugin (RED) and then **with** the skills and qrkit (GREEN), on the same data. The data were 60 synthetic daily stocks for 2012–2023, with planted problems:
- 10 duplicate rows
- one unadjusted 2:1 split
- one delisting
- a non-cointegrated "KO/PEP" pair

These are single runs per arm. They show direction only; the scored comparison is the `claude plugin eval` suite.

## Observed failures without the plugin (RED)

| Scenario | Failures |
|---|---|
| Pairs, "go/no-go by end of day" | No hypothesis, source of edge or kill criteria. About 20 cointegration tests (full sample, halves, 11 rolling windows, Johansen) run with no multiple-testing correction. Full-sample tests looked at the later "OOS" half. Static hedge with no rebalancing cost and no hedge turnover. No Sharpe confidence interval. A Johansen `ComplexWarning` was ignored. |
| Cross-sectional momentum | Good data checks, but the split was fixed by halving prices inline as a "judgement call". No OOS split. No Sharpe CI. "Mostly the market" was claimed without an exposure regression. Variants were tried without a deflated Sharpe. No three-way conclusion. |
| 36-variant TSMOM grid, user had peeked at 2020–2023 | Handled selection well (deflated Sharpe, reality check). Signal not volatility-scaled. The peek was not logged. No pre-registration, and no kill / iterate / promote decision. |

All three baselines computed every number in ad-hoc scripts that were not logged or restricted to a window.

## With the plugin (GREEN)

All three runs did the following:
- wrote and locked a hypothesis before testing
- audited the data
- fixed the data with a script (`scripts/fix_prices.py`) when the audit failed
- computed no statistics outside qrkit
- ran OOS once
- reported one of the three conclusions, with file citations

The grid run refused to select on the peeked period and logged the peek. `evals/grade.py` passes on all three workspaces.

## Skill and qrkit changes made from GREEN feedback (REFACTOR)

- Power for `cointegration | variance_ratio | beta` metrics was meaningless. These metrics now require `min_sharpe`.
- Once the pre-registered test fails, *effect found* is impossible. The workflow now stops before OOS so the window stays unspent, and `qrkit report` concludes without it.
- `hypothesis check` no longer fails on dirty data before the audit has run.
- The report cites the files it actually used. The pre-registered test file was previously mis-cited.
- The skip-period error applies only to cross-sectional momentum, because Moskowitz–Ooi–Pedersen TSMOM uses no skip. The skill and the reference previously contradicted each other.
- Output JSON records only the parameters each command uses.
- New guidance covers:
  - grids: declare them, select in-sample only, let the deflated Sharpe charge for them
  - non-interactive data fixes: apply them and flag them as unconfirmed
  - reading hedge turnover
  - volume units
  - `qrkit report` flags
- New audit check: volume.
