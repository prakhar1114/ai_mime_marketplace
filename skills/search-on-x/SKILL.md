---
name: search-on-x
description: Search X for an exact query with since/until filters, scroll results through the browser harness, and return posts sorted by likes with author, engagement, URL, views, and content fields.
---

# Search On X

Use this skill when the user wants to search X/Twitter for an exact phrase or term with date filters and extract structured post data.

## Preconditions

- Chrome must be able to access X.
- If X requires authentication, the user must already be logged in to X in Chrome.

## Inputs

The skill reads a JSON object:

- `query`: required exact search term, for example `computer use`.
- `since`: optional lower date/datetime bound. Defaults to one day before `until` or today. Date format: `YYYY-MM-DD`; ISO datetime is accepted.
- `until`: optional upper date/datetime bound. Defaults to today. Date format: `YYYY-MM-DD`; ISO datetime is accepted.
- `limit`: optional maximum post count. Defaults to `100`; supports values up to `1000`. Small values like `10` are useful for validation.

## Run

Run with:

```bash
./run.sh inputs/inputs.example.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

No `requirements.txt` is needed for this skill. If one is added later for build or manual repair, install it with:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

Those install commands are for skill build or manual repair. Runtime does not create or repair `.venv`.

## Outputs

The script prints a JSON object to stdout with:

- `query`, `since`, `until`, `limit`
- `search_url`
- `count`
- `posts`: list sorted by `likes` descending

Each post contains:

- `name`
- `username`
- `likes`
- `comments`
- `views`
- `url`
- `content`

Content is the visible X search timeline content. Very long posts may be truncated by X with a visible "Show more" affordance.

## Progress log format

Progress is emitted to stderr as JSON lines:

```json
{"event":"step_start","id":"run_search","title":"Search X and extract posts"}
{"event":"step_done","id":"run_search","outputs":{"count":10,"search_url":"..."},"summary":"Extracted 10 posts"}
{"event":"workflow_done","outputs":{"count":10,"search_url":"..."}}
```

The browser harness also emits human-readable scroll progress to stderr, for example `scroll 4: collected 13/50`.

When fewer results are available than `limit`, the runner stops early in this order:

- immediately when X shows its no-results empty state;
- when the main search timeline is exhausted, with no loader and blank space after the last visible post;
- as a last fallback, after 3 consecutive scroll cycles add no new posts.

## Fallback

If the script fails, read `references/fallback_plan.md`. The fallback is to open the generated X search URL or X Advanced Search manually, use the Top tab, scroll the timeline, stop when X shows no results or the timeline is visibly exhausted, and extract fields from visible posts.

## ask_llm decision points

None. The skill uses deterministic browser-harness DOM extraction and numeric sorting.

## References

- `references/fallback_plan.md`: manual/UI-agent fallback steps, selectors, URL format, and extraction notes.
