# Fallback Plan

## Open The Group

Intent: Load the target Facebook group in chronological order using the existing logged-in Chrome session.

- Open `https://www.facebook.com/groups/{group_id}/?sorting_setting=CHRONOLOGICAL`.
- Wait at least 8-10 seconds for the feed to hydrate.
- If Facebook redirects to `/login` or `/checkpoint`, stop and ask the user to log in or resolve the checkpoint manually.
- If the page says the content is unavailable, the logged-in account does not have access to the group.

Notes:
- The chronological query is important; the default feed may show algorithmic or repeated popular posts.
- Do not click Join, Like, Comment, Share, or any write action.

## Collect Visible Posts

Intent: Extract the post details currently mounted in the feed before scrolling.

- Click loaded `See more` controls before reading body text. Use visible elements with role `button` or `link` and exact text `See more`.
- When clicking offscreen loaded controls, restore the previous scroll position afterward so the feed collection continues downward.
- Query post containers with `div[role="article"]`.
- Query post bodies with `div[data-ad-preview="message"], div[data-ad-comet-preview="message"]`.
- If body selectors are missing, use article text and take the text after the final `·`, then remove `See more`, `Like`, `Comment`, `Share`, and `Write a public comment`.
- Prefer author links matching `/groups/{group_id}/user/` and use their `aria-label` or text.
- Prefer direct post links matching `/groups/` plus `/posts/` or `/permalink/`.
- If no direct post link is present, find photo links containing `set=pcb.<post_id>` and construct `https://www.facebook.com/groups/{group_id}/posts/<post_id>/`.

Notes:
- Facebook virtualizes the feed. Collect first, then scroll. Scrolled-past posts may be removed from the DOM.
- Some posts contain multiple photo links; use the same `pcb.<post_id>` value for the post URL.
- If output post text ends with `…`, the post probably was not fully expanded.
- For truncated posts with a `post_url`, open the post permalink, click `See more`, and re-read the longest message body.

## Reconstruct Timestamps

Intent: Recover relative timestamps such as `42m`, `1h`, or `2d` when Facebook scrambles timestamp text.

- Inspect small visible timestamp links near the author line.
- The link `innerText` may contain decoy characters.
- Reconstruct the real timestamp from leaf `span` elements inside the link whose bounding boxes intersect the link's visible bounding box.
- Sort those visible characters by `y` then `x` and concatenate them.
- Parse relative values:
  - `m`, `min`, `minute` as minutes
  - `h`, `hr`, `hour` as hours
  - `d`, `day` as days
  - `w`, `week` as weeks
  - `yesterday` as one day ago

Notes:
- Verified live examples reconstructed `40m`, `42m`, and `1h`.
- If no timestamp can be reconstructed, skip that post for date-window filtering.

## Scroll And Stop

Intent: Continue collecting posts until the requested date window is covered.

- After collecting visible posts, scroll near the center of the viewport by about 900 pixels.
- Wait at least 2.5 seconds after each scroll.
- Deduplicate posts by post URL when available; otherwise use a text prefix key.
- Stop when enough posts older than the cutoff are found, when no new unique posts appear across repeated scrolls, or after a bounded maximum scroll count.
- Treat the run as complete only if diagnostics show `coverage_complete: true`. If `hit_max_scrolls` is true, Facebook stopped serving enough older posts before the requested date window was exhausted.

Notes:
- Pacing matters. Faster scrolling can cause empty hydrated containers or account checkpoint prompts.
- If Facebook starts showing empty post containers or a checkpoint, stop immediately.
- High-volume groups may require hundreds of scroll batches to cover even two days.

## Write Output

Intent: Save all matching posts in a structured file.

- Write JSON with `group_url`, `days`, `cutoff_iso`, `extracted_at`, `post_count`, `diagnostics`, and `posts`.
- Each post should include `author`, `timestamp_text`, `timestamp_iso`, `post_url`, `text`, and visible engagement if available.
- Include diagnostics for `coverage_complete`, `hit_max_scrolls`, `expanded_see_more`, `hydrated_truncated_posts`, and `truncated_text_posts`.

Notes:
- Reruns are safe; they only create or overwrite local output JSON files.
