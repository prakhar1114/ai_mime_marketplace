# Fallback Plan

## Search X

Intent: Run the same exact query and date-filtered X search if the packaged script cannot drive the browser harness.

- Ensure Chrome can access X and the user is logged in if X shows a login wall.
- Build a direct search URL with this pattern for date-only filters:
  `https://x.com/search?f=top&q=%22{query}%22%20until%3A{until}%20since%3A{since}&src=typed_query`
- For ISO datetime filters, convert the bounds to UTC epoch seconds and use `until_time:{epoch}` and `since_time:{epoch}` in the query string.
- For the default one-day search, use yesterday as `since` and today as `until`.
- Open the URL in Chrome.
- Verify the X search page shows the `Top` tab and a visible search timeline.
- If direct URL search fails, open `https://x.com/search-advanced`, enter the query as the exact phrase, set from/to date filters, submit the search, and switch to `Top`.

Notes:
- X `until:` / `since:` are used for dates; `until_time:` / `since_time:` are used for datetimes.
- The script uses `f=top` and then sorts extracted posts by numeric likes locally.

## Extract Visible Posts

Intent: Collect structured data from search results while scrolling.

- For each visible post/reply result, capture the canonical post URL from the link containing `/status/` and not ending in `/analytics`.
- Capture the visible post text from the first tweet text block.
- Capture author display text from the post header. It appears as line-delimited text like `Name`, `@username`, separator dot, and timestamp.
- Capture reply/comment count from the Reply button label, for example `132 Replies. Reply`.
- Capture like count from the Like button label, for example `1119 Likes. Like`.
- Capture views from the analytics link label, for example `91166 views. View post analytics`.
- Keep a set of canonical post URLs to deduplicate results.

Notes:
- Useful selectors in the browser DOM are `article[data-testid="tweet"]`, `[data-testid="tweetText"]`, `[data-testid="User-Name"]`, `[data-testid="reply"]`, `[data-testid="like"]`, and `a[href*="/analytics"]`.
- X may abbreviate visible numbers, but aria labels usually contain full integers.
- Very long post content may be truncated in the search timeline with a visible "Show more" affordance.

## Scroll And Stop

Intent: Continue collecting posts until the limit is reached or X stops loading new results.

- Scroll by roughly one viewport at a time.
- Wait briefly after each scroll for X to render more timeline items.
- Stop immediately if X shows its no-results empty state. Useful selectors are `[data-testid="empty_state_header_text"]` and `[data-testid="empty_state_body_text"]`; visible text includes `No results for ...` and `Try searching for something else...`.
- Do not stop after the first scroll that adds no new posts; exploration showed temporary stalls followed by more results.
- Stop when the requested limit is reached.
- If no new canonical URLs appear on a scroll, no `[role="progressbar"]` loader is present, and the main timeline has blank space after the last visible post, treat the search timeline as exhausted.
- Use 3 consecutive no-new-post scrolls only as a final fallback.
- Sort the collected posts by `likes` descending before returning them.

Notes:
- In the validated `uipath` last-24-hour run, the skill found 13 posts for a limit of 100 and stopped with the exhausted-timeline signal.
- The right rail/footer can keep the whole document taller after the main timeline is done, so whole-page bottom alone is not reliable.
