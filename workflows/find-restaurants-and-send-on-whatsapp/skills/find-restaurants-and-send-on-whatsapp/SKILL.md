---
name: find-restaurants-and-send-on-whatsapp
description: Search Google Maps for restaurants matching a query, capture a configurable number of top result names and URLs, and send them as separate WhatsApp messages via the native WhatsApp Mac app.
---

# Find Restaurants and Send on WhatsApp

Searches Google Maps for a restaurant query, extracts the top place names and URLs
(default 5), closes the Maps search tab, then sends an intro plus each place as a
separate message to a WhatsApp contact using the native WhatsApp Mac app.

## Inputs
- `search_query` (required, string): The Google Maps search, typically cuisine + area
  (e.g. "italian restaurants in indiranagar").
- `contact_name` (required, string): Exact WhatsApp contact name to open and message
  (e.g. "Prakhar Jain"). A self-chat appears as "<name> (You)" and matches fine.
- `result_limit` (optional, integer): Number of top unique restaurant results to extract
  and send. Defaults to `5`.

## Run
Run via the executable bash wrapper:
```bash
./run.sh [path/to/inputs.json]
```
If no path is given it defaults to `inputs/inputs.example.json`.

Python runtime contract:
- `run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`,
  workflow `.venv/bin/python`, then the required `$AI_MIME_PYTHON_PATH`.
- `scripts/run.py` uses only the Python standard library, so no virtualenv is required.
- The skill shells out to `$AI_MIME_BROWSER_HARNESS_BIN` for Google Maps and
  `$AI_MIME_UI_AGENT_CMD` for native WhatsApp.

## How It Works
1. **find_top_restaurants** (`browser_harness`): Opens
   `https://www.google.com/maps/search/<urlencoded query>` in a new Chrome tab, waits for
   `div[role=feed]`, reads unique result cards (`div.Nv2PK`) using `.qBF1Pd` for the name
   and `a.hfpxzc[href]` for the Google Maps URL, then closes the Maps tab.
2. **send_whatsapp_message** (`ui_agent`): Activates native WhatsApp, confirms the target
   chat, sends `suggested places to eat, do a thumbsup where we should meet`, then sends
   each place as its own single-line message: `<index>. <name> - <url>`. The UI agent uses
   clipboard paste and the Return/`enter` key; it verifies the first send and final state
   but avoids slow per-message screenshots.

## Outputs
- `restaurant_places` (list[dict]): Top restaurants in display order, each with `name`
  and `url`.
- `restaurant_messages` (list[str]): The intro message followed by one message per place.
- `sent_confirmation` (dict): `{ "sent": true, "messages_sent": <count>, "note": "..." }`
  from the UI agent.

## Progress Log Format
The script emits JSON log events on `stderr`:
- `{"event": "step_start", "id": "find_top_restaurants", "title": "..."}`
- `{"event": "step_done", "id": "find_top_restaurants", "outputs": {...}, "summary": "..."}`
- `{"event": "step_failed", "id": "...", "error": "...", "recoverable": false}`
- `{"event": "workflow_done", "outputs": {...}}`

The process exits non-zero on `step_failed`.

## Fallback
If Google Maps extraction fails or WhatsApp cannot complete, follow
`references/fallback_plan.md`. The Maps fallback is manual/UI-agent extraction from the
left results panel; the WhatsApp fallback is already UI-agent driven.

## ask_llm Decision Points
None. Restaurant extraction is deterministic DOM scraping, and the WhatsApp flow is
handled by the UI agent. No `ask_llm` calls are used.

## References
- [fallback_plan.md](references/fallback_plan.md): Manual/UI-agent recovery steps.
- [learned_notes.md](references/learned_notes.md): Durable selectors, URL pattern,
  WhatsApp activation notes, and speed gotchas.
