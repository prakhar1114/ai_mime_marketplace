---
name: play_a_song_on_spotify
description: Play a requested song on the Spotify desktop app on macOS. Use this whenever the user wants to play, put on, or start a specific track/song by name on Spotify. Resolves the best matching track from Spotify's catalog and starts playback using the existing logged-in Spotify session.
---

# Play a song on Spotify

Resolve the best-matching Spotify track for a song query, then start playback in the
Spotify desktop app via the `spotify:track:<id>` URL scheme. Uses the user's existing
logged-in Spotify session — no OAuth or Web API credentials required.

## Inputs
- `song_name` (string, required) — The song title or search query to play. May include
  artist or movie context for disambiguation, e.g. `"Sajda, My name is Khan"`.

## Run
```bash
./run.sh inputs/inputs.example.json
# or
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

Runtime/interpreter contract:
- `run.sh` selects the first available interpreter in this order: skill `.venv/bin/python`,
  workflow `.venv/bin/python`, then the required `$AI_MIME_PYTHON_PATH`.
- This skill needs no third-party Python packages, so there is **no** `requirements.txt`
  and no `.venv` to build. It relies only on:
  - macOS system tools (`osascript`, `open`),
  - the browser harness at `$AI_MIME_BROWSER_HARNESS_BIN` (to search Spotify's catalog),
  - the runtime-provided `llm_resolver` module (for `ask_llm`).
- Runtime does not create or repair `.venv`. (If a future change adds dependencies, build
  with `"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"` then
  `"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python` — for
  build/manual repair only.)

How it works:
1. Search `https://open.spotify.com/search/<query>/tracks` via the browser harness and
   extract relevance-ordered track candidates (id, title, artists, album).
2. Choose the best match (`ask_llm`, falling back to the top result).
3. Play with `osascript -e 'tell application "Spotify" to play track "spotify:track:<id>"'`
   (falls back to `open spotify:track:<id>`).
4. Verify via AppleScript that `player state` is `playing` and report the track.

## Outputs
- `playing_track` — object with `title`, `artist`, `uri`, and `state` (`"playing"`) of the
  track that started playing. Emitted in the final `workflow_done` event.

## Progress log format
Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"resolve_and_play_spotify_track","title":"Resolve And Play Track"}`
- `{"event":"step_done","id":"resolve_and_play_spotify_track","outputs":{"playing_track":{...}},"summary":"…"}`
- `{"event":"step_failed","id":"…","error":"…","recoverable":false}` (exits non-zero)
- `{"event":"workflow_done","outputs":{"playing_track":{...}}}`

## Fallback
If the deterministic path fails (search returns no results, or Spotify never reports active
playback), the task can be completed manually in the Spotify desktop app. See
`references/fallback_plan.md` for the recorded step-by-step UI recipe.

## ask_llm decision points
- **Best-match track selection** (`scripts/run.py`, `pick_best`): given the relevance-ordered
  candidate list (title/artists/album), `ask_llm` returns the chosen track `id` with a schema
  of `{id: string|null, reason: string}`. It prefers the original/soundtrack studio version
  matching the query and avoids instrumental/lofi/remix/cover/unrelated tracks. If `ask_llm`
  errors or returns an unknown id, the code deterministically falls back to the top result
  (index 0). A single candidate skips the LLM entirely.

## References
- `references/fallback_plan.md` — manual UI recipe + learned selectors/URLs/AppleScript.
