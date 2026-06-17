import argparse
import json
import os
import re
import subprocess
import sys
import time

from llm_resolver import ask_llm


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


# ---- Browser harness script: search open.spotify.com and return track candidates ----
HARNESS_SCRIPT = r"""
import urllib.parse, json
q = %s
url = "https://open.spotify.com/search/" + urllib.parse.quote(q) + "/tracks"
tid = new_tab(url)
wait_for_load()
# Return as soon as the track rows actually render instead of a fixed sleep.
# open.spotify.com is an SPA, so the document is "complete" before results paint.
if not wait_for_element('[data-testid="tracklist-row"]', timeout=10):
    wait(1)
rows = js(r'''
(() => {
  const rows = document.querySelectorAll("[data-testid=\"tracklist-row\"]");
  const out = [];
  for (const r of rows) {
    const link = r.querySelector("a[href*=\"/track/\"]");
    const m = link && link.href.match(/track\/([A-Za-z0-9]{22})/);
    if (!m) continue;
    const anchors = Array.from(r.querySelectorAll("a")).map(a => a.textContent.trim()).filter(Boolean);
    out.push({id: m[1], title: anchors[0] || "", artists: anchors.slice(1, -1), album: anchors[anchors.length - 1] || ""});
    if (out.length >= 10) break;
  }
  return JSON.stringify(out);
})()
''')
# Close the Spotify search tab now that the candidates are extracted; playback
# happens through the native Spotify app, so the browser tab is no longer needed.
try:
    cdp("Target.closeTarget", targetId=tid)
except Exception:
    pass
print("<<<CANDIDATES>>>" + rows + "<<<END>>>")
"""


def resolve_track_candidates(song_name):
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN not configured")
    code = HARNESS_SCRIPT % json.dumps(song_name)
    proc = subprocess.run([harness_bin, "-c", code], capture_output=True, text=True)
    out = proc.stdout + "\n" + proc.stderr
    m = re.search(r"<<<CANDIDATES>>>(.*?)<<<END>>>", out, re.DOTALL)
    if not m:
        raise RuntimeError("Could not extract search results from Spotify. Output: " + out[-500:])
    return json.loads(m.group(1))


# Variant keywords that usually indicate a non-original rendition. Penalized
# unless the user's query explicitly asks for them.
VARIANT_KEYWORDS = (
    "instrumental", "karaoke", "lofi", "lo fi", "sped up", "sped-up", "slowed",
    "reverb", "remix", "cover", "tribute", "live", "acoustic", "8d", "nightcore",
    "made famous", "originally performed", "in the style of",
)


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def rank_candidates(song_name, candidates):
    """Deterministic relevance ranking that guards against obviously-wrong picks.

    Combines Spotify's own ordering (index 0 is its top hit) with an exact
    normalized-title match bonus, query-token coverage, and penalties for
    instrumental/remix/cover-style variants the user did not ask for.
    """
    qn = _norm(song_name)
    q_tokens = [t for t in qn.split() if len(t) > 1]
    ranked = []
    for idx, c in enumerate(candidates):
        title = _norm(c.get("title", ""))
        artists = _norm(" ".join(c.get("artists", []) or []))
        combined = (title + " " + artists).strip()
        score = -idx * 5  # preserve Spotify relevance order as the tie-breaker
        if title and title == qn:
            score += 1000
        if qn and qn in combined:
            score += 300
        score += 30 * sum(1 for t in q_tokens if t in combined)
        for kw in VARIANT_KEYWORDS:
            if kw in title and kw not in qn:
                score -= 200
        ranked.append((score, idx, c))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in ranked]


def pick_best(song_name, candidates):
    if len(candidates) == 1:
        return candidates[0]

    ranked = rank_candidates(song_name, candidates)
    top = ranked[0]
    # Confident deterministic match: exact normalized title and a clear lead over
    # the runner-up. Skip the LLM to avoid it second-guessing an obvious answer.
    if _norm(top.get("title", "")) == _norm(song_name):
        return top

    shortlist = ranked[:5]
    prompt = (
        "Pick the Spotify track that best matches the user's request.\n"
        f"User request: {song_name!r}\n\n"
        "Candidates (already pre-ranked best-first):\n"
        + json.dumps(shortlist, ensure_ascii=False, indent=2)
        + "\n\nPrefer the original/soundtrack studio version that matches the requested song "
        "and any movie/artist context in the request. Avoid instrumental, karaoke, lofi, remix, "
        "cover, live, sped-up, or unrelated songs unless the request explicitly asks for them. "
        "If unsure, choose the first candidate. Return the chosen track id."
    )
    schema = {
        "type": "object",
        "properties": {"id": {"type": ["string", "null"]}, "reason": {"type": "string"}},
        "required": ["id", "reason"],
    }
    try:
        pick = ask_llm(prompt, schema=schema)
        chosen = pick.get("id")
        for c in shortlist:
            if c["id"] == chosen:
                return c
    except Exception as e:
        log_event("step_start", id="llm_fallback", title=f"LLM pick failed ({e}); using top ranked result")
    return top


def osascript(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description="Play a song on Spotify")
    parser.add_argument("--inputs-json", required=True)
    args = parser.parse_args()

    with open(args.inputs_json, "r", encoding="utf-8") as f:
        inputs = json.load(f)

    song_name = inputs.get("song_name")
    if not song_name:
        print("Missing required input: song_name", file=sys.stderr)
        sys.exit(1)

    step_id = "resolve_and_play_spotify_track"
    log_event("step_start", id=step_id, title="Resolve And Play Track")

    # 1. Resolve candidates via the browser.
    try:
        candidates = resolve_track_candidates(song_name)
    except Exception as e:
        log_event("step_failed", id=step_id, error=str(e), recoverable=False)
        sys.exit(1)

    if not candidates:
        log_event("step_failed", id=step_id, error=f"No Spotify tracks found for {song_name!r}", recoverable=False)
        sys.exit(1)

    # 2. Choose the best match.
    track = pick_best(song_name, candidates)
    uri = f"spotify:track:{track['id']}"

    # 3. Play via Spotify URL scheme + AppleScript (uses existing logged-in session).
    play = osascript(f'tell application "Spotify" to play track "{uri}"')
    if play.returncode != 0:
        # Fallback to URL scheme open.
        subprocess.run(["open", uri], capture_output=True, text=True)

    # 4. Verify playback. Poll quickly so we report success as soon as Spotify
    # flips to "playing" instead of waiting out fixed one-second intervals.
    playing_track = None
    deadline = time.time() + 8
    while time.time() < deadline:
        v = osascript(
            'tell application "Spotify" to return (name of current track) & "\t" & '
            '(artist of current track) & "\t" & (player state as text)'
        )
        if v.returncode == 0:
            parts = v.stdout.strip().split("\t")
            if len(parts) == 3 and parts[2] == "playing":
                playing_track = {"title": parts[0], "artist": parts[1], "uri": uri, "state": parts[2]}
                break
        time.sleep(0.4)

    if not playing_track:
        log_event("step_failed", id=step_id, error="Spotify did not report active playback of the resolved track", recoverable=False)
        sys.exit(1)

    log_event(
        "step_done",
        id=step_id,
        outputs={"playing_track": playing_track},
        summary=f"Playing '{playing_track['title']}' by {playing_track['artist']}",
    )
    log_event("workflow_done", outputs={"playing_track": playing_track})

    # Force a clean exit. The llm_resolver Claude fallback registers an asyncio
    # generator that can raise during interpreter shutdown and intermittently set a
    # non-zero exit code even though the workflow fully succeeded. Flush our streams
    # and exit immediately, bypassing those atexit handlers.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
