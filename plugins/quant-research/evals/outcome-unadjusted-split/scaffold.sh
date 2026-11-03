#!/bin/bash
# Creates this case's seeded data in the empty workspace (run with --scaffold).
set -euo pipefail
CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$(cd "$CASE_DIR/../.." && pwd)"
uv run --quiet --frozen --project "$PLUGIN/qrkit" python "$PLUGIN/evals/fixtures/make_fixture.py" unadjusted-split
