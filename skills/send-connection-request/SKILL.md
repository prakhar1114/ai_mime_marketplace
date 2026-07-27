---
name: send_connection_request
description: Send one LinkedIn connection request from a profile URL using the user's logged-in browser session, optionally adding a custom note, and report whether it was sent, pending, already connected, or failed.
---

# send_connection_request

Open a LinkedIn profile, detect the current relationship state, and send a single connection request when a Connect action is available. If `custom_note` is empty, send without a note; if it is non-empty, add and verify the note before sending. After a new request is submitted, refresh the original profile URL and verify the direct profile page shows `Pending`.

For the primary Connect action, the runner first derives the vanity name from `profile_url` and clicks the matching visible `/preload/custom-invite` profile anchor instead of relying on broad visible-text search. For the invite modal, LinkedIn's current UI exposes the reliable controls through Chrome's Accessibility tree rather than normal page DOM selectors; the runner uses AX role/name nodes for the dialog and send controls.

## Preconditions

The user must already be logged into LinkedIn in the Chrome/browser profile controlled by `$AI_MIME_BROWSER_HARNESS_BIN`.

## Inputs

JSON object:

- `profile_url` (string, required): LinkedIn profile URL, for example `https://www.linkedin.com/in/example/`.
- `custom_note` (string, optional): note text to include. Empty or omitted means send without a note.

## Run

Use:

```bash
./run.sh /path/to/inputs.json
```

Without an argument, `run.sh` uses `inputs/inputs.example.json`.

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

This skill has no third-party Python dependencies and does not need `requirements.txt`. Runtime does not create or repair `.venv`.

## Outputs

The runner prints a single-line JSON object to stdout:

```json
{"event":"workflow_done","outputs":{"status":"sent","message":"Connection request sent."}}
```

`outputs.status` is one of:

- `sent`: connection request was submitted in this run and the refreshed direct profile page showed `Pending`.
- `pending`: LinkedIn already showed a pending request before sending.
- `already_connected`: profile is already a 1st-degree connection.
- `failed`: login, page load, unavailable profile, missing Connect action, note-entry mismatch, send-modal failure, or post-send pending verification failure. Failed runs exit non-zero.

Successful and known terminal runs close the tab opened by the skill. Failed runs intentionally leave that tab open with a visible error banner asking the user to check LinkedIn.

## Progress logs

Progress logs are written to stderr in clear, short, natural language suitable for an end-user overlay, such as `Opening LinkedIn profile...`, `Looking for Connect...`, and `Typing note...`.

## Fallback

If `run.sh` fails, read `references/fallback_plan.md` and complete the same single-profile workflow manually or with a UI agent. Do not bulk-send requests or attempt account-risk workarounds.

## Stable selector notes

- Profile Connect: `main a[href*="/preload/custom-invite"]` with `vanityName` equal to `/in/<vanity>/`.
- Invite modal: Chrome Accessibility tree role `dialog`, name `Add a note to your invitation?`.
- No-note send: Chrome Accessibility tree role `button`, name `Send without a note`.
- DOM gap: the modal may not appear in `document.body.innerText` or `[role="dialog"]` page selectors even while visible. Use AX first for modal actions.
- Remaining unconfirmed path: custom-note textarea selectors can vary after `Add a note`; if note entry fails, leave the tab open and use the fallback plan.

## ask_llm decision points

None. The skill uses deterministic LinkedIn page-state checks, visible button/link text, and LinkedIn's visible invite link when Connect is rendered as an anchor.

## References

- `references/fallback_plan.md`: manual/UI-agent fallback steps, state checks, selectors, and traps observed during validation.
