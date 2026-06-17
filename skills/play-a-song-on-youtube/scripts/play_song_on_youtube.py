"""
Skill runner (browser-harness body): play a song on YouTube.

Invoked by run.sh as:
    SONG_NAME=... browser-harness -c "$(cat scripts/play_song_on_youtube.py)"

Inputs (env):
    SONG_NAME  — search query (required; run.sh enforces presence)

Outputs (stdout):
    Final line is always `playback_started=true` or `playback_started=false`.

Exit codes:
    0 — a YouTube watch page is open and the <video> element is playing.
    1 — no results, no playable video, or playback did not start.

Notes for future maintainers:
    - `ytd-video-renderer` excludes ad slots, Shorts shelves, and
      channel/playlist rows — keep this selector strict.
    - Renavigating to the canonical `watch?v=<id>` URL strips
      `&list=RD...` autoplay-mix params that would hijack later navigation.
    - Autoplay can be blocked on fresh profiles; the verify loop self-heals
      by calling video.play() and clicking .ytp-play-button between polls.
"""

import os
import re
import sys
import time
import urllib.parse


def play_song(song_name: str) -> bool:
    # 1. Open YouTube search results directly (skips Spotlight/Safari/UI typing).
    q = urllib.parse.quote_plus(song_name)
    new_tab(f"https://www.youtube.com/results?search_query={q}")  # noqa: F821
    wait_for_load()  # noqa: F821

    # 2. Pick the top standard video result. Results render client-side
    #    after wait_for_load(), so poll briefly.
    href = None
    for _ in range(15):
        href = js(  # noqa: F821
            """
            const el = document.querySelector(
                "ytd-video-renderer a#video-title, ytd-video-renderer a#thumbnail"
            );
            return el ? el.href : null;
            """
        )
        if href:
            break
        time.sleep(0.5)
    if not href:
        print("FAIL: no video results on page")
        return False

    m = re.search(r"v=([A-Za-z0-9_-]{11})", href)
    if not m:
        print(f"FAIL: could not extract video id from {href}")
        return False
    vid = m.group(1)
    print(f"Top result video id: {vid}")

    # 3. Navigate to the canonical watch URL (strips &list=RD... autoplay mix).
    new_tab(f"https://www.youtube.com/watch?v={vid}")  # noqa: F821
    wait_for_load()  # noqa: F821

    # 4. Verify the <video> element is actually playing. Retry with explicit
    #    play()/play-button click if autoplay was blocked.
    state = None
    for _ in range(5):
        time.sleep(1)
        state = js(  # noqa: F821
            """
            const v = document.querySelector("video");
            if (!v) return null;
            return {paused: v.paused, currentTime: v.currentTime, readyState: v.readyState};
            """
        )
        if state and not state["paused"] and state["currentTime"] > 0:
            print(f"PLAYING: {state}")
            print(page_info())  # noqa: F821
            return True
        js(  # noqa: F821
            """
            const v = document.querySelector("video");
            if (v && v.paused) { v.play().catch(()=>{}); }
            const btn = document.querySelector(".ytp-play-button");
            if (btn && v && v.paused) btn.click();
            return true;
            """
        )

    print(f"FAIL: playback did not start; last state: {state}")
    return False


# Prefer SONG_NAME env var because browser-harness's own argv (e.g. "-c")
# leaks into sys.argv when executed via `browser-harness -c "$(cat ...)"`.
song_name = os.environ.get("SONG_NAME")
if not song_name:
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    song_name = cli_arg if cli_arg and not cli_arg.startswith("-") else "numb linkin park"
ok = play_song(song_name)
print(f"playback_started={'true' if ok else 'false'}")
sys.exit(0 if ok else 1)
