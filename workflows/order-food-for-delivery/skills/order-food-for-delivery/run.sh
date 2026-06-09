#!/usr/bin/env bash
# One-shot entrypoint for the order-food-for-delivery skill.
#
#   ./run.sh [inputs.json]
#
# Defaults to inputs/inputs.example.json when no path is given.
# Prints one JSON result line to stdout; progress logs go to stderr.
# Exit codes: 0 success | 2 logical failure | 3 not-logged-in
#             4 invalid input | 5 harness error
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
INPUTS="${1:-$HERE/inputs/inputs.example.json}"
exec python3 "$HERE/scripts/run.py" --inputs-json "$INPUTS"
