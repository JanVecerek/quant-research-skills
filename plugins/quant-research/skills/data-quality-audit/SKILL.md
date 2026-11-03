---
name: data-quality-audit
description: Use when a new price or returns dataset arrives for research, before any analysis or backtest on it; when results look too good or a single asset dominates; when prices show jumps, splits, gaps, duplicates, stale values, odd timestamps or futures roll jumps; or when survivorship bias or delisted stocks may matter.
---

# Data quality audit

This skill owns **data checks against the data contract** (`qrkit audit`). It runs after the hypothesis is written and before it is locked. Step order belongs to `quant-research:research-workflow`.

**Core principle:** an error in the data does not look like an error in the results. It looks like alpha. Audit first, and fix with a script, never by hand.

`qrkit` means `bash ${CLAUDE_PLUGIN_ROOT}/bin/qrkit` (on PATH as `qrkit` while the plugin is enabled).

## Data contract

| File | Columns | Notes |
|---|---|---|
| Prices (required) | `date`, `asset`, `close`; optional `open`, `high`, `low`, `volume` (shares or contracts traded per bar; drives market impact), `contract` | Long format, CSV or Parquet. One series = one-asset panel. `close` must be split- and dividend-adjusted. Futures: back-adjusted continuous series, `contract` holds the underlying contract code. |
| Universe (optional) | `asset`, `start`, `end` (`end` empty = still a member) | Point-in-time membership, including delisted names. Needed for the survivorship check. |
| Factors (optional) | `date` + one numeric column per factor return | Needed to call a result alpha. |

Without the universe file the survivorship check is **WARN, never PASS**. Without the factor file, the exposure check is WARN.

## Run the audit

```bash
qrkit audit                                   # paths from hypothesis.yaml (data.prices / universe / factors)
qrkit audit --prices data/prices.parquet --universe data/universe.csv
```

The audit always checks the **full period, including out-of-sample**: data errors in the OOS window corrupt the one-time OOS test just as badly. It computes no returns or statistics you could use for the strategy.

Checks, each PASS / WARN / FAIL (SKIP when not applicable): duplicates, missing values, calendar gaps, stale prices, outliers (robust MAD z-score), invalid OHLC, jumps matching unadjusted splits, volume, time zones, index monotonicity, futures roll jumps, survivorship, factor coverage.

qrkit cannot check prices against an external reference. Look at the first and last close of a few assets and the median dollar volume reported by the `volume` check; if they are implausible for the named instruments (wrong currency, unadjusted, synthetic), tell the user before analysing.

Report every FAIL and WARN to the user with the examples qrkit lists. Do not summarise WARNs away.

## On FAIL: stop and propose a fix script

1. **Stop the analysis.** Do not run tests "on the data as it is for now". Why: results on bad data anchor everyone, including you.
2. **Write a fix script** in the project, e.g. `scripts/fix_prices.py`, that reads the raw file and writes a new cleaned file. Never edit the raw file and never patch values by hand or inline inside an analysis. Why: a script is reviewable and reruns on the next data delivery; a manual edit or an in-analysis adjustment is invisible and is a judgement call made after seeing the data.
3. Show the user each proposed fix and the evidence (e.g. "S05 2017-10-02 ratio 0.499 → 2:1 split; divide closes before that date by 2"). Ask before applying a fix that changes returns (split adjustments, dropping assets). Removing exact duplicate rows can be applied directly. If nobody can be asked (a non-interactive run), apply the fix in the script, and list it first among the report caveats as *unconfirmed*.
4. Log it: `qrkit log-event --kind data_fix --note "<fix and script path>"` (once the hypothesis is locked; before locking, put it in the hypothesis `rationale` or a project note).
5. Point `data.prices` in `hypothesis.yaml` to the cleaned file and run `qrkit audit` again until there is no FAIL.

| Finding | Typical fix in the script | Do not |
|---|---|---|
| Duplicate (date, asset) rows | Keep one if identical; if values differ, ask which source is right | Silently `drop_duplicates()` inside the analysis |
| Unadjusted split | Get adjusted prices from the vendor; otherwise divide pre-split closes by the ratio, after confirming the split date | Halve prices in the analysis "as a judgement call" |
| Futures roll jump | Back-adjust by the roll gap with a documented roll rule | Leave raw front-month prices |
| Calendar gaps / missing | Check against the exchange calendar; leave real gaps as missing | Forward-fill prices (creates stale returns) |
| Stale prices | Flag illiquid periods; exclude or mark them | Treat zero returns as real |
| Survivorship WARN | Ask for a point-in-time universe with delisted names and delisting returns | Assume the current constituents were always the universe |

## WARN

WARN does not stop the analysis, but every WARN goes into the final report's caveats. Survivorship WARN in particular means the user cannot claim the result holds for a tradeable universe. Why: survivor-only panels inflate momentum and long-only results, because the losers that disappeared are missing.

## After the lock

Once `qrkit hypothesis lock` has run, run `qrkit audit` once more so the audit is recorded under the hypothesis id; `qrkit report` treats a missing audit as a missing step.

## Common mistakes

| Mistake | Fix |
|---|---|
| Looking only at the in-sample period | The audit always covers the full file. |
| "Only 10 duplicates, not material" | Duplicates double-count returns and break joins; FAIL means fix. |
| Fixing data and re-testing in one step | Fix, re-audit, then lock; the cleaned file is a different input. |
| Writing your own checks in pandas instead | Use `qrkit audit`; it is logged and identical every time. Add a project-specific check as a script only if qrkit lacks it, and say so. |
