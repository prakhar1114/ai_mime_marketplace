---
name: facebook-data-extractor
description: Extract visible posts from a Facebook group for the last N days using the AI Mime browser harness and an existing logged-in Facebook Chrome session.
---

# Facebook Data Extractor

## Preconditions

- Chrome must already be logged in to Facebook.
- The logged-in Facebook account must already be able to view the target group.
- The automation is read-only: it does not post, like, comment, join groups, or send messages.

## Inputs

Provide a JSON file with:

- `group_url`: Facebook group URL, for example `https://www.facebook.com/groups/1279620962532340`
- `days`: Number of days back from the run time to include.
- `max_scrolls` optional: Maximum scroll batches, from 5 to 500. Omit for the default. Larger values improve coverage in busy groups but make runs slower.
- `max_hydration_pages` optional: Maximum number of truncated posts to hydrate in individual tabs, from 0 to 100. Defaults to 5 to save time.

## Run

Run with:

```bash
./run.sh inputs/inputs.example.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

This skill has no third-party Python dependencies. If a future version adds `requirements.txt`, use these commands during skill build or manual repair only:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

Runtime does not create or repair `.venv`.

## Outputs

The skill writes a JSON file under the workflow output directory. Each post includes:

- `author`
- `timestamp_text`
- `timestamp_iso`
- `post_url`
- `text`
- `visible_engagement`

The top-level output also includes `group_url`, `days`, `cutoff_iso`, `extracted_at`, `post_count`, and diagnostics.

Important diagnostics:

- `coverage_complete`: true only when the run saw posts older than the requested cutoff.
- `hit_max_scrolls`: true when Facebook did not serve enough older feed content before the scroll ceiling.
- `expanded_see_more`: number of loaded `See more` controls clicked before extraction.
- `hydrated_truncated_posts`: number of truncated posts repaired by opening their post URL.
- `truncated_text_posts`: number of output posts whose text still ended with Facebook's truncation ellipsis.

## Progress log format

Progress events are emitted to stderr as JSON lines:

- `{"event":"step_start","id":"...","title":"..."}`
- `{"event":"step_done","id":"...","outputs":{...},"summary":"..."}`
- `{"event":"step_failed","id":"...","error":"...","recoverable":true|false}`
- `{"event":"workflow_done","outputs":{...}}`

The final stdout line is a JSON object containing `output_path` and `post_count`.

## Fallback

If automation fails, read `references/fallback_plan.md`. It contains manual/browser-harness recovery steps, selectors, timestamp reconstruction notes, and access-wall handling.

## ask_llm decision points

None. This skill does not call `ask_llm`.

## References

- `references/fallback_plan.md`
