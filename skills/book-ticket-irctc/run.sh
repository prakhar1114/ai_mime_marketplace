#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# ai-mime-env: load standalone env when not already provided by AI Mime
if [[ -z "${AI_MIME_PYTHON_PATH:-}" && -f "$HERE/.env" ]]; then
  set -a; . "$HERE/.env"; set +a
fi
INPUTS="${1:-$HERE/inputs/inputs.example.json}"
exec python3 "$HERE/scripts/run.py" --inputs-json "$INPUTS"
