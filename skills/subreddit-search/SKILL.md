---
name: subreddit-search
description: Scrape top Reddit posts from a subreddit in Chrome, optionally filtered by a search query, and return title, URL, upvotes, comments, and body text.
---

# Subreddit Search

Scrapes a Reddit feed in the browser, collects post URLs, opens each post, and returns structured post data.

## Inputs
- `target_subreddit` (required, string): Subreddit name, with or without `r/`, such as `SaaS` or `r/LocalLLaMA`.
- `query` (optional, string): Search query. Leave blank to collect general top posts.
- `time_frame` (optional, enum): Exactly one of `hour`, `day`, `week`, `month`, `year`, `all`. Default is `month`.
- `post_count` (optional, integer): Number of posts to extract. Default is `10`.

## Run
Run via the executable bash script:

```bash
./run.sh [path/to/inputs.json]
```

Python runtime contract:
- `run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.
- This skill has no third-party Python package requirements, so it does not include `requirements.txt`.
- `$AI_MIME_BROWSER_HARNESS_BIN` must be set by AI Mime. The runner uses it to connect to Chrome and drive Reddit.
- Runtime does not create or repair a virtual environment.

## Outputs
The skill prints and logs:

```json
{
  "results": [
    {
      "title": "...",
      "url": "...",
      "upvotes": 0,
      "comments": 0,
      "body_text": "..."
    }
  ]
}
```

## Progress log format
The script outputs JSON log events on `stderr`:

```json
{"event":"step_start","id":"prepare_inputs","title":"Prepare Reddit scrape inputs"}
{"event":"step_done","id":"prepare_inputs","outputs":{"target_url":"...","post_count":10},"summary":"Prepared Reddit URL and limits"}
{"event":"step_start","id":"scrape_reddit","title":"Scrape Reddit posts in browser"}
{"event":"step_done","id":"scrape_reddit","outputs":{"result_count":10},"summary":"Extracted 10 posts"}
{"event":"workflow_done","outputs":{"results":[]}}
```

On failure, it emits:

```json
{"event":"step_failed","id":"scrape_reddit","error":"...","recoverable":false}
```

## Fallback
If `run.sh` fails, read [references/fallback_plan.md](references/fallback_plan.md). It contains the manual/browser fallback steps, target URL rules, and Reddit selectors used by the runner.

## ask_llm decision points
None.

## References
- [references/fallback_plan.md](references/fallback_plan.md): Manual and UI-agent fallback flow for collecting links and extracting post fields from Reddit.
