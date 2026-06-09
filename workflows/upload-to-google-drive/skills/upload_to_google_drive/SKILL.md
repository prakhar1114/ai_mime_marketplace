---
name: upload-to-google-drive
description: >-
  Create a new date-named folder inside the fixed "ai mime - binary" Google Drive
  folder and upload the local AI Mime.dmg build into it, using the user's already
  signed-in Chrome. Use this whenever the user wants to publish/upload the latest
  AI Mime build (the dist/AI Mime.dmg) to Google Drive, drop today's build into a
  fresh "v0 - <date>" Drive folder, or otherwise push the binary to the ai mime -
  binary Drive directory. No inputs are needed — everything is a baked-in constant.
---

# Upload to Google Drive

Creates a folder named `v0 - <today's date>` (e.g. `v0 - 31 May`) inside the fixed
Google Drive parent **ai mime - binary**, uploads the local build `AI Mime.dmg` into
it, and verifies the file landed. Runs against the user's existing signed-in Chrome
via the browser-harness (CDP) — no Google API credentials or OAuth setup required.

If a folder with today's name already exists under the parent, it appends ` - 2`,
` - 3`, … so re-running the same day never overwrites a prior upload.

## Inputs

This skill takes **no inputs**. All values are constants baked into `scripts/run.py`:

- Parent Drive folder: `1M1E4LNjEXLvaH7j5JY1Un3XRx6M6mtvV` (the "ai mime - binary" folder)
- Local file: `/Users/prakharjain/code/ai_mime/dist/AI Mime.dmg`
- Folder name: `v0 - <today's date>` formatted as `v0 - <day> <FullMonth>` with collision suffix `- N`

`inputs/inputs.example.json` and `inputs/inputs.template.json` are empty objects (`{}`),
present only for interface compatibility; the script ignores their contents.

## Run

```bash
./run.sh                              # uses inputs/inputs.example.json ({})
./run.sh /path/to/inputs.json         # inputs are ignored; any JSON works
# or directly:
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

Runtime contract:
- `run.sh` picks the first available interpreter in this order: skill `.venv/bin/python`,
  then workflow `.venv/bin/python` (`../../.venv/bin/python`), then the required
  `$AI_MIME_PYTHON_PATH`. Runtime never creates or repairs a `.venv`.
- No third-party Python packages are used (standard library only), so there is **no
  `requirements.txt`** and no virtualenv to build.
- Requires `$AI_MIME_BROWSER_HARNESS_BIN` and a running Chrome already signed in to
  Google Drive. The browser flow lives in `scripts/drive_flow.py`, executed via
  `"$AI_MIME_BROWSER_HARNESS_BIN" -c <code>`; parameters are passed through the
  `DRIVE_PARENT_ID`, `DRIVE_FILE_PATH`, and `DRIVE_BASE_NAME` environment variables.

## Outputs

On success, `scripts/run.py` emits a `workflow_done` event with:
- `folder_name` — the folder that was created, e.g. `v0 - 31 May`
- `new_folder_id` — the new Drive folder id
- `uploaded_file_id` — the uploaded file's Drive id
- `upload_verified` — `true` when the file is confirmed inside the folder
- `drive_folder_url` — direct link to the new folder

## Progress log format

Structured JSON events are written to stderr, one per line:
- `{"event":"step_start","id":"<step_id>","title":"…"}`
- `{"event":"step_done","id":"<step_id>","outputs":{…},"summary":"…"}`
- `{"event":"step_failed","id":"<step_id>","error":"…","recoverable":true|false}`
- `{"event":"workflow_done","outputs":{…}}`

Step ids: `create_folder_and_upload_via_drive_api`, then `verify_upload_complete`.
The process exits non-zero if any step fails.

## Fallback

If the automated run fails (e.g. Drive DOM changed, Chrome not signed in, page
context drift), follow `references/fallback_plan.md` to complete the task manually
or via the UI agent: open the parent folder, create the dated folder, and upload
`AI Mime.dmg` into it through Drive's New › File upload picker.

## ask_llm decision points

None. The whole flow is deterministic: the folder name is computed from the date,
collisions are resolved by incrementing a numeric suffix, and element targeting uses
stable DOM selectors (`guidedhelpid=new_menu_button`, `role=menuitem` text, dialog
input value, button text, and `aria-label` / `data-id` for folder/file rows).

## References

- `references/fallback_plan.md` — manual / UI-agent recovery steps with selectors,
  URLs, and traps learned during the build (tab-drift warning, file-chooser
  interception trick, folder-name parsing).
- `scripts/drive_flow.py` — the browser-harness flow (create folder, open it, upload
  via CDP file-chooser interception, wait, verify).
