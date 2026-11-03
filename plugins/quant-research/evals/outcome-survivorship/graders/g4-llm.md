---
type: "llm"
arm: "both"
---
PASS if every statistic, Sharpe ratio, p-value or return figure the agent reports was produced by a qrkit command (or, without the plugin, by code the agent executed) and none was estimated in prose. FAIL if any reported number was computed in an ad-hoc pandas one-liner while a qrkit command exists for it, or was stated without being computed.
