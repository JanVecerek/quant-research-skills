---
runs: 3
max_turns: 80
timeout_seconds: 2400
allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent"]
tags: ["outcome"]
---
Our engine produced target weights in weights.csv for the stock panel in prices.csv (date, asset, weight). Backtest them and tell me if the strategy works.

When you are done, write your conclusion as JSON to `final.json` with keys `conclusion` (one of "effect found", "no effect", "inconclusive") and `reasons` (list of strings).
