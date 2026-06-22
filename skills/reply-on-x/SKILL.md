---
name: reply-on-x
description: Reply to an X post or comment from the user's already logged-in Chrome session using browser-harness, and return the posted reply URL. Use when the user gives an x.com status link and reply text and wants the reply posted.
---

# Reply on X

## Preconditions
- The user must already be signed in to X in the Chrome session controlled by browser-harness.
- The target X post/comment must be replyable.
- Running this skill posts a real public reply. Reruns are not idempotent, and X may block repeated duplicate reply text.

## Inputs
- `post_url`: X status URL containing `/status/<id>`.
- `reply_text`: Text to post as the reply.

## Run
Use:

```bash
./run.sh /path/to/inputs.json
```

If no path is provided, `run.sh` uses `inputs/inputs.example.json`.

`run.sh` uses the first available Python interpreter in this order:
1. Skill `.venv/bin/python`
2. Workflow `.venv/bin/python`
3. Required `$AI_MIME_PYTHON_PATH`

This skill has no third-party Python package requirements. If `requirements.txt` is added later, install or repair dependencies during skill build or manual repair with:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

Runtime does not create or repair `.venv`.

## Outputs
- `reply_url`: URL of the newly posted X reply.

The script also prints the final output JSON to stdout.

## Progress log format
Structured progress events are emitted to stderr:

```json
{"event":"step_start","id":"load_inputs","title":"Load inputs"}
{"event":"step_done","id":"post_reply","outputs":{"reply_url":"https://x.com/.../status/..."},"summary":"Reply posted"}
{"event":"workflow_done","outputs":{"reply_url":"https://x.com/.../status/..."}}
```

Failures emit:

```json
{"event":"step_failed","id":"post_reply","error":"...","recoverable":true}
```

## Fallback
If `run.sh` fails, read `references/fallback_plan.md`. The main manual fallback is to open the supplied X status URL in logged-in Chrome, scroll the inline reply composer into view, enter `reply_text`, submit with Cmd+Return or the Reply button, then copy the URL from the newly posted reply.

## ask_llm decision points
None. The skill does not call `ask_llm`.

## References
- `references/fallback_plan.md`: manual/UI-agent recovery flow, selectors, and edge cases learned during validation.
