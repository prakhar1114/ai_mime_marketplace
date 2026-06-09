# Fallback Plan — Play a song on Spotify

If `run.sh` fails, complete the task manually in the Spotify desktop app. The skill's
deterministic path (browser catalog search → URL scheme playback → AppleScript verify) is
strongly preferred; this is the human/UI-agent recovery recipe.

## Subtask 0 — Launch Spotify
Intent: Ensure the Spotify desktop app is open and ready.
- Open Spotify (`open -a Spotify`, or via the app launcher / Dock).
- Wait until the main window with the top search bar and bottom playback bar is visible.
Notes:
- Spotify.app is at `/Applications/Spotify.app`. It uses the user's existing logged-in session.

## Subtask 1 — Search for {song_name}, select top match, and play
Intent: The requested song {song_name} is playing in Spotify.
- Click the top-center search field ("What do you want to play?").
- Clear any existing text (X button inside the search bar), then type the song query.
- Select the top search suggestion / first result row.
- Click the green Play button on the first (top) result row.
- Confirm playback started (bottom playback bar shows the track and a pause button).

Notes (learned in exploration, verified 2026-06-04):
- **Preferred deterministic path** — skip the UI entirely:
  - Resolve track id via the browser harness:
    URL `https://open.spotify.com/search/<urlencoded query>/tracks`; after
    `new_tab` + `wait_for_load` + `wait(3)`, read rows from
    `[data-testid="tracklist-row"]`; track id = `a[href*="/track/"]` →
    regex `track/([A-Za-z0-9]{22})`. Per-row anchors = [title, artists…, album].
    Results are relevance-ordered (row 0 = top result).
  - Play: `osascript -e 'tell application "Spotify" to play track "spotify:track:<id>"'`
    (auto-launches Spotify), or `open "spotify:track:<id>"`.
  - Verify: `osascript -e 'tell application "Spotify" to return (name of current track) & "\t" & (artist of current track) & "\t" & (player state as text)'`
    → expect `player state == "playing"`; match on track NAME (AppleScript `artist`
    returns the primary/album artist, e.g. "Shankar-Ehsaan-Loy", not always the vocalist).
- Spotify search results are client-side rendered — static `http_get` returns no results,
  so the browser harness (or the live UI) is required for search.
- Example: query "Sajda My Name Is Khan" → canonical top track id
  `395gJWcJQK0C3GJfHAn7f6` ("Sajdaa", My Name Is Khan OST). Avoid instrumental / lofi /
  remix / "Sajda Ve" (a different song).
