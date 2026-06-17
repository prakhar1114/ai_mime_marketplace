# Fallback plan — play a song on YouTube

If `run.sh` exits non-zero, the browser-harness path is not going to
recover on retry. A human or the `macos-computer-use` / `ui_agent` agent
should complete the workflow by driving Safari + YouTube directly using
the steps below.

Synthesized from `schema.plan.subtasks[]` and `optimized_plan.steps[]`,
trimmed to the user-visible workflow (the recorded
Spotlight → Safari → address-bar → site-search path).

Goal: **a YouTube watch page for `{song_name}` is open and playing.**

---

## Subtask 0 — Launch Safari via Spotlight

**Intent:** Get a Safari window open with a focused address/search bar.

- Press **Cmd-Space** to open Spotlight.
- Type `safari` and press **Return** (or click the "Safari" result).
- Safari opens to the start page; the address bar is focused.

**Notes / traps:**
- If Safari is already running but hidden, Spotlight will activate the
  existing window — that's fine, just click the address bar to focus it.
- Dismiss any stray red dashed selection rectangle on the desktop by
  clicking it once before opening Spotlight.

---

## Subtask 1 — Navigate to YouTube

**Intent:** Load `youtube.com` in the active tab.

- With the address bar focused, type `youtub`.
- Safari shows an autocomplete dropdown; the first item is usually
  "YouTube — youtube.com". Click it (or press **Return** if the address
  bar already shows the full `https://www.youtube.com/` URL).
- The YouTube homepage loads — header with search box, "Try searching to
  get started" prompt in the main area.

**Notes / traps:**
- If a consent / cookie banner appears, accept or dismiss it before
  continuing — it can intercept clicks on the search field.

---

## Subtask 2 — Search and play the top result

**Intent:** Find `{song_name}` and start the top result.

- Click the search input at the top center of the YouTube header
  (placeholder text: **"Search"**, with a magnifying-glass button to its
  right).
- Type `{song_name}` into the focused field.
- Click the magnifying-glass button (or press **Return**) to submit.
  The page updates to a list of results with thumbnails on the left and
  titles on the right.
- Click the **title or thumbnail of the first result** (skip the "Ad"
  row at the very top if one is present — it has an explicit "Ad" badge).
- The watch page loads, the video player appears, and audio starts
  within a couple of seconds.

**Notes / traps:**
- A Shorts shelf may appear above the regular results. Skip it — click a
  result with a standard horizontal thumbnail, not a vertical Shorts tile.
- If the video is paused on load (autoplay blocked), click the large
  central play button in the player or press **K** to toggle playback.
- The browser may display a "Click to allow audio" overlay; click anywhere
  on the player to unblock audio.

---

## Verification (must hold true to call the workflow done)

- A `https://www.youtube.com/watch?v=...` URL is in the address bar.
- The video title reasonably matches `{song_name}` (substring or
  token-overlap is fine — official MVs often append "(Official Music
  Video)", "[4K UPGRADE]", etc.).
- The player's progress indicator is advancing and audio is audible.
