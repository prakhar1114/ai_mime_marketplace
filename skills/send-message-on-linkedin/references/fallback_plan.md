# Fallback Plan — Send a LinkedIn message

## Validate Inputs

Intent: Ensure the user provided one LinkedIn target and a message.

- Check that exactly one of `profile_url` or `thread_url` is non-null.
- Confirm the non-null URL is on `linkedin.com`.
- Confirm `thread_url` contains `/messaging/thread/`; confirm `profile_url` is not a thread URL.
- Confirm `message` is a non-empty string.

Notes: Both URL fields null, or both filled, is an input error. Message is sent as plain text.

## Thread URL Path

Intent: Open the existing thread in the user's logged-in session.

- Open the `thread_url` in a new tab; `wait_for_load()` then wait ~4s.
- Stop if LinkedIn shows login, checkpoint, captcha, rate limit, or security verification.
- The composer is present directly on the thread page.

## Profile URL Path

Intent: Open the profile's message composer (new chat allowed).

- Open the `profile_url` in a new tab; wait ~4s.
- Stop on login/checkpoint screens.
- Find the compose link: `document.querySelectorAll('a[href*="/messaging/compose/"]')`; take the first `href`.
  Format: `https://www.linkedin.com/messaging/compose/?profileUrn=urn:li:fsd_profile:<id>&recipient=<id>&screenContext=NON_SELF_PROFILE_VIEW&interop=msgOverlay`.
- If no compose link exists, return a clear failure ("Could not find a Message button for this profile").
- Navigate the same tab to the compose URL (`cdp("Page.navigate", url=compose_url)`); wait ~5s.

Notes: Starting a brand-new conversation from a profile is acceptable (user-approved).

## Type and Send

Intent: Put the message into the composer and click Send.

- Composer selector: `.msg-form__contenteditable` (role=textbox, aria-label "Write a message…").
- Send button selector: `button.msg-form__send-button` — it is disabled until an input event registers.
- Fill recipe (verified):
  - `box.focus()`, clear `box.innerHTML`, append one `<p>` per line of the message (`textContent` = line; empty line → `<p><br></p>`).
  - Dispatch `new InputEvent('input', {bubbles:true, inputType:'insertText', data:<message>})` on the box.
- CRITICAL: `cdp("Input.insertText", ...)` sets text but does NOT enable Send. You must dispatch a real `InputEvent`.
- The Send button enables ASYNCHRONOUSLY (~1s after the input event). Poll `button.msg-form__send-button.disabled` for up to ~8s until it is `false` before clicking.
- Click Send: `document.querySelector('button.msg-form__send-button').click()`; wait ~3s.

## Verify

Intent: Confirm the message actually posted.

- After send, `.msg-form__contenteditable` innerText should be empty AND the last `.msg-s-event-listitem__body` innerText should equal (or contain) the sent message; Send button disabled again.
- If the box cleared but the text can't be matched, report success:false with an "unconfirmed" status rather than assuming success.
- Close the tab opened by the skill (`cdp("Target.closeTarget", targetId=...)`).
