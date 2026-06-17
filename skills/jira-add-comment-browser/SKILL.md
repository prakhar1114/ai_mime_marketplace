---
name: jira-add-comment-browser
description: Add a comment to a Jira ticket on aimime.atlassian.net. Use this whenever the user wants to post, add, leave, or write a comment/note/reply on a Jira issue or ticket (e.g. "comment on KAN-2", "add a note to PROJ-123", "reply on the Jira ticket"), given the ticket key and the comment text.
---

# Jira — Add a comment to a ticket

Opens a Jira Cloud ticket in the user's logged-in Chrome and posts a new comment on it.

## Preconditions
- Google Chrome is running and signed in to `https://aimime.atlassian.net` (the
  automation reuses the existing browser session — it does not log in). If a login
  wall is hit, the run stops and reports it.

## Inputs
Provided as a JSON file (see `inputs/inputs.example.json`):
- `ticket` (string, required) — the Jira issue key, e.g. `KAN-2`.
- `comment` (string, required) — the plain-text comment body to post.

## Run
```bash
./run.sh inputs/inputs.example.json
# or
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

Python runtime contract:
- `run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`,
  workflow `.venv/bin/python`, then the required `$AI_MIME_PYTHON_PATH`.
- This skill has no third-party Python dependencies, so there is no `requirements.txt`
  and no `.venv` is required. It drives Chrome through `$AI_MIME_BROWSER_HARNESS_BIN`.
- If a `requirements.txt` were ever added, build/repair the environment with:
  ```bash
  "$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
  "$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
  ```
  These install commands are for skill build or manual repair only. Runtime never
  creates or repairs `.venv`.

## Outputs
- On success, a `workflow_done` event with:
  - `ticket` — the issue key.
  - `ticket_url` — `https://aimime.atlassian.net/browse/<ticket>`.
  - `comment` — the comment text that was posted.
  - `posted` — `true`.
- The comment is visible in the ticket's Activity → Comments feed.

## Progress log format
Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"post_comment","title":"…"}`
- `{"event":"step_done","id":"post_comment","outputs":{…},"summary":"…"}`
- `{"event":"step_failed","id":"post_comment","error":"…","recoverable":false}` (exits non-zero)
- `{"event":"workflow_done","outputs":{…}}`

## Fallback
If `run.sh` fails, follow `references/fallback_plan.md` to complete the task manually
or via the UI agent. Common failure causes and meanings are reported in the
`step_failed` error string (not logged in, ticket not found, editor didn't open, or
comment didn't save).

## ask_llm decision points
None. The flow is fully deterministic — no `ask_llm` calls are used.

## References
- `references/fallback_plan.md` — step-by-step manual/UI-agent recovery, with the
  selectors, keyboard shortcuts, and traps learned during exploration.
