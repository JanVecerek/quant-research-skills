---
type: "regex"
pattern: "\"conclusion\"\\s*:\\s*\"effect found\""
match: "not_contains"
target: {"source": "file", "path": "final.json"}
arm: "both"
---

