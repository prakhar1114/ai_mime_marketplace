# Fallback Plan — Send Slack Message (Bot)

## Subtask: Post a message to a Slack channel
Intent: Deliver `message` text to `channel` as the Slack bot and capture a link.

Primary path (what `scripts/run.py` does):
- `POST https://slack.com/api/chat.postMessage` with header
  `Authorization: Bearer <bot_token>` and JSON body `{"channel": <channel>, "text": <message>}`.
- Success response: `{"ok": true, "channel": "C...", "ts": "..."}`.

Fallback steps if the script fails:
- **`missing_scope`** → In api.slack.com/apps → your app → OAuth & Permissions,
  add the `chat:write` bot scope (and `chat:write.public` for public channels
  the bot has not joined), then **Reinstall to Workspace** and update the token
  in credentials.
- **`not_in_channel`** → In Slack, run `/invite @<bot>` in the target channel,
  or add the `chat:write.public` scope.
- **`channel_not_found`** → Verify the channel name (include the leading `#`) or
  use the channel ID. For private channels, the bot must be a member.
- **`invalid_auth` / `not_authed`** → The token is wrong/revoked; regenerate the
  bot token and refresh credentials.
- **Manual last resort** → Open Slack, go to the channel, type the message, send.

Notes:
- Channel names with a leading `#` are accepted directly by `chat.postMessage`.
- Verified working: workspace `ai-mime.slack.com`, bot user `mimey`.

## Subtask: Build a clickable permalink
Intent: Return a link to the just-posted message.

Primary path:
- `GET https://slack.com/api/chat.getPermalink?channel=<channel_id>&message_ts=<ts>`
  with the bearer token. Response: `{"ok": true, "permalink": "https://<team>.slack.com/archives/<C>/p<ts-no-dot>"}`.

Notes:
- Non-fatal if it fails — the message is already posted. The permalink can be
  reconstructed as `https://<team>.slack.com/archives/<channel_id>/p<ts with the dot removed>`.
