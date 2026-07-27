# Fallback Plan

## Validate Inputs

Intent: Ensure the user provided one LinkedIn chat target.

- Check that exactly one of `profile_url` or `thread_url` is non-null.
- Confirm the non-null URL is on `linkedin.com`.
- Confirm `thread_url` contains `/messaging/thread/`.
- Confirm `days` is null or a non-negative integer.

Notes: Both URL fields null or both filled is an input error.

## Thread URL Path

Intent: Read a thread through LinkedIn's own logged-in browser session without opening shared URLs.

- Open a neutral LinkedIn page such as `https://www.linkedin.com/feed/` in a new tab.
- Stop if LinkedIn shows login, checkpoint, captcha, rate limit, or security verification.
- Read `/voyager/api/me` with same-origin browser credentials and `csrf-token` from `JSESSIONID`.
- Build conversation URN as `urn:li:msg_conversation:(<viewer_profile_urn>,<thread_id>)`.
- Call `/voyager/api/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=(conversationUrn:<strict-encoded-conversation-urn>)`.
- Parse `included` records of type `com.linkedin.messenger.Message` and `com.linkedin.messenger.MessagingParticipant`.
- Close the tab opened by the skill.

Notes: Use `csrf-token`, `x-restli-protocol-version: 2.0.0`, browser cookies, and `accept: application/vnd.linkedin.normalized+json+2.1`. Do not send messages. Do not open shared URLs.

## Profile URL Path

Intent: Locate the existing conversation for a LinkedIn profile, then read messages through the same message API.

- Open the profile URL in a new tab.
- Stop if LinkedIn shows login, checkpoint, captcha, rate limit, or security verification.
- Find a Message link matching `/messaging/compose/?profileUrn=...&recipient=...`.
- If no Message link exists, return a clear failure.
- Navigate the same opened tab to the Message link.
- Read the observed `messengerMessages` resource from browser performance entries and extract `conversationUrn`.
- Fetch the message API using that conversation URN.
- Close the tab opened by the skill.

Notes: Opening a profile Message view may mark the conversation as seen/read. Do not type in the composer.

## Message Formatting

Intent: Return structured data and Markdown with clickable links.

- For each message, derive `sender` as `You` when the sender profile URN equals the viewer profile URN; otherwise use participant `firstName` + `lastName`.
- Linkify text URLs as `[url](url)`.
- For LinkedIn shared content, return direct message-payload fields: host URN, host type, activity id, and derived URL `https://www.linkedin.com/feed/update/urn:li:activity:<id>/`.
- Include `preview_text` only when it is present directly in the message payload.

Notes: Do not make per-shared-item preview calls. Do not open shared URLs individually.
