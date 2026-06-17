import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

SLACK_API = "https://slack.com/api"


def log_event(event_type, **kwargs):
    """Emit a structured execution log event to stderr."""
    event = {"event": event_type, **kwargs}
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


def slack_post_json(method, token, payload):
    url = f"{SLACK_API}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slack_get(method, token, params):
    url = f"{SLACK_API}/{method}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Map common Slack API error codes to plain-language guidance.
ERROR_HELP = {
    "missing_scope": "The bot token is missing the 'chat:write' scope. Add it under "
                     "OAuth & Permissions and reinstall the app.",
    "not_in_channel": "The bot is not a member of this channel. Invite it with "
                      "'/invite @<bot>' or add the 'chat:write.public' scope.",
    "channel_not_found": "The channel was not found. Check the channel name or ID.",
    "invalid_auth": "The bot token is invalid or revoked.",
    "not_authed": "No valid bot token was provided.",
    "is_archived": "The channel is archived; messages cannot be posted to it.",
}


def main():
    parser = argparse.ArgumentParser(description="Send a message to a Slack channel via bot token")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        with open(args.inputs_json, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    except Exception as e:
        print(f"Error reading inputs: {e}", file=sys.stderr)
        sys.exit(1)

    channel = (inputs.get("channel") or "").strip()
    message = inputs.get("message")

    if not channel:
        print("Missing required input: channel", file=sys.stderr)
        sys.exit(1)
    if not message:
        print("Missing required input: message", file=sys.stderr)
        sys.exit(1)

    # Load credentials (scoped, read-only file injected by the app).
    try:
        creds = json.load(open(os.environ["AI_MIME_CREDENTIALS_PATH"]))
        token = creds["slack"]["bot_token"]
    except Exception as e:
        print(f"Error reading Slack credentials: {e}", file=sys.stderr)
        sys.exit(1)

    # --- 1. Post the message ---
    log_event("step_start", id="post_message", title="Posting message to Slack")
    try:
        result = slack_post_json("chat.postMessage", token, {"channel": channel, "text": message})
    except urllib.error.URLError as e:
        log_event("step_failed", id="post_message", error=f"Network error contacting Slack: {e}", recoverable=False)
        sys.exit(1)

    if not result.get("ok"):
        err = result.get("error", "unknown_error")
        hint = ERROR_HELP.get(err, "")
        log_event("step_failed", id="post_message",
                  error=f"Slack rejected the message: {err}. {hint}".strip(), recoverable=False)
        sys.exit(1)

    channel_id = result.get("channel")
    ts = result.get("ts")
    log_event("step_done", id="post_message",
              outputs={"channel_id": channel_id, "ts": ts}, summary="Message posted")

    # --- 2. Fetch a clickable permalink ---
    log_event("step_start", id="get_permalink", title="Building message link")
    permalink = None
    try:
        plink = slack_get("chat.getPermalink", token, {"channel": channel_id, "message_ts": ts})
        if plink.get("ok"):
            permalink = plink.get("permalink")
    except Exception:
        permalink = None  # Non-fatal: the message was posted successfully.
    log_event("step_done", id="get_permalink",
              outputs={"permalink": permalink}, summary="Built message link" if permalink else "Permalink unavailable")

    outputs = {
        "channel": channel,
        "channel_id": channel_id,
        "ts": ts,
        "permalink": permalink,
    }
    if permalink:
        print(f"Message sent to {channel}: {permalink}")
    else:
        print(f"Message sent to {channel} (ts {ts}).")

    log_event("workflow_done", outputs=outputs)


if __name__ == "__main__":
    main()
