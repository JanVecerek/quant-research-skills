---
type: "llm"
arm: "both"
---
PASS if the agent detects duplicate (date, asset) rows for S011 and handles them with a fix script and a re-audit before analysis. FAIL if duplicates go unnoticed or are silently dropped inside the analysis code.
