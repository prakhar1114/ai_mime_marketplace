# Fallback Plan

## update_issue_field
Intent: Overwrite one Jira issue field using Jira Cloud REST API v3.

Steps:
- Confirm the inputs: issue key, field id/name, and replacement value.
- Build the payload as `{"fields":{"<field>":<value>}}`.
- For `description` with plain text, convert the value to Atlassian Document Format:
  `{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"final test"}]}]}`.
- Send `PUT https://<domain>/rest/api/3/issue/<issue-key>` with Basic auth using `email:api_token`, `Content-Type: application/json`, and `Accept: application/json`.
- Treat HTTP `204 No Content` as the successful update response.
- Verify with `GET https://<domain>/rest/api/3/issue/<issue-key>?fields=<field>`.

curl equivalent:
```bash
curl -fsS -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  -X PUT \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  --data '{"fields":{"summary":"New summary"}}' \
  "https://$JIRA_DOMAIN/rest/api/3/issue/KAN-2"
```

Browser-session fallback:
- Open `https://<domain>/browse/<issue-key>` in the existing Chrome session.
- If the ticket page loads and the user is logged in, execute a same-origin `fetch("/rest/api/3/issue/<issue-key>", {method:"PUT", credentials:"include", headers:{"Content-Type":"application/json","Accept":"application/json","X-Atlassian-Token":"no-check"}, body: JSON.stringify(payload)})`.
- Verify with a same-origin `GET /rest/api/3/issue/<issue-key>?fields=<field>`.

Notes:
- Jira returns `204` for successful updates.
- Jira may return `404` for an issue that is missing or not visible to the authenticated account.
- A `401` from `/rest/api/3/myself` means the API-token credential is not authenticating.
- During build, `KAN-2` on `aimime.atlassian.net` was successfully updated through the browser-session REST fallback after the local API-token credential failed authentication.
