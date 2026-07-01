---
name: jira-get-fields
description: Fetch Jira Cloud issue fields through Jira REST API v3 and return a compact, cleaned JSON payload. Use when the user wants issue field values, custom fields, description text, comments, subtasks, or other returned Jira fields without duplicate metadata-heavy structures.
---

# Jira Get Fields

Fetches all returned fields for one Jira Cloud issue via `GET /rest/api/3/issue/{issueIdOrKey}?fields=*all&expand=names,schema`, then returns a cleaned JSON object. The cleanup runs after the raw Jira payload is built and before the final result is printed.

## Inputs
- `ticket` (string, required): Jira issue key, e.g. `KAN-2`.

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
On success the script prints a JSON object to stdout:
- `ticket`: Fetched issue key.
- `ticket_id`: Jira internal issue id, when returned.
- `ticket_url`: Browse URL of the ticket.
- `field_count`: Number of fields returned by Jira for the issue.
- `fields`: Object keyed by Jira field id containing cleaned values.
- `auth_method`: `api_token` or `browser_session`.

Cleanup rules:
- Drops `fields_by_id` entirely.
- Converts the field list into a single object, e.g. `"summary": "Task 2-1"`.
- Flattens common Jira objects to readable strings, e.g. user `displayName` and metadata `name`.
- Extracts plain text from Atlassian Document Format fields such as `description`.
- Returns `comment` as `comments`, with each comment reduced to `author`, `body`, and `created`.
- Reduces `subtasks` to `key`, `summary`, `status`, and `issuetype`.

## Progress log format
Structured JSON events are emitted on stderr:
- `{"event":"step_start","id":"get_issue_fields","title":"..."}`
- `{"event":"step_done","id":"get_issue_fields","outputs":{...},"summary":"..."}`
- `{"event":"step_failed","id":"get_issue_fields","error":"...","recoverable":false}`
- `{"event":"workflow_done","outputs":{...}}`

Exit code is non-zero on failure.

## Credentials
Service `jira` (filled in from `credentials.template.json`):
- `email`: Atlassian account email.
- `api_token`: Jira API token from id.atlassian.com.
- `domain`: site domain, e.g. `your-company.atlassian.net`.

Read at runtime from `$AI_MIME_CREDENTIALS_PATH`. Never hardcoded.

## Fallback
If API-token authentication fails and `$AI_MIME_BROWSER_HARNESS_BIN` is available, the script opens the issue in the user's existing Chrome session and performs the same Jira REST reads from that authenticated browser context. Chrome must already be logged into the Jira site for this fallback to work.

If both automated paths fail, see `references/fallback_plan.md` for manual API and browser-session steps.

## ask_llm decision points
None. The task is fully deterministic.

## References
- `references/fallback_plan.md` - manual steps and curl/browser equivalent.
