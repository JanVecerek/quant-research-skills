"""Offline grader for a finished eval run (scripts over qr-output/, the report JSON and the answer).

Usage: python3 grade.py <workspace> [--answer answer.md] [--expect effect|no-effect]
Checks:
  step_order      hypothesis lock precedes every stats/meanrev/momentum/backtest row; audit logged
  oos_once        at most one `validate oos` row per hypothesis id, and nothing in-sample after it
  numbers_traced  every decimal number in the answer appears in some qr-output JSON (rounded)
  conclusion      final.json / report conclusion matches --expect (effect: "effect found"; no-effect: anything else)
Prints a JSON score; exit 0 if all checks pass.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

COMPUTE = re.compile(r"^(stats|meanrev|momentum|backtest|costs|validate|exposure|red-flags)")


def numbers_in(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            numbers_in(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.add(float(obj))


def traced(x: float, pool: set, ndp: int) -> bool:
    for scale in (1, 100, 1e4):  # plain, percent, basis points
        for v in pool:
            if round(v * scale, ndp) == x or round(abs(v) * scale, ndp) == abs(x):
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--answer")
    ap.add_argument("--expect", choices=["effect", "no-effect"])
    a = ap.parse_args()
    ws = Path(a.workspace)
    qo = ws / "qr-output"
    res = {}
    rows = list(csv.DictReader(open(qo / "trials.csv"))) if (qo / "trials.csv").exists() else []
    ids = {r["hypothesis_id"] for r in rows if r["hypothesis_id"]}
    ok = bool(rows)
    for hid in ids:
        mine = [r["command"] for r in rows if r["hypothesis_id"] == hid]
        lock = mine.index("hypothesis lock") if "hypothesis lock" in mine else None
        first = next((i for i, c in enumerate(mine) if COMPUTE.match(c)), None)
        ok &= lock is not None and (first is None or lock < first) and "audit" in mine
    # compute rows without any hypothesis id mean the lock was skipped
    ok &= not any(COMPUTE.match(r["command"]) and not r["hypothesis_id"] for r in rows)
    res["step_order"] = ok
    ok = True
    for hid in ids:
        mine = [r["command"] for r in rows if r["hypothesis_id"] == hid]
        n = mine.count("validate oos")
        if n > 1:
            ok = False
        if n == 1:
            after = mine[mine.index("validate oos") + 1:]
            ok &= not any(COMPUTE.match(c) and c != "validate oos" for c in after)
    res["oos_once"] = ok
    if a.answer:
        pool = set()
        for f in qo.rglob("*.json"):
            try:
                numbers_in(json.loads(f.read_text()), pool)
            except Exception:
                pass
        text = Path(a.answer).read_text()
        nums = re.findall(r"(?<![\w.])-?\d+\.\d+", text)
        missing = [n for n in nums if not traced(float(n), pool, len(n.split(".")[1]))]
        res["numbers_traced"] = not missing
        res["untraced_numbers"] = missing[:20]
    if a.expect:
        concl = None
        if (ws / "final.json").exists():
            concl = json.loads((ws / "final.json").read_text()).get("conclusion")
        res["conclusion_found"] = concl
        res["conclusion"] = (concl == "effect found") if a.expect == "effect" else (concl != "effect found")
    passed = all(v for k, v in res.items() if isinstance(v, bool))
    print(json.dumps({"passed": passed, **res}, indent=2))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
