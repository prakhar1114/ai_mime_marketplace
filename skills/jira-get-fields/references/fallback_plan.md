# Fallback Plan

## get_issue_fields
Intent: Fetch all returned Jira issue fields and values using Jira Cloud REST API v3.

Steps:
- Confirm the input issue key, for example `KAN-2`.
- Send `GET https://<domain>/rest/api/3/issue/<issue-key>?fields=*all&expand=names,schema` with Basic auth using `email:api_token` and `Accept: application/json`.
- Send `GET https://<domain>/rest/api/3/field` with the same auth to collect field metadata.
- Build one raw field list from the issue response `fields` object. For each field id, attach:
  - `name` from `issue.names`, falling back to `/field` metadata.
  - `schema` from `issue.schema`, falling back to `/field` metadata.
  - `value` from `issue.fields`.
- Before returning, clean the raw output:
  - Drop `fields_by_id`.
  - Convert the raw field list into `fields`, an object keyed by Jira field id.
  - Flatten user objects to `displayName`, metadata objects to `name`, and Atlassian Document Format objects to plain text.
  - Rename the `comment` field to `comments` and reduce each comment to `author`, `body`, and `created`.
  - Reduce each subtask to `key`, `summary`, `status`, and `issuetype`.

curl equivalent:
```bash
curl -fsS -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  -H "Accept: application/json" \
  "https://$JIRA_DOMAIN/rest/api/3/issue/KAN-2?fields=*all&expand=names,schema"

curl -fsS -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  -H "Accept: application/json" \
  "https://$JIRA_DOMAIN/rest/api/3/field"
```

Browser-session fallback:
- Open `https://<domain>/browse/<issue-key>` in the existing Chrome session.
- If the ticket page loads and the user is logged in, execute same-origin reads:
  - `fetch("/rest/api/3/issue/<issue-key>?fields=*all&expand=names,schema", {credentials:"include", headers:{"Accept":"application/json"}})`
  - `fetch("/rest/api/3/field", {credentials:"include", headers:{"Accept":"application/json"}})`
- Use the same cleanup rules as the API-token path.

Notes:
- Jira may return `404` for an issue that is missing or not visible to the authenticated account.
- A `401` means the API-token credential is not authenticating, or the browser session is not logged in for fallback.
- During build, `KAN-2` on `aimime.atlassian.net` was successfully fetched through API-token auth and returned 45 fields.
- The cleaned `KAN-2` output included examples such as `fields.summary = "Task 2-1"`, `fields.status = "In Progress"`, `fields.description = "testing again from antigravity"`, and `fields.comments[]` with author/body/created only.
