#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
INPUTS="${1:-$HERE/inputs/inputs.example.json}"

if [[ ! -f "$INPUTS" ]]; then
  echo "inputs file not found: $INPUTS" >&2
  exit 2
fi

# Extract song_name from JSON inputs without requiring jq.
SONG_NAME="$(python3 -c '
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
v = data.get("song_name")
if not v or not str(v).strip():
    sys.exit("Missing required input: song_name")
print(str(v).strip())
' "$INPUTS")"

export SONG_NAME

exec browser-harness -c "$(cat "$HERE/scripts/play_song_on_youtube.py")"
