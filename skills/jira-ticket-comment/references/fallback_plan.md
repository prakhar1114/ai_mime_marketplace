# Fallback Plan — Jira Ticket Comment

## Add a comment to a Jira ticket
Intent: Post a comment to a Jira Cloud issue.

Steps (deterministic API — preferred):
- Endpoint: `POST https://{domain}/rest/api/3/issue/{ticket}/comment`
- Auth: HTTP Basic with `email:api_token` (Atlassian account email + API token).
- Header: `Content-Type: application/json`.
- Body uses Atlassian Document Format (ADF):
  ```json
  {"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"<comment>"}]}]}}
  ```
- Success = HTTP 201; response JSON has `id` (comment id) and `self`.

curl equivalent:
```bash
curl -s -u "$EMAIL:$API_TOKEN" \
  -X POST "https://$DOMAIN/rest/api/3/issue/$TICKET/comment" \
  -H "Content-Type: application/json" \
  -d '{"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"YOUR COMMENT"}]}]}}'
```

Notes / traps:
- The comment body MUST be ADF, not a plain string, on REST API v3.
- 401 = bad email/token. 404 = wrong ticket key or no permission.
- Get an API token at https://id.atlassian.com/manage-profile/security/api-tokens.
- Browse URL for verification: `https://{domain}/browse/{ticket}`.

Manual UI fallback (last resort):
- Open `https://{domain}/browse/{ticket}` in a logged-in browser.
- Scroll to the Activity/Comments section, click the comment box, type the text, click "Save".

## Cleanup (remove a test comment)
- `DELETE https://{domain}/rest/api/3/issue/{ticket}/comment/{comment_id}` with the same auth.
