---
name: fetch-linkedin-message-threads
description: Fetch recent LinkedIn Messaging thread URLs, contact names, last-message timestamps, and unread/new status from the user's already logged-in Chrome session. Use when the user needs a read-only list of LinkedIn message conversations from the last N days for later message-data extraction.
---

## Preconditions

Chrome must already be logged into LinkedIn. The skill uses browser-harness through `$AI_MIME_BROWSER_HARNESS_BIN` and opens a temporary LinkedIn tab, then closes that tab when finished.

## Inputs

- `last_message_within_days`: whole number. Include conversations whose last message timestamp is within this many days from the run time.
- `maximum_threads`: optional whole number, `null`, or `0`. `null`, missing, or `0` uses the safe default of `20`, matching LinkedIn's observed default conversation page size. Positive values limit returned threads to that number. Values above `100` are rejected to keep LinkedIn access low-volume.

## Run

Run with:

```bash
./run.sh /path/to/inputs.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

No third-party Python packages are required. If `requirements.txt` is added later, use these build or manual repair commands:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

These install commands are for skill build or manual repair only. Runtime does not create or repair `.venv`.

## Outputs

The script prints one single-line JSON object:

```json
{"event":"workflow_done","outputs":{"threads":[]}}
```

`outputs.threads` is a list of:

- `contact_name`: LinkedIn participant or conversation name.
- `last_message_date`: UTC ISO timestamp of the last message activity.
- `thread_url`: LinkedIn Messaging URL that opens the thread in a new tab.
- `new`: boolean, true when LinkedIn reports unread/new messages for the conversation.

The output also includes `count`, `last_message_within_days`, `maximum_threads`, `pages_fetched`, and `stopped_because`.

## Progress logs

Progress logs are written to stderr in clear, short, natural language suitable for an end-user overlay, such as "Opening LinkedIn...", "Reading LinkedIn profile...", and "Reading thread page 1...".

## Fallback

Read `references/fallback_plan.md` if `run.sh` fails. The fallback keeps the workflow read-only and prioritizes low-volume browser/API access before any manual UI inspection.

## ask_llm decision points

None. The skill does not call `ask_llm`; extraction and filtering are deterministic.

## References

- `references/fallback_plan.md`: manual and UI-agent fallback steps.
