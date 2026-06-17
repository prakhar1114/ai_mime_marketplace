import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request


def log_event(event_type, **kwargs):
    """Emit structured execution log events to stderr."""
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False),
          file=sys.stderr, flush=True)


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {label}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Add a comment to a Jira ticket")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    inputs = load_json(args.inputs_json, "inputs")
    ticket = (inputs.get("ticket") or "").strip()
    comment = inputs.get("comment")

    if not ticket:
        print("Missing required input: ticket", file=sys.stderr)
        sys.exit(1)
    if not comment or not str(comment).strip():
        print("Missing required input: comment", file=sys.stderr)
        sys.exit(1)
    comment = str(comment)

    creds_path = os.environ.get("AI_MIME_CREDENTIALS_PATH")
    if not creds_path:
        print("AI_MIME_CREDENTIALS_PATH not configured", file=sys.stderr)
        sys.exit(1)
    creds = load_json(creds_path, "credentials")
    jira = creds.get("jira", {})
    email = jira.get("email")
    api_token = jira.get("api_token")
    domain = (jira.get("domain") or "").replace("https://", "").replace("http://", "").strip("/")

    if not (email and api_token and domain):
        print("Missing Jira credentials (email, api_token, domain)", file=sys.stderr)
        sys.exit(1)

    # --- Post comment via Jira Cloud REST API v3 ---
    log_event("step_start", id="post_comment", title=f"Adding comment to {ticket}")

    url = f"https://{domain}/rest/api/3/issue/{ticket}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph",
                 "content": [{"type": "text", "text": comment}]}
            ],
        }
    }
    token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 401:
            msg = "Authentication failed — check Jira email and API token."
        elif e.code == 404:
            msg = f"Ticket '{ticket}' not found (or no permission to comment)."
        else:
            msg = f"Jira API error {e.code}: {detail}"
        log_event("step_failed", id="post_comment", error=msg, recoverable=False)
        sys.exit(1)
    except urllib.error.URLError as e:
        log_event("step_failed", id="post_comment", error=f"Network error: {e.reason}", recoverable=False)
        sys.exit(1)

    comment_id = body.get("id")
    ticket_url = f"https://{domain}/browse/{ticket}"
    outputs = {"ticket": ticket, "comment_id": comment_id, "ticket_url": ticket_url}
    log_event("step_done", id="post_comment", outputs=outputs,
              summary=f"Comment {comment_id} added to {ticket}")

    log_event("workflow_done", outputs=outputs)
    print(f"Added comment to {ticket}: {ticket_url}")


if __name__ == "__main__":
    main()
