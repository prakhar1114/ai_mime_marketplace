---
name: record-expenses-to-google-sheets
description: Read every receipt file (PDFs and images) from a local folder, extract merchant/description/total via PDF text parsing + Gemini, and append one row per receipt to a fixed Expenses Google Sheet (Idx / Description / Cost) at the bottom. Never deduplicates — every run appends every receipt currently in the folder.
---

# record-expenses-to-google-sheets

End-to-end automation that turns a folder of receipts into rows in a Google Sheet.

The target sheet URL is hardcoded inside `scripts/run.py` as `EXPENSES_SHEET_URL` (constant, not an input). The user's Chrome must already be signed into the Google account that owns the sheet — the skill drives that Chrome via the `browser` skill / `browser-harness`. No OAuth or API key needed.

## Inputs

`scripts/run.py --inputs-json <file>` expects JSON like:

```json
{ "receipts_folder_path": "/Users/prakharjain/Desktop/expenses" }
```

- `receipts_folder_path` (string, required): absolute path to the folder containing receipts. Every file directly in the folder with one of these extensions is processed (case-insensitive): `.pdf .png .jpg .jpeg .heic .webp .tiff .gif`. Subfolders and `.DS_Store` are ignored.

## Run

```bash
./run.sh                          # uses inputs/inputs.example.json
./run.sh inputs/inputs.template.json
./run.sh /abs/path/to/inputs.json
```

`run.sh` is self-bootstrapping: on first run it creates a virtual env at
`.venv/` (next to `run.sh`) and installs `requirements.txt` (just
`pdfplumber`) into it, then runs `scripts/run.py` with that interpreter. On
later runs it reuses the venv, only reinstalling if `pdfplumber` is missing.
The venv is gitignored — delete `.venv/` to force a clean rebuild. `python3`
must be on `$PATH` to create the venv.

Per-receipt pipeline:

1. **Enumerate** — `os.listdir` the folder, filter by extension, sort, absolute paths.
2. **Extract** —
   - PDFs: `pdfplumber.extract_text()` per page, joined; the text is sent to Gemini with a JSON schema.
   - HEIC images: converted to JPG via macOS-native `sips -s format jpeg <in> --out <tmp.jpg>` (Gemini rejects `.heic` directly). Other image types go to Gemini as-is.
   - Gemini is reached by shelling out to `browser-harness -c '<python>'` and importing `ask_llm` from `browser_harness.helpers` (so the host Python doesn't need any vision deps). The structured response is `{merchant, description, item_price, total_paid}`.
3. **Append** — opens `EXPENSES_SHEET_URL` in a new Chrome tab, reads the existing sheet via `fetch("/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&gid=0", {credentials:"include"})` from the page's own origin (cookies authenticate), computes `next_idx = max(existing Idx values) + 1` and `next_row = last non-empty row + 1`. It then jumps to A`next_row` by clicking the Name Box and typing the address, and dispatches a synthetic `ClipboardEvent("paste")` carrying a TSV string in `text/plain` only (`text/html` collapses tabs → must be omitted). Sheets accepts the paste and writes Idx / Description / Cost across the new rows.

Re-runs always append — the skill does NOT deduplicate. Two runs against the same folder produce two sets of rows. To get distinct descriptions for receipts of the same product across billing periods, the Gemini prompt asks for the date or billing period in the description (e.g. `Claude Pro subscription (May 16 - Jun 16, 2026)`).

External tools required at run time:

- `python3` on `$PATH` to create the `.venv`. `pdfplumber` is installed automatically into `.venv/` from `requirements.txt` by `run.sh` (no manual `pip install` needed). If you invoke `scripts/run.py` directly instead of via `run.sh`, use `.venv/bin/python` or otherwise ensure `pdfplumber` is importable.
- `browser-harness` on `$PATH` (used both for Gemini calls and for driving Chrome). Install with `uv tool install -e /path/to/browser-harness` if not already present. Its dependencies are intentionally NOT in `requirements.txt` — it runs as a separate subprocess with its own environment.
- `sips` (macOS-built-in; required only when the folder contains `.heic` files).
- A Chrome window the user is already signed into the target Google account in. The skill connects via CDP; it does not log in for the user.

## Outputs

- Side effect: new rows appended to the Expenses Google Sheet (Idx / Description / Cost). The skill writes nothing to local disk besides progress logs on stderr.
- Programmatic result: the last `workflow_done` event on stderr carries `outputs.appended_rows` — one object per appended row with `idx`, `description`, `cost`, `source_file`.

## Progress log format

Every step transition is one JSON object per line on stderr:

- `{"event":"step_start","id":"<step_id>","title":"…"}`
- `{"event":"step_done","id":"<step_id>","outputs":{…},"summary":"…"}`
- `{"event":"step_failed","id":"<step_id>","error":"…","recoverable":true|false}` (process exits non-zero immediately after)
- `{"event":"workflow_done","outputs":{…}}`

Free-form `print` lines may be interleaved.

Step IDs in order: `enumerate_receipt_files`, `extract_receipt_fields`, `append_expense_rows_in_sheet`.

## Fallback

See `references/fallback_plan.md`. If `scripts/run.py` fails, the recorded UI flow (open Finder → open PDF in Preview → launch Chrome via Spotlight → open the bookmarked sheet → type Idx / Description / Cost) is enough for a human or `macos-computer-use` agent to finish the task.

Common automated failure modes and their handling:

- **Gemini schema rejection** — Gemini rejects nullable union types (`"type":["string","null"]`). The script uses non-nullable types and instructs the model to emit `0` / `""` instead. If schemas are tightened later, keep this constraint.
- **PDF without a text layer** — `pdfplumber.extract_text()` returns `""`. Currently the prompt still goes to Gemini with empty text and Gemini will guess; that's the wrong behavior. Future improvement: detect empty text and route the PDF through `pdftoppm` → JPG → image prompt instead.
- **Chrome not signed in / wrong account** — the `fetch` to gviz returns a Google login HTML page rather than CSV. The script will treat it as a parse failure. Fallback: ask the user to sign into Chrome with the right account; then re-run.
- **`browser-harness` not on PATH** — `subprocess.run(["browser-harness", ...])` raises `FileNotFoundError`. Install per the Run section above.

## ask_llm decision points

The skill makes exactly one Gemini call per receipt, in `extract_record()`:

- For PDFs: prompt is `GEMINI_TEXT_PROMPT + <extracted text>`, no image.
- For images: prompt is `GEMINI_IMAGE_PROMPT`, with the image file path (HEIC → JPG via `sips` first).

In both cases the JSON schema is:

```json
{
  "type": "object",
  "properties": {
    "merchant":      {"type": "string"},
    "description":   {"type": "string"},
    "item_price":    {"type": "number"},
    "total_paid":    {"type": "number"}
  },
  "required": ["merchant", "description", "item_price", "total_paid"]
}
```

The prompt explicitly requests that `description` include the date or billing period when present so that successive bills from the same merchant are distinguishable in the sheet.


## References

- `references/fallback_plan.md` — full human / `macos-computer-use` fallback playbook.
- `EXPENSES_SHEET_URL` and `SHEET_ID` constants in `scripts/run.py` — the only sheet-specific configuration. Replace both to point at a different sheet.
