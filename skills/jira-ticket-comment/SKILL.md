---
name: jira-ticket-comment
description: Add a comment to a Jira Cloud ticket using the Jira REST API. Takes a ticket key and comment text and posts the comment to that issue.
---

# Jira Ticket Comment

Adds a plain-text comment to a Jira Cloud ticket via the Jira Cloud REST API v3.

## Inputs
- `ticket` (string, required): Jira issue key, e.g. `KAN-1`.
- `comment` (string, required): The comment text to post.

Inputs are read from a JSON file (see `inputs/inputs.example.json`).

## Run
```bash
./run.sh inputs/inputs.example.json
```
`run.sh` selects the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then the required `$AI_MIME_PYTHON_PATH`.

This skill uses only the Python standard library, so there is no `requirements.txt` and no `.venv` is required. If a future change adds third-party packages, build/repair the environment manually with:
```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```
These install commands are for skill build or manual repair only. Runtime does not create or repair `.venv`.

## Outputs
On success the script posts the comment and emits:
- `ticket`: the issue key.
- `comment_id`: the new comment's id.
- `ticket_url`: browse URL of the ticket.

It also prints a one-line confirmation to stdout.

## Progress log format
Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"post_comment","title":"..."}`
- `{"event":"step_done","id":"post_comment","outputs":{...},"summary":"..."}`
- `{"event":"step_failed","id":"post_comment","error":"...","recoverable":false}`
- `{"event":"workflow_done","outputs":{...}}`

Exit code is non-zero on failure.

## Credentials
Service `jira` (filled in from `credentials.template.json`):
- `email`: Atlassian account email.
- `api_token`: Jira API token from id.atlassian.com.
- `domain`: site domain, e.g. `your-company.atlassian.net`.

Read at runtime from `$AI_MIME_CREDENTIALS_PATH`. Never hardcoded.

## Fallback
If `run.sh` fails, see `references/fallback_plan.md` for the manual API/curl steps.

## ask_llm decision points
None. The task is fully deterministic.

## References
- `references/fallback_plan.md` — manual steps and curl equivalent.
