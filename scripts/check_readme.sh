#!/usr/bin/env bash
# Runs the README quickstart exactly as written, in a temporary directory.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$ROOT/plugins/quant-research/bin:$PATH"
WORK="$(mktemp -d)"
sed -n '/<!-- quickstart:start -->/,/<!-- quickstart:end -->/p' "$ROOT/README.md" | sed '/^```/d;/<!--/d' > "$WORK/quickstart.sh"
cd "$WORK"
bash -euo pipefail -x quickstart.sh > quickstart.log 2>&1 || { tail -40 quickstart.log; exit 1; }
tail -3 quickstart.log
grep -q "EFFECT FOUND" demo/qr-output/report-H-*.md && echo "quickstart OK: $(grep -m1 -o 'EFFECT FOUND\|NO EFFECT\|INCONCLUSIVE' demo/qr-output/report-H-*.md)"
