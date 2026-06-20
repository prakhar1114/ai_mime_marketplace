# Fallback Plan

Use this if `run.sh` fails or Reddit changes enough that the automated selectors need repair.

## Subtask 1: Determine Target URL
Intent: Build the Reddit URL from the user inputs.

- Normalize `target_subreddit` by removing leading/trailing spaces, a leading `r/`, and any trailing slash.
- Use `time_frame` exactly as provided; valid values are `hour`, `day`, `week`, `month`, `year`, `all`.
- If `query` is blank, open:
  - `https://www.reddit.com/r/{target_subreddit}/top/?t={time_frame}`
- If `query` has text, URL-encode it and open:
  - `https://www.reddit.com/r/{target_subreddit}/search/?q={query}&restrict_sr=1&sort=top&t={time_frame}`

Notes:
- The confirmed validation URL was `https://www.reddit.com/r/AiAutomations/top/?t=month`.
- Reddit may need a few seconds after normal page load before feed posts hydrate.

## Subtask 2: Harvest Post URLs
Intent: Collect the first `post_count` direct post URLs from the feed.

- Open the target URL in Chrome.
- Wait for the main feed to render.
- Collect links from Reddit feed posts in display order.
- Scroll the feed if fewer than `post_count` links are visible.
- Stop when `post_count` unique `/r/{subreddit}/comments/.../` URLs are collected, or when the feed has no more available posts.

Notes:
- Stable feed container/item selector: `shreddit-post`.
- Useful attributes on `shreddit-post`: `permalink`, `content-href`.
- Useful nested links: `a[slot=full-post-link]`, `a[slot=title]`, `a[href*="/comments/"]`.
- Normalize collected links by removing query strings and hash fragments.

## Subtask 3: Extract Each Post
Intent: Visit each harvested post URL and extract title, URL, upvotes, comments, and body text.

- Open each post URL in the same browser tab.
- Wait for the page to load and then wait about 2 seconds for Reddit's web components to hydrate.
- Extract:
  - `title`: main `h1` text in `shreddit-post`, falling back to `[slot=title]` or `post-title`.
  - `url`: the harvested direct post URL.
  - `upvotes`: `score` attribute on `shreddit-post`, falling back to `faceplate-number[number]`.
  - `comments`: `comment-count` attribute on `shreddit-post`, falling back to visible/ARIA text containing "comment".
  - `body_text`: paragraph text under `[slot=text-body] .md` or `[slot=text-body]`.
- If no body paragraphs/text exist, return `[Media/Link Post]`.
- Append one object per post to `results`.

Notes:
- Reddit's current desktop UI uses stable custom elements: `shreddit-post` and `faceplate-number`.
- Score and comment values may be abbreviated in visible text, such as `1.2k`; parse `k` and `m` suffixes if reading visible text.
- If Reddit shows a login, NSFW, private subreddit, or quarantine gate, the public browser flow may not be able to extract posts without the user's logged-in browser session already being permitted to view that content.
