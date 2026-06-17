#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request


STEP_ID = "resolve_and_play_spotify_track"
STEP_TITLE = "Resolve And Play Track"


KNOWN_TRACK_URIS = {
    "fate of ophelia": "spotify:track:53iuhJlwXhSER5J2IYYv1W",
    "the fate of ophelia": "spotify:track:53iuhJlwXhSER5J2IYYv1W",
}


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


def fail(message, recoverable=False):
    log_event("step_failed", id=STEP_ID, error=message, recoverable=recoverable)
    sys.exit(1)


def normalize_text(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def normalize_spotify_track_uri(value):
    value = (value or "").strip()
    match = re.search(r"spotify:track:([A-Za-z0-9]{22})", value)
    if match:
        return f"spotify:track:{match.group(1)}"
    match = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]{22})", value)
    if match:
        return f"spotify:track:{match.group(1)}"
    if re.fullmatch(r"[A-Za-z0-9]{22}", value):
        return f"spotify:track:{value}"
    return None


def run_osascript(lines, check=True):
    cmd = ["osascript"]
    for line in lines:
        cmd.extend(["-e", line])
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)


def play_track_uri(uri):
    run_osascript([f'tell application "Spotify" to play track "{uri}"'])


def read_current_track():
    proc = run_osascript(
        [
            'tell application "Spotify"',
            "set t to current track",
            'return (player state as string) & tab & (name of t) & tab & (artist of t) & tab & (spotify url of t)',
            "end tell",
        ],
        check=False,
    )
    if proc.returncode != 0:
        return None
    parts = proc.stdout.rstrip("\n").split("\t")
    if len(parts) < 4:
        return None
    return {
        "state": parts[0],
        "name": parts[1],
        "artist": parts[2],
        "uri": parts[3],
    }


def wait_for_playback(expected_query, expected_uri=None, timeout=12):
    query_norm = normalize_text(expected_query)
    query_tokens = [token for token in query_norm.split() if len(token) > 1]
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = read_current_track()
        if last and last.get("state") == "playing":
            combined = normalize_text(f"{last.get('name', '')} {last.get('artist', '')}")
            uri_match = expected_uri and last.get("uri") == expected_uri
            token_match = query_tokens and all(token in combined for token in query_tokens[: min(4, len(query_tokens))])
            if uri_match or token_match:
                return last
        time.sleep(1)
    if last and last.get("state") == "playing":
        combined = normalize_text(f"{last.get('name', '')} {last.get('artist', '')}")
        if any(token in combined for token in query_tokens):
            return last
    return last


def http_json(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_spotify_access_token():
    token = os.environ.get("SPOTIFY_ACCESS_TOKEN")
    if token:
        return token

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    payload = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii")
    data = http_json(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    return data.get("access_token")


def score_track(query, item):
    query_norm = normalize_text(query)
    name_norm = normalize_text(item.get("name", ""))
    artists_norm = normalize_text(" ".join(artist.get("name", "") for artist in item.get("artists", [])))
    combined = f"{name_norm} {artists_norm}".strip()
    query_tokens = [token for token in query_norm.split() if len(token) > 1]
    score = int(item.get("popularity") or 0)
    if name_norm == query_norm:
        score += 1000
    if query_norm and query_norm in combined:
        score += 500
    score += 40 * sum(1 for token in query_tokens if token in combined)
    return score


def resolve_via_spotify_api(song_name):
    token = get_spotify_access_token()
    if not token:
        return None
    params = urllib.parse.urlencode({"q": song_name, "type": "track", "limit": "10", "market": os.environ.get("SPOTIFY_MARKET", "US")})
    data = http_json(
        f"https://api.spotify.com/v1/search?{params}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    items = data.get("tracks", {}).get("items", [])
    if not items:
        return None
    best = max(items, key=lambda item: score_track(song_name, item))
    return best.get("uri")


def run_ui_agent_fallback(song_name):
    ui_agent_cmd = os.environ.get("AI_MIME_UI_AGENT_CMD")
    if not ui_agent_cmd:
        fail(
            "Could not resolve a Spotify track URI without Spotify API credentials, and AI_MIME_UI_AGENT_CMD is not configured.",
            recoverable=True,
        )

    search_uri = "spotify:search:" + urllib.parse.quote(song_name)
    subprocess.run(["open", search_uri], check=False)
    task_prompt = (
        "Target and constraints: Use the native Spotify desktop app on macOS, not a browser. "
        f"Goal: play the best matching song result for the query {song_name!r}. "
        f"Known setup: the app may already be on a Spotify search results page for {song_name!r}; if not, open or navigate to that search. "
        "Optimized action sequence: inspect the Spotify results, prefer a result whose title strongly matches the requested song, prefer song results over albums/playlists/videos when both are visible, then click that result's Play button. "
        "Skip if already true: if Spotify is already playing the requested title, report success. "
        "Gotchas: pressing Return after opening a spotify:search link may not start playback; do not rely on keyboard focus alone. "
        "Recovery: if Spotify is not foreground, activate it; if the search page is wrong, use the top search field to search the requested query. "
        "Verification: before finishing, confirm Spotify visibly shows playback active for the selected matching result."
    )
    schema = {
        "type": "object",
        "properties": {
            "played": {"type": "boolean"},
            "track_name": {"type": "string"},
            "artist": {"type": "string"},
        },
        "required": ["played", "track_name", "artist"],
    }
    cmd = shlex.split(ui_agent_cmd) + [task_prompt, "--schema", json.dumps(schema), "--json"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if proc.returncode != 0:
        fail(f"UI Agent fallback failed to run: {proc.stderr.strip() or proc.stdout.strip()}", recoverable=True)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("UI Agent fallback returned invalid JSON.", recoverable=True)
    if result.get("status") != "success":
        fail(result.get("error") or result.get("summary") or "UI Agent fallback did not complete.", recoverable=True)
    return result.get("result_json") or {}


def resolve_track_uri(song_name):
    direct_uri = normalize_spotify_track_uri(song_name)
    if direct_uri:
        return direct_uri, "direct_input"
    cached_uri = KNOWN_TRACK_URIS.get(normalize_text(song_name))
    if cached_uri:
        return cached_uri, "exploration_cache"
    api_uri = resolve_via_spotify_api(song_name)
    if api_uri:
        return api_uri, "spotify_api"
    return None, "ui_agent_fallback"


def main():
    parser = argparse.ArgumentParser(description="Play a requested song in Spotify.")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file.")
    args = parser.parse_args()

    try:
        with open(args.inputs_json, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    except Exception as exc:
        fail(f"Could not read inputs JSON: {exc}", recoverable=False)

    song_name = (inputs.get("song_name") or "").strip()
    if not song_name:
        fail("Missing required input: song_name", recoverable=False)

    log_event("step_start", id=STEP_ID, title=STEP_TITLE)

    try:
        uri, source = resolve_track_uri(song_name)
        if uri:
            play_track_uri(uri)
            playing_track = wait_for_playback(song_name, expected_uri=uri)
        else:
            run_ui_agent_fallback(song_name)
            playing_track = wait_for_playback(song_name)
            source = "ui_agent_fallback"
    except Exception as exc:
        fail(f"Spotify playback failed: {exc}", recoverable=True)

    if not playing_track or playing_track.get("state") != "playing":
        fail("Spotify did not report active playback after attempting to play the requested song.", recoverable=True)

    output = {
        "playing_track": {
            "name": playing_track.get("name"),
            "artist": playing_track.get("artist"),
            "uri": playing_track.get("uri"),
            "state": playing_track.get("state"),
            "resolution_source": source,
        }
    }
    log_event("step_done", id=STEP_ID, outputs=output, summary=f"Spotify is playing {playing_track.get('name')} by {playing_track.get('artist')}.")
    log_event("workflow_done", outputs=output)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
