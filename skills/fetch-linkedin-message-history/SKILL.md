---
name: fetch-linkedin-message-history
description: Fetch read-only LinkedIn message history from the user's logged-in browser for either a LinkedIn messaging thread URL or a LinkedIn profile URL. Use when the user wants recent/default LinkedIn chat history, sender names, timestamps, raw structured message data, and Markdown-formatted clickable links without sending messages or opening shared URLs individually.
---

## Preconditions

- The user is already logged in to LinkedIn in Chrome.
- The skill uses the AI Mime browser harness through `$AI_MIME_BROWSER_HARNESS_BIN`.

## Inputs

Read JSON from `--inputs-json`. Provide exactly one of:

- `profile_url`: LinkedIn profile URL, or `null`.
- `thread_url`: LinkedIn messaging thread URL, or `null`.

Optional:

- `days`: integer day window, or `null`. When `null`, LinkedIn's latest/default message set is returned, capped by LinkedIn's API/page behavior.

Validation rules:

- Exactly one of `profile_url` or `thread_url` must be non-null.
- `profile_url` is optional; use `thread_url` alone for direct thread fetches.
- Both null is invalid.
- Both filled is invalid.
- `days` must be null or a non-negative integer.
- Validation failures return `success: false` with `validation_message`; they do not launch LinkedIn browser automation.

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

Runtime does not create or repair `.venv`.

## Outputs

The script prints one stdout JSON object:

```json
{"event":"workflow_done","outputs":{"success":true,"runs":[]}}
```

Validation failures print the same wrapper with `outputs.success` set to `false` and a `validation_message` explaining the invalid input.

Each run includes:

- `messages`: structured records with sender name (`sender` as `You` or the LinkedIn display name), timestamp, text, content type, and direct LinkedIn message metadata.
- `message_history_markdown`: Markdown list with clickable links formatted as `[url](url)`.
- `shared_content`: for LinkedIn shared posts, direct message-payload fields only: host URN, host type, activity id, derived LinkedIn activity URL, and direct `preview_text` if LinkedIn included it in the message payload.
- `possibly_truncated`: true only when the fetched default API page does not reach older than the requested day cutoff.

The skill does not open each shared URL and does not make per-shared-item preview requests.

## Progress logs

Progress logs are written to stderr in clear, short, natural language suitable for an end-user overlay, such as "Opening a neutral LinkedIn page for authenticated API access..." and "Reading messages through LinkedIn's first-party messaging API...".

## Fallback

Read `references/fallback_plan.md` if `run.sh` fails. The fallback describes how to manually use the LinkedIn UI and same-origin browser APIs without sending messages or opening shared URLs individually.

## ask_llm decision points

None.

## References

- `references/fallback_plan.md`
