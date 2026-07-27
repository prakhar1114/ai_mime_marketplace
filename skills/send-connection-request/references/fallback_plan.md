# Fallback Plan

## 1. Open the LinkedIn profile

Intent: Navigate to the requested profile without disturbing existing browser work.

- Open a new browser tab.
- Navigate to the exact `profile_url`.
- Wait until the profile header is visible.
- If LinkedIn shows a login page, stop and return `failed` with a login-required message.
- If the profile is unavailable or the URL does not load, return `failed`.

Notes:
- Use `https://www.linkedin.com/in/.../` profile URLs.
- The browser-harness path uses `new_tab(url)` so the active user tab is not clobbered.

## 2. Detect relationship state

Intent: Avoid sending when the profile is already connected or already pending.

- Inspect the profile header/top card before clicking anything.
- If the top card shows `1st`, `1st degree`, or a visible `Message` relationship state for a 1st-degree profile, return `already_connected`.
- If the top card or primary action area shows `Pending`, return `pending`.
- If neither state is present, continue to Connect.

Notes:
- In validation, the profile `https://www.linkedin.com/in/ravi-kumar-kushawaha-224950121/` showed `Ravi Kumar Kushawaha · 1st` plus `Message`; the expected output is `already_connected`.
- Avoid matching `1st` from posts far down the feed. Prefer text from the first profile sections under `main`.

## 3. Find and click Connect

Intent: Use LinkedIn's visible connection action when it exists.

- First look for a visible top-card button, link, or role button whose text or aria label is exactly `Connect`.
- Prefer the selector-first invite path: derive the target vanity from `/in/<vanity>/`, find visible `main a[href*="/preload/custom-invite"]` anchors whose `vanityName` query param equals that vanity, and click the visible anchor coordinates.
- Prefer the main profile action over the sticky header action when both matching invite anchors are visible.
- If no primary Connect button appears, click the visible top-card `More` button.
- In the opened menu, click `Connect` if present.
- If no Connect action exists, return `failed`.

Notes:
- `https://www.linkedin.com/in/ashishpatel13/` rendered Connect as a plain `<a>` link with aria label `Invite Ashish Patel to connect`, not a button.
- `https://www.linkedin.com/in/manjeet-verma-b06326214/` required clicking the exact visible invite anchor; broad text matching and raw pending substring checks caused false positives.
- Use visible button/link text and aria labels only as fallbacks after the vanity-matched invite selector.
- Do not loop over multiple profiles or retry aggressively.

## 4. Add optional note and send

Intent: Submit one connection request with the requested note behavior.

- After Connect opens the invitation modal, wait for the modal controls.
- Only treat the invite prompt as ready when Chrome's Accessibility tree exposes a dialog named `Add a note to your invitation?` or a visible LinkedIn modal/dialog container exists. Do not use unrelated feed/page `Send` controls as a modal-ready signal.
- If `custom_note` is non-empty, click `Add a note` if shown.
- Focus the visible textarea and insert the note, then verify the visible field text matches `custom_note` before clicking Send.
- Click `Send` or `Send invitation` using the modal-scoped control.
- If `custom_note` is empty, click `Send without a note` using the Chrome Accessibility tree button whose role is `button` and name is exactly `Send without a note`; otherwise click the available modal-scoped `Send` button.
- If the send control is unavailable, return `failed`.

Notes:
- The direct invitation dialog for `ashishpatel13` showed `Add a note` and `Send without a note`.
- The automated runner first uses CDP text insertion for note entry, then falls back to a DOM value update with input/change events if LinkedIn does not reflect the text.
- Stable selector finding from `https://www.linkedin.com/in/chaitanya-shinde-pmp%C2%AE-715b89110/`: the profile Connect selector was a visible `main a[href*="/preload/custom-invite"]` anchor whose `vanityName` query param was `chaitanya-shinde-pmp®-715b89110`.
- Stable modal finding: the visible invite modal did not appear in `document.body.innerText` or normal page selectors like `[role="dialog"]` / `.artdeco-modal`, but Chrome's CDP Accessibility tree exposed `role=dialog`, `name=Add a note to your invitation?`, and buttons named `Add a note` and `Send without a note`.
- The no-note path was validated end-to-end on Chaitanya after the AX selector update and returned `sent` after the refreshed profile showed `Pending`.
- Custom-note textarea selectors after `Add a note` were not re-confirmed in this review; if note entry fails, leave the tab open and complete that step manually.
- Do not try to bypass LinkedIn warnings, rate limits, checkpoints, or other account-safety interstitials.

## 5. Report, close, or hand off

Intent: Return the skill result and leave the browser clean unless the user needs to inspect a failure.

- After clicking Send for a new request, navigate the same tab back to the exact original `profile_url`.
- Wait for the direct profile page to load, then inspect the profile header/top-card controls again.
- If the refreshed direct profile page shows `Pending`, return `sent` with a message explaining that the direct profile page now shows pending.
- If Send was clicked but the refreshed direct profile page does not show `Pending`, return `failed`, leave the tab open, and show a visible banner asking the user to check the tab.
- If the profile is already pending or already connected, return that state and close the profile tab opened for this run.
- If the run fails because login, profile load, Connect, note entry, or Send is blocked, leave the tab open and show a visible banner asking the user to check the tab.
- Failed runs should exit non-zero while still printing the workflow JSON result.

Notes:
- If a request was actually sent, rerunning for the same profile may return `pending`.
