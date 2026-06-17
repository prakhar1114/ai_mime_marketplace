#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# ai-mime-env: load standalone env when not already provided by AI Mime
if [[ -z "${AI_MIME_PYTHON_PATH:-}" && -f "$HERE/.env" ]]; then
  set -a; . "$HERE/.env"; set +a
fi
INPUTS="${1:-$HERE/inputs/inputs.example.json}"

VENV="$HERE/.venv"
PY="$VENV/bin/python"
REQS="$HERE/requirements.txt"

# Bootstrap the script's own virtual env (only non-stdlib dep is pdfplumber).
# browser-harness is a separate CLI on $PATH and manages its own environment.
if [ ! -x "$PY" ]; then
  echo "[run.sh] creating virtual env at $VENV" >&2
  python3 -m venv "$VENV"
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r "$REQS" --quiet
elif ! "$PY" -c "import pdfplumber" >/dev/null 2>&1; then
  echo "[run.sh] installing missing deps into $VENV" >&2
  "$PY" -m pip install -r "$REQS" --quiet
fi

exec "$PY" "$HERE/scripts/run.py" --inputs-json "$INPUTS"
