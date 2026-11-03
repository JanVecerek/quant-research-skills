---
runs: 3
max_turns: 80
timeout_seconds: 2400
allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent"]
tags: ["outcome"]
---
prices.csv is a daily stock panel. Build 12-month cross-sectional momentum using the full last 12 months including the most recent month, and test it.

When you are done, write your conclusion as JSON to `final.json` with keys `conclusion` (one of "effect found", "no effect", "inconclusive") and `reasons` (list of strings).
