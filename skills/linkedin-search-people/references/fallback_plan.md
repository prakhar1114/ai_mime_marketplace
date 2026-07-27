# Fallback Plan

## Open LinkedIn People Search
Intent: Reach the same read-only LinkedIn people search page the runner uses.

- Make sure Chrome is signed in to LinkedIn.
- Build a URL under `https://www.linkedin.com/search/results/people/`.
- Put the joined free-text inputs (`keywords`, `title`, `company`, `location`) in the `keywords` query parameter.
- Put the requested page number in `page`.
- Put connection filters in `network` using `1st -> F`, `2nd -> S`, `3rd -> O`.
- Open the URL in Chrome and wait for normal page load.

Notes: If LinkedIn redirects to login, stop and ask the user to sign in. Do not type passwords or recover credentials.

## Extract Visible Results
Intent: Read the visible people-result cards from the loaded page.

- Prefer `ul.reusable-search__entity-result-list > li` if LinkedIn exposes the older reusable-search markup.
- Otherwise, use visible `[role="listitem"]` elements that contain a LinkedIn profile link with `/in/`.
- For each card, choose the first `/in/` profile link as the primary profile URL and ignore later mutual-connection links.
- Normalize the profile URL by removing query and hash.
- Parse visible card lines in order: name, degree, headline, location, then action/mutual/follower text.
- Skip action lines such as `Connect`, `Message`, `Follow`, `Pending`, and mutual-connection/follower lines.
- Infer `current_company` from `at Company`, `@ Company`, or the explicit input company if it appears in the headline.

Notes: In this session, LinkedIn did not expose `ul.reusable-search__entity-result-list`; it used semantic `role="list"` / `role="listitem"` containers with obfuscated classes. Avoid depending on generated class names.

## Determine Pagination
Intent: Report whether LinkedIn shows a usable next page control.

- Search visible `button` and `a` elements for text or `aria-label` containing `Next`.
- Treat next page as unavailable if the control is disabled or has `aria-disabled="true"`.
- Do not click pagination during a single-page run; the skill returns only the requested page.

Notes: The skill intentionally avoids rapid pagination or bulk scraping.

## Close the Search Tab
Intent: Clean up the tab the runner opened once results are read.

- The runner opens the search in a NEW Chrome tab and remembers its target id (from `new_tab`).
- When `close_tab_after` is true (the default), close that tab after extraction via CDP `Target.closeTarget` with the remembered target id.
- When `close_tab_after` is false, leave the tab open.

Notes: browser-harness has no `close_tab` helper — use raw `cdp("Target.closeTarget", targetId=...)`. Wrap it in try/except so a close failure never aborts the run or loses results.

## API Shortcut Check
Intent: Prefer a direct endpoint only if it is clearly stable and session-safe.

- Inspect loaded resources for same-session search data.
- In this build, visible resources showed LinkedIn `flagship-web/rsc-action/...search...` requests rather than a stable public people-search API payload.
- Use DOM extraction unless a future exploration proves a reliable endpoint with durable request and response shapes.

Notes: Do not store cookies, tokens, CSRF headers, or account-specific values in the skill.
