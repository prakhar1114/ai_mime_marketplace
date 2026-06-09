# Fallback Plan

If `run.sh` fails, a human or UI agent can finish the task from this file alone.

## Subtask 1 - Search Google Maps and Extract Restaurants

**Intent:** Get the first `result_limit` unique restaurant names and Google Maps URLs for
`search_query` from the Maps left results panel. Default `result_limit` is 5.

- Open Google Chrome.
- Navigate directly to `https://www.google.com/maps/search/<urlencoded search_query>`.
- Wait a few seconds for the left results feed to render.
- Read the left results panel from top to bottom.
- For each result card, capture the primary place name and its Maps URL.
- Skip repeated names if the same restaurant appears more than once.
- Stop once `result_limit` unique places have been captured.
- Close the Google Maps search tab after extraction.

**Selectors:**
- Results feed: `div[role=feed]`
- Result card: `div.Nv2PK`
- Primary name: `.qBF1Pd`, fallback `a[aria-label]`
- Place URL: `a.hfpxzc[href]`, fallback `a[href*="/maps/place/"]`

**Messages to prepare:**
- Intro: `suggested places to eat, do a thumbsup where we should meet`
- Each place: `<index>. <name> - <url>`

## Subtask 2 - Send WhatsApp Messages

**Intent:** Send the intro, then each place as its own separate message to `contact_name`
in the native WhatsApp Mac app.

- Activate WhatsApp with:
  ```bash
  osascript -e 'tell application "WhatsApp" to activate'
  ```
- Use native WhatsApp for Mac, not WhatsApp Web.
- Confirm the correct chat is open. If needed, use the left sidebar Search field and open
  the top chat whose displayed name matches `contact_name`. A self-chat can appear as
  `<name> (You)`.
- Confirm the right-pane chat header matches `contact_name` before typing.
- Click the compose box.
- If stale draft text is present, use Cmd+A before the first paste.
- Paste the intro and press the physical Return key to send. In UI-agent tools this key
  may be named `enter`.
- Paste each place message and press Return/`enter` after each one.
- Do not combine places into one message.
- Do not click the send button unless the user explicitly allows a manual fallback.
- After the last message, verify the final outgoing bubble is visible and the compose box
  is clear.

## Speed Notes

- Do not dump WhatsApp's full accessibility tree; it is slow in Electron.
- Verify the correct chat once, verify the first send clears the compose box, then send
  the remaining messages in a tight clipboard paste + Return loop.
- Take one final screenshot after the last message instead of checking every message with
  screenshots or accessibility lookups.
