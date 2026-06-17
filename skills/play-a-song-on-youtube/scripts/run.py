#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Play a requested song on YouTube")
    parser.add_argument("--inputs-json", default=str(skill_dir / "inputs" / "inputs.example.json"))
    args = parser.parse_args()

    with open(args.inputs_json, "r", encoding="utf-8") as f:
        inputs = json.load(f)
    song_name = str(inputs.get("song_name") or "").strip()
    if not song_name:
        print("Missing required input: song_name", file=sys.stderr)
        return 2

    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN") or "browser-harness"
    script = (skill_dir / "scripts" / "play_song_on_youtube.py").read_text(encoding="utf-8")
    env = os.environ.copy()
    env["SONG_NAME"] = song_name
    return subprocess.call([harness, "-c", script], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
