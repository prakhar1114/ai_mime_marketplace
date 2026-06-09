# Learned Notes

## Step 1: find_top_restaurants (browser_harness)

### Approach
Skip the Spotlight/Chrome/omnibox typing recording entirely. Navigate directly to the
Google Maps search results URL — far more reliable than driving the search box.

### URL pattern
```
https://www.google.com/maps/search/<urlencoded query>
```
e.g. `https://www.google.com/maps/search/italian%20restaurants%20in%20indiranagar`

Use `urllib.parse.quote(query)`.

### Load
- `new_tab(url)` then `wait_for_load()` then `time.sleep(4)` (results feed renders async).

### Extraction (DOM, deterministic — no ask_llm needed)
Result cards live in `div[role=feed]` as `div.Nv2PK`. Primary name is in `.qBF1Pd`
(fallback `a[aria-label]`). Result URL is the card anchor `a.hfpxzc[href]`, falling
back to any card anchor containing `/maps/place/`.

```js
((limit) => {
  const normalize = (s) => (s || "").replace(/\s+/g, " ").trim();
  const out = [];
  const seen = new Set();
  const feed = document.querySelector("div[role=feed]");
  let cards = feed ? Array.from(feed.querySelectorAll("div.Nv2PK"))
                   : Array.from(document.querySelectorAll("div.Nv2PK"));
  for (const c of cards) {
    const nameEl = c.querySelector(".qBF1Pd") || c.querySelector("a[aria-label]");
    const linkEl = c.querySelector("a.hfpxzc[href]") ||
      c.querySelector("a[href*='/maps/place/']") ||
      c.querySelector("a[href]");
    const name = normalize(nameEl ? (nameEl.textContent || nameEl.getAttribute("aria-label")) : "");
    const href = linkEl ? linkEl.href : "";
    if (!name || !href || seen.has(name + href)) continue;
    seen.add(name + href);
    out.push({name, url: href});
    if (out.length >= limit) break;
  }
  return out;
})(limit)
```
Take the first `result_limit` entries. Default `result_limit` is 5. Verified order
matches the visually-displayed left panel.
Example output for "italian restaurants in indiranagar":
1. Bologna Italian Restaurant - Indiranagar
2. Spettacolare
3. Pasta Street - Indiranagar
4. La Gioia - Italian Bar and Restaurant | Pizzeria
5. Chianti, Indiranagar

### Message preparation
Build separate single-line messages (WhatsApp Return/Enter sends, so avoid newlines):
- Intro: `suggested places to eat, do a thumbsup where we should meet`
- One message per place: `<index>. <name> - <url>`

### Outputs
- restaurant_places: list[dict] with `name` and `url`
- restaurant_messages: list[str] where index 0 is the intro and subsequent entries are
  individual place messages

### Gotchas
- Results render async; sleep after wait_for_load.
- Close the Maps search tab after extraction. In browser-harness, the tab opened by
  `new_tab(url)` can be closed with `js("window.close(); true")`.
- Sometimes sponsored/ad cards can appear at top of feed but they are also div.Nv2PK
  and acceptable as "top results" (matches recording behavior). None appeared in test.

## Step 2: send_whatsapp_message (ui_agent)

### Target
Native WhatsApp Mac app, bundle id `net.whatsapp.WhatsApp` (NOT WhatsApp Web — user
not logged into web). Verified end-to-end via cua tools.

### Activation gotcha
`open -b net.whatsapp.WhatsApp` launches it but the window may not come to the
foreground on its own. Reliable activation:
```
open -b net.whatsapp.WhatsApp
osascript -e 'tell application "System Events" to set frontmost of (first process whose bundle identifier is "net.whatsapp.WhatsApp") to true'
```
The standalone UI agent should activate the app first.

### Ordered high-level steps (use as UI agent task prompt)
1. Launch/activate the WhatsApp Mac app and make its window frontmost.
2. Click the chat search field at the top of the left sidebar (placeholder "Search").
3. Type the contact name (the contact_name input).
4. In the results list under the "Chats" heading, click the first/top chat entry that
   matches the contact name (e.g. "Prakhar Jain (You)" for a self-chat).
5. Click the message compose text box at the bottom of the right-hand chat pane
   (left of the emoji/mic icons).
6. Paste the intro message, press Return/Enter to send it.
7. For each prepared place message, paste the message and press Return/Enter. Each
   place must be sent as a separate outgoing message, not one combined list.
8. Verify the final outgoing bubble appears at the bottom and the compose box is clear.

### Notes
- Return/Enter sends the message; the compose box accepts a single-line string fine.
- Verified 2026-06-04: sent the intro plus five separate URL-bearing place messages to
  self-chat "Prakhar Jain (You)" using clipboard paste and Return/Enter.
- Speed update 2026-06-04: per-message screenshot/accessibility verification is much too
  slow for long URL messages. Keep the safety check that the correct chat is open, verify
  the first paste/send clears the compose box, then send the remaining messages in a tight
  clipboard paste + Return/Enter loop. Take one final screenshot after the last message.

## All steps complete end-to-end (verified live).
