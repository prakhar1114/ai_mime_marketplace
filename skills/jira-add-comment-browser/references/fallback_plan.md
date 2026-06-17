# Fallback plan — Add a comment to a Jira ticket

If `run.sh` fails, a human or the UI agent can finish the task from this file alone.

Site: `https://aimime.atlassian.net` (Jira Cloud). The user is normally already
logged in via their Chrome profile.

## Subtask 1 — Open the ticket
**Intent:** Land on the ticket's detail page.
- Open `https://aimime.atlassian.net/browse/<ticket>` (e.g. `KAN-2`) in Chrome.
- Wait for the page to load (the ticket title + key appear).
- Notes:
  - If redirected to `id.atlassian.com` or a `/login` page → NOT logged in. Stop and
    ask the user to log in to Jira in Chrome, then retry. Do not enter credentials.
  - Confirm the ticket loaded by checking the ticket key (e.g. `KAN-2`) is on the page.

## Subtask 2 — Open the comment editor
**Intent:** Get a focused, ready-to-type comment box.
- Press the `m` key (Jira keyboard shortcut: "Add a comment"). Jira even shows a
  "Pro tip: press M to comment" hint. This opens the editor with a formatting toolbar
  and focuses it.
- Notes:
  - The `m` shortcut only works when the page body has focus (true right after load),
    NOT when focus is already inside another text field.
  - The editor element is `div[contenteditable=true]`. Clicking its bounding-box
    center ensures focus before typing.
  - Do NOT type while the editor is unfocused — Jira's single-key shortcuts will fire
    and navigate away (e.g. typing jumped to the board view during exploration).

## Subtask 3 — Type the comment
**Intent:** Enter the comment text.
- With the editor focused, type the comment text.

## Subtask 4 — Save the comment
**Intent:** Commit the comment.
- Press **Cmd+Enter** (on macOS, Cmd+Return). In the browser harness this is
  `press_key("Enter", modifiers=4)` (modifiers bitfield: 1=Alt, 2=Ctrl, 4=Meta/Cmd, 8=Shift).
  Note: `press_key("Meta+Enter")` does NOT work — combos must use the `modifiers` arg.
- Alternative: click the on-screen **Save** button. This is fragile because the page
  scroll position shifts (the button's pixel Y is not stable) and a flaky "Spaces"
  hover popup (anchored to the left-nav "More spaces") sometimes overlays content and
  intercepts clicks. If you must click Save, dismiss any popup with `Escape` first and
  locate the button via DOM:
  `[...document.querySelectorAll("button")].find(b => b.textContent.trim() === "Save")`.
- Verify success: after saving, the `div[contenteditable=true]` editor is empty AND
  there is no `button` whose text is exactly "Save" → comment committed and editor
  reset to the "Add a comment…" placeholder. The new comment shows in
  Activity → Comments as the logged-in user with timestamp "now".

## Side effects / cleanup
- Posts a REAL, visible comment as the logged-in user. Each run adds another comment
  (no de-duplication). To remove a test comment, use the comment's "•••" menu →
  Delete on the ticket.
