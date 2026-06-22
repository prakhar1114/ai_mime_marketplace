# Fallback Plan

## Post Reply on X
Intent: Post the supplied reply text on the supplied X status URL and return the new reply URL.

Executable fallback steps:
- Open the supplied `post_url` in the user's logged-in Chrome session.
- Wait for the X post page to render. If X asks for login, sign in first and rerun.
- Find the inline reply composer under the status thread. It is usually a visible `div[role=textbox][data-testid^=tweetTextarea]`.
- If the composer is below the viewport, scroll it into view.
- Click inside the composer, clear any restored draft, and enter `reply_text`.
- Verify the visible Reply button, usually `button[data-testid=tweetButtonInline]`, becomes enabled.
- Submit with Cmd+Return. If that does not submit, click the enabled Reply button.
- Wait for the thread to update.
- Find the newly visible article containing the exact reply text.
- Copy the first `/status/<id>` link in that article that is not the original post ID. That URL is `reply_url`.

Notes:
- Do not rely on the `R` keyboard shortcut for the final automation. In validation, X sometimes opened a composer for the currently focused timeline item instead of the supplied status.
- X can block repeated duplicate comment text on the same thread. Use a different validation reply text for repeated end-to-end tests.
- Required browser-harness selectors:
  - Reply editor: `div[role=textbox][data-testid^=tweetTextarea]`
  - Reply buttons: `button[data-testid=tweetButtonInline]`, `button[data-testid=tweetButton]`
  - Posted reply lookup: visible `article` elements containing the exact reply text and links with `/status/`.
- Side effects are public X replies. Clear by manually deleting test replies from X.
