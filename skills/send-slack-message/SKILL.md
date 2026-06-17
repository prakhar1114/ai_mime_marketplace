---
name: send-slack-message
description: >-
  Post a message to a Slack channel using a Slack bot token via the Slack Web
  API, and return a clickable permalink to the posted message. Use this whenever
  the user wants to send, post, or announce a message to a Slack channel through
  a bot, drop a notification into Slack, or push text to a Slack channel
  programmatically — even if they don't say "API". Takes a channel and message
  text; posts as the bot and returns the message link.
---

# Send Slack Message (Bot)

Posts a message to a Slack channel as a bot and returns a clickable link to the
posted message. Uses the Slack Web API (`chat.postMessage` + `chat.getPermalink`)
over HTTPS — no browser or UI automation, so it is fast and reliable.

## Credentials

Requires a Slack bot token stored under service `slack`:
- `slack.bot_token` — a bot token (`xoxb-...`) with the **`chat:write`** scope
  (add **`chat:write.public`** too if the bot is not invited to the target
  channel). The installer is prompted to fill `credentials.template.json`.

## Inputs

Read from the JSON file passed via `--inputs-json`. See
`inputs/inputs.example.json` and `inputs/inputs.template.json`.

- `channel` (required) — channel name (e.g. `#general`) or channel ID (e.g. `C0BB39TU3AS`).
- `message` (required) — the text to post.

## Run

```bash
./run.sh inputs/inputs.example.json
# or
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

Runtime contract:
- `run.sh` uses the first available interpreter in this order: skill
  `.venv/bin/python`, workflow `.venv/bin/python`, then required
  `$AI_MIME_PYTHON_PATH`.
- No `requirements.txt` — the script uses only the Python standard library
  (`urllib`), so no `.venv` is required. Runtime does not create or repair a
  `.venv`.

## Outputs

On success, prints a one-line confirmation with the message link and emits a
`workflow_done` event whose `outputs` contain:
- `channel` — the channel input as provided.
- `channel_id` — the resolved Slack channel ID.
- `ts` — the posted message timestamp.
- `permalink` — clickable Slack link to the message (may be `null` if the
  permalink lookup fails, though the message is still posted).

## Progress log format

Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"<step_id>","title":"…"}`
- `{"event":"step_done","id":"<step_id>","outputs":{…},"summary":"…"}`
- `{"event":"step_failed","id":"<step_id>","error":"…","recoverable":false}`
- `{"event":"workflow_done","outputs":{…}}`

Step ids: `post_message`, `get_permalink`. Exits non-zero on `step_failed`.

## Fallback

If the API call fails, see `references/fallback_plan.md`. Common errors are
mapped to plain-language guidance in the script (`missing_scope`,
`not_in_channel`, `channel_not_found`, `invalid_auth`). The fallback covers
fixing scopes/membership and posting manually via the Slack app.

## ask_llm decision points

None. The task is fully deterministic — no `ask_llm` calls.

## References

- `references/fallback_plan.md` — recovery steps and Slack API error guidance.
