---
name: linkedin-search-people
description: Search LinkedIn people results in the user's already logged-in Chrome browser and return structured profile-card data. Use when asked to find people on LinkedIn by keywords, title, company, location, connection degree, or page without sending messages, connection requests, or modifying account data.
---

# LinkedIn People Search

## Preconditions
LinkedIn must already be signed in in the user's Chrome browser. The skill is read-only and does not send messages, connect, follow, or edit profile/account data.

## Inputs
Read inputs from JSON:
- `keywords`: optional string; may be omitted or left empty.
- `title`: optional string; may be omitted or left empty.
- `company`: optional string; may be omitted or left empty.
- `location`: optional string; may be omitted or left empty.
- `connection_degree`: optional array of checkbox selections from `1st`, `2nd`, `3rd`. Leave all unchecked (empty array) to search all three degrees.
- `page`: optional integer; defaults to `1`.
- `close_tab_after`: optional boolean; defaults to `true`. When enabled, the newly opened LinkedIn search tab is closed after results are read. Set to `false` to leave the tab open.

The runner joins `keywords`, `title`, `company`, and `location` into LinkedIn's `keywords` URL parameter, maps connection degrees to LinkedIn's `network` values, and opens `/search/results/people/`.

## Run
Run with:

```bash
./run.sh inputs/inputs.example.json
```

Or invoke the script directly:

```bash
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

`run.sh` uses the first available interpreter in this order: skill `.venv/bin/python`, workflow `.venv/bin/python`, then required `$AI_MIME_PYTHON_PATH`.

No third-party Python packages are required. If a future edit adds `requirements.txt`, use these commands only during skill build or manual repair:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

Runtime does not create or repair `.venv`.

## Outputs
The final stdout line is a single JSON object:

```json
{"event":"workflow_done","outputs":{"results":[],"page":1,"has_next_page":false}}
```

Each `results` item contains:
- `name`
- `headline`
- `location`
- `profile_url`
- `degree`
- `current_company`
- `pending` — boolean. `true` when a connection request has already been sent to this person and is awaiting a response (LinkedIn shows a "Pending" action on the card). When `true`, there is no point sending another connection request.
- `connection_status` — one of `pending` (request already sent), `can_connect` (a "Connect" action is available, so a request can be sent), `connected` (already connected/following; only "Message"/"Following" is shown), or `unknown` (no recognizable action line was visible).

## Progress logs
Progress logs are written to stderr in clear, short, natural language suitable for an end-user overlay, such as "Preparing LinkedIn search...", "Opening LinkedIn people search...", and "Reading visible people results...".

## Fallback
Read [references/fallback_plan.md](references/fallback_plan.md) if browser automation fails, LinkedIn changes its DOM, or the user needs manual recovery steps.

## ask_llm decision points
None. The skill uses deterministic URL construction and DOM extraction.

## References
- [references/fallback_plan.md](references/fallback_plan.md)
