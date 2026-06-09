---
name: play-a-song-on-youtube
description: Play a requested song on YouTube via a browser tab and verify the watch-page <video> element is actually playing.
platform: macos
entrypoint: run.sh
inputs_template: inputs/inputs.template.json
inputs_example: inputs/inputs.example.json
---

# Play a song on YouTube (browser-harness)

Opens YouTube search results directly via `youtube.com/results?search_query=...`,
picks the top standard video result (skipping ads / Shorts / channel rows),
navigates to its canonical watch URL, and verifies the `<video>` element is
actively playing. Driven through `browser-harness` — no Spotlight, no Safari
address-bar typing, no UI clicks on YouTube itself.

## Inputs

JSON object passed via `--inputs-json /path/to/inputs.json`.

| Field        | Type   | Required | Description                                                |
|--------------|--------|----------|------------------------------------------------------------|
| `song_name`  | string | yes      | Search query entered into YouTube (song / video name).     |

- Template: [`inputs/inputs.template.json`](inputs/inputs.template.json)
- Example:  [`inputs/inputs.example.json`](inputs/inputs.example.json)

```json
{ "song_name": "numb linkin park" }
```

## Run

```bash
# default — uses inputs/inputs.example.json
./run.sh

# explicit inputs file
./run.sh /absolute/path/to/inputs.json
```

`run.sh` lives at the skill root and is a thin wrapper that reads `song_name`
from the inputs JSON, exports it as `SONG_NAME`, and invokes:

```bash
browser-harness -c "$(cat scripts/play_song_on_youtube.py)"
```

Behavior:

1. Opens a new browser tab at `https://www.youtube.com/results?search_query=<URL-encoded song_name>`
   and waits for the page to load. Skips Safari/Spotlight launch — the
   harness already has a controlled Chrome instance.
2. Polls the DOM (up to ~7.5s) for the first `ytd-video-renderer` link —
   this CSS selector intentionally excludes ad slots, Shorts shelves, and
   channel/playlist rows so the top *standard* video is selected.
3. Extracts the 11-char video id from the `?v=...` query param and
   navigates to the canonical `https://www.youtube.com/watch?v=<id>` URL.
   Using the canonical URL strips any `&list=RD...` autoplay-mix params
   that would otherwise hijack subsequent navigation.
4. Polls `document.querySelector("video")` for up to ~5s and confirms
   playback: `!paused && currentTime > 0 && readyState == 4`. If autoplay
   was blocked, calls `video.play()` and clicks `.ytp-play-button` once
   between polls before giving up.

## Outputs

Final state is printed to stdout by the script:

```
Top result video id: kXYiU_JCYtU
PLAYING: {'paused': False, 'currentTime': 5.6, 'readyState': 4}
{'url': 'https://www.youtube.com/watch?v=kXYiU_JCYtU', 'title': '... – Linkin Park - YouTube', ...}
playback_started=true
```

The final line is always `playback_started=true` or `playback_started=false`.

## Exit codes

| Code | Meaning                                                                |
|------|------------------------------------------------------------------------|
| `0`  | A YouTube watch page is open and the `<video>` element is playing.     |
| `1`  | No results found, no playable video, or playback did not start.        |

## Fallback

The optimized plan declares `fallback: ui_agent` for this step. If
`./run.sh` exits non-zero, hand off to the UI agent (or a human) rather
than retrying — repeating the same harness call will not change the
outcome. Likely causes: YouTube is showing a consent / sign-in interstitial,
the browser-harness Chrome isn't running, or the network is blocking
the site.

Step-by-step recovery instructions for driving YouTube's UI manually are
in [`references/fallback_plan.md`](references/fallback_plan.md).

## ask_llm decision points

None. Result selection is deterministic (first `ytd-video-renderer`), and
playback verification reads the live `<video>` element state — no
stochastic judgment required.

## Recovery notes

- **Top-result selector matters.** `ytd-video-renderer a#video-title` is
  the right selector. Don't relax it to `a#video-title` alone — that also
  matches Shorts and channel-upload rows, which either don't have a `?v=`
  param or jump into the Shorts player (which doesn't expose a standard
  `<video>` element the verification step can read).
- **Strip `&list=RD...`.** YouTube's "Mix - <song>" autoplay queue gets
  attached to the first result's href. Navigating to that URL works, but
  any later programmatic navigation gets pulled back into the mix.
  Re-navigating to the canonical `watch?v=<id>` avoids this entirely.
- **Autoplay can be blocked.** A fresh Chrome profile without prior user
  interaction sometimes refuses to autoplay with sound. The verification
  loop self-heals by calling `video.play()` and clicking the play button
  between polls.

## References

- [`references/schema.json`](references/schema.json) — byte-identical copy of workflow schema.
- [`references/optimized_plan.json`](references/optimized_plan.json) — byte-identical copy of optimized plan.
- [`references/learned_notes.md`](references/learned_notes.md) — notes captured during synthesis (selectors, traps, the canonical-URL trick).
- [`references/fallback_plan.md`](references/fallback_plan.md) — manual / UI-agent recovery path if `run.sh` fails.
