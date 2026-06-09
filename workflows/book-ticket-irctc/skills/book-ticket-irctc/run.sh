#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
INPUTS="${1:-$HERE/inputs/inputs.example.json}"
exec python3 "$HERE/scripts/run.py" --inputs-json "$INPUTS"
