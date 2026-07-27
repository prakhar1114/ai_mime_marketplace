---
name: send-message-on-linkedin
description: Send a message on LinkedIn from the user's logged-in Chrome session, given either a LinkedIn messaging thread URL or a LinkedIn profile URL plus the message text. Use when the user wants to send/reply to a LinkedIn chat. For a profile URL it opens the message composer and will start a brand-new conversation if none exists. Returns whether the send succeeded.
---

## Preconditions

- The user is already logged in to LinkedIn in Chrome.
- The skill uses the AI Mime browser harness through `$AI_MIME_BROWSER_HARNESS_BIN`.

## Inputs

Read JSON from `--inputs-json`. All fields are optional in the schema and are validated at runtime:

- `profile_url`: LinkedIn profile URL, or `null`. Opens that person's message composer (starts a new chat if none exists).
- `thread_url`: LinkedIn messaging thread URL, or `null`.
- `message`: the plain-text message to send. Sent as plain text (no Markdown rendering). Newlines are preserved.

Runtime validation rules (checked before any browser action):

- Exactly one of `profile_url` or `thread_url` must be non-null. Both null or both filled is invalid.
- The provided URL must be a `linkedin.com` URL.
- `thread_url` must contain `/messaging/thread/`; `profile_url` must not be a thread URL.
- `message` must be a non-empty string.
- On invalid input the skill returns `success: false` with a `reason` (also mirrored as `validation_message`) and does NOT launch LinkedIn browser automation. On valid input and a confirmed send it returns `success: true` with a `reason`.

## Run

Run with:

```bash
./run.sh inputs/inputs.example.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

No third-party Python packages are required. If a future change adds `requirements.txt`, install or repair dependencies during skill build or manual repair with:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

These commands are for skill build or manual repair only. Runtime does not create or repair `.venv`.

## Outputs

The script prints one stdout JSON object:

```json
{"event":"workflow_done","outputs":{"success":true,"reason":"Message sent.","status_message":"Message sent.","input_url":"..."}}
```

- `success`: `true` when the message was sent and confirmed in the thread, otherwise `false`.
- `reason`: short human-readable explanation of the outcome, present on every result (both success and failure).
- `status_message`: same human-readable result (kept for backward compatibility).
- `profile_name`: the profile's display name when a `profile_url` was used (otherwise `null`).
- `input_url`: the thread or profile URL used.
- Validation failures print the same wrapper with `success: false`, a `reason`, and a `validation_message`.

## Progress logs

Progress logs are written to stderr in clear, short, natural language suitable for an end-user overlay, such as "Opening the LinkedIn conversation...", "Typing the message...", and "Sending the message...".

## Fallback

Read `references/fallback_plan.md` if `run.sh` fails. It describes how to open the thread or profile composer, type the message, and click Send manually or via the same-origin browser APIs.

## ask_llm decision points

None.

## References

- `references/fallback_plan.md`
