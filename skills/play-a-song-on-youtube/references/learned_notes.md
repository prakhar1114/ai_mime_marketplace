# Learned notes — play a song on YouTube (browser-harness)

## Smart native shortcut
- YouTube exposes a fully URL-driven search endpoint:
  `https://www.youtube.com/results?search_query=<URL-encoded query>`.
  Navigating directly to this URL replaces the entire recorded
  Spotlight → Safari → address-bar → site-search → click sequence with a
  single `new_tab(...)` call from inside `browser-harness`.
- The top playable video can be lifted out of the DOM and replayed via the
  canonical watch URL — no clicks required:
  ```js
  document.querySelector(
    "ytd-video-renderer a#video-title, ytd-video-renderer a#thumbnail"
  ).href
  // → https://www.youtube.com/watch?v=<id>&pp=...
  ```

## Traps that cost time
- **Wrong selector picks the wrong thing.** `a#video-title` without the
  `ytd-video-renderer` ancestor also matches Shorts shelves and
  channel/upload rows. Shorts URLs don't have a `?v=` param and the Shorts
  player doesn't expose a standard `<video>` element the verification step
  can read. Always anchor on `ytd-video-renderer`.
- **`&list=RD<id>` hijacks navigation.** YouTube attaches an autoplay-mix
  parameter to the first result's href. Navigating to it works the first
  time but any later programmatic navigation gets pulled back into the
  mix. Renavigate to the canonical `https://www.youtube.com/watch?v=<id>`
  (no `list` param) once the id has been extracted.
- **Autoplay can be blocked** on fresh Chrome profiles without prior user
  interaction. The verification loop self-heals by calling `video.play()`
  and clicking `.ytp-play-button` between polls — don't simplify it to a
  single state read.
- **browser-harness `-c` leaks into argv.** When executed via
  `browser-harness -c "$(cat ...)"`, the harness's own flags end up in
  `sys.argv`. Prefer `SONG_NAME` env var for inputs and only fall back to
  argv if the value doesn't start with `-`.

## Verification path
Poll the live `<video>` element directly:
```js
const v = document.querySelector("video");
return v ? {paused: v.paused, currentTime: v.currentTime, readyState: v.readyState} : null;
```
Treat as playing when `!paused && currentTime > 0 && readyState === 4`.
Five 1-second polls is enough on a warm profile; cold profiles benefit
from the autoplay-nudge between polls.

## Verified end states
- `song_name="numb linkin park"` →
  `video id=kXYiU_JCYtU`,
  `title="Numb (Official Music Video) [4K UPGRADE] – Linkin Park"`,
  `paused=False`, `currentTime≈5.6`, `readyState=4`.

## Fallback
If the verification poll does not see `!paused && currentTime > 0` within
~5s, exit non-zero. The plan declares `fallback: ui_agent` for this step,
so the caller will hand off to the UI agent.
