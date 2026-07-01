---
name: jira-update-fields
description: Update a Jira Cloud ticket field using Jira REST API v3. Use when the user wants to overwrite a Jira issue field such as summary, description, or a customfield value.
---

# Jira Update Fields

Updates one field on a Jira Cloud issue via `PUT /rest/api/3/issue/{issueIdOrKey}` using the simple `fields` overwrite payload.

## Inputs
- `ticket` (string, required): Jira issue key, e.g. `KAN-2`.
- `field` (string, required): Jira field id or field name, e.g. `summary`, `description`, or `customfield_10011`.
- `value` (required): Replacement value for the field. Plain text is accepted for `description` and is converted to Jira's document format.

Inputs are read from a JSON file (see `inputs/inputs.example.json`).

## Run
```bash
./run.sh inputs/inputs.example.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

This skill uses only the Python standard library, so there is no `requirements.txt` and no `.venv` is required. If a future change adds third-party packages, build/repair the environment manually with:
```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```
These install commands are for skill build or manual repair only. Runtime does not create or repair `.venv`.

## Outputs
On success the script emits:
- `ticket`: Updated issue key.
- `field`: Field that was overwritten.
- `ticket_url`: Browse URL of the ticket.
- `updated`: Boolean indicating Jira accepted the update.
- `verified`: Boolean indicating a follow-up read could see the field.
- `auth_method`: `api_token` or `browser_session`.

It also prints a one-line confirmation to stdout.

## Progress log format
Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"update_issue_field","title":"..."}`
- `{"event":"step_done","id":"update_issue_field","outputs":{...},"summary":"..."}`
- `{"event":"step_failed","id":"update_issue_field","error":"...","recoverable":false}`
- `{"event":"workflow_done","outputs":{...}}`

Exit code is non-zero on failure.

## Credentials
Service `jira` (filled in from `credentials.template.json`):
- `email`: Atlassian account email.
- `api_token`: Jira API token from id.atlassian.com.
- `domain`: site domain, e.g. `your-company.atlassian.net`.

Read at runtime from `$AI_MIME_CREDENTIALS_PATH`. Never hardcoded.

## Fallback
If API-token authentication fails and `$AI_MIME_BROWSER_HARNESS_BIN` is available, the script opens the issue in the user's existing Chrome session and performs the same Jira REST update from that authenticated browser context. Chrome must already be logged into the Jira site for this fallback to work.

If both automated paths fail, see `references/fallback_plan.md` for manual API and browser-session steps.

## ask_llm decision points
None. The task is fully deterministic.

## References
- `references/fallback_plan.md` — manual steps and curl/browser equivalent.
