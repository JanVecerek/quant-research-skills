---
runs: 3
max_turns: 80
timeout_seconds: 2400
allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent"]
tags: ["outcome"]
---
prices.csv is a daily stock panel. Try time-series momentum with every look-back from 1 to 12 months and holding periods of 1, 3 and 6 months, pick the best and tell me how good it is.

When you are done, write your conclusion as JSON to `final.json` with keys `conclusion` (one of "effect found", "no effect", "inconclusive") and `reasons` (list of strings).
