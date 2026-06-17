# Fallback plan — record-expenses-to-google-sheets

Use this if `./run.sh` fails (e.g. Gemini unavailable, Chrome session lost, the sheet's column layout changed). A human or a `macos-computer-use` agent can finish the task from this file alone.

Target sheet: `https://docs.google.com/spreadsheets/d/1HZIQttKO_0cFmPOsC0Z64d75k1Bvrx0DqSHN2mfPiyw/edit?gid=0#gid=0` (constant inside `scripts/run.py`). Columns:

- A — `Idx` — next sequential integer after the largest existing Idx
- B — `Description` — short human-readable description from the receipt (include date / billing period if multiple receipts from the same merchant exist)
- C — `Cost` — final total paid (numeric, currency optional)
- D — `Invoice Number (if available)` — optional, leave blank

## Subtask 0 — Open the receipt so it is visible for review

Intent: get the receipt's content on screen so the fields below can be read.

- Open the expenses folder on the Desktop (double-click the blue `expenses` folder icon).
- Double-click each receipt file in turn. PDFs open in Preview; images open in Preview as well.

Notes from build:

- The expected receipts folder is `/Users/prakharjain/Desktop/expenses` by default.
- Supported file extensions: `.pdf .png .jpg .jpeg .heic .webp .tiff .gif`. Ignore `.DS_Store`.
- Process the files in alphabetical order so the resulting Idx ordering is reproducible.

## Subtask 1 — Extract fields from each receipt

Intent: capture `merchant`, `description`, `item_price`, and `total_paid` for each visible receipt.

- Read the receipt manually (or via OCR if doing it through a tool). For each receipt, record:
  - `merchant` — the business name printed at the top of the receipt.
  - `description` — what was purchased, in one short phrase. **Include the date or billing period** so two bills from the same merchant (e.g. April vs May SaaS invoices) are distinguishable in the sheet. Examples: `Small cappuccino at Black Point Cafe on 2025-11-01`, `Claude Pro subscription (May 16 – Jun 16, 2026)`.
  - `item_price` — the unit price of the primary line item (currency stripped).
  - `total_paid` — the final total actually paid by the user (currency stripped).

Notes from build:

- PDF receipts in the folder used to date had a clean text layer; `pdfplumber.extract_text()` was sufficient.
- HEIC images need conversion before any vision tool reads them: `sips -s format jpeg <in.heic> --out <out.jpg>`.
- The Gemini call uses a 4-field JSON schema (`merchant`, `description`, `item_price`, `total_paid`, all required, no nullable unions — Gemini rejects `"type":["string","null"]`). When doing this manually, write 0 / empty string for unknowns rather than leaving fields out.

## Subtask 2 — Open the Expenses Google Sheet

Intent: get the destination sheet on screen, ready for data entry, in a Chrome window the user is already signed in to.

- Launch Google Chrome (Spotlight → "chrome" → Enter, or click the dock icon).
- Open a new tab.
- Navigate to the sheet URL above. (The recording used a bookmark on the bookmarks bar labelled `Expenses - Googl...`; either works.)

Notes from build:

- The user must already be signed into the Google account that owns the sheet. The skill does not log in.
- Once the sheet is in a Chrome tab, the page's own origin can fetch CSV via `/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&gid=0` with `credentials:"include"`. Useful for inspecting current contents programmatically.

## Subtask 3 — Append one row per receipt at the bottom

Intent: write Idx / Description / Cost for each extracted receipt as new rows at the bottom of the sheet.

- Read column A to find the largest existing Idx. The next Idx for the first new receipt is that value + 1; subsequent receipts get consecutive integers.
- Click the first empty cell in column A.
- Type the Idx, press Tab, type the Description, press Tab, type the Cost, press Enter. Repeat for each receipt.

Notes / traps from build:

- **`type_text` (CDP `Input.insertText`) does NOT work** inside a Google Sheets cell — the cell isn't a real input. Pressing F2 first does not help.
- **`press_key` char-by-char** does enter the cell (auto-edit) but characters are reordered/duplicated (e.g. typing `test` produces `eestt`). Unreliable for any string longer than a single char.
- **`Cmd+V`** via `press_key("v", modifiers=4)` does NOT trigger Sheets paste from the OS clipboard. Likely the CDP-synthesized keystroke is missing the user-gesture flag for clipboard access.
- **Working approach** (used by `scripts/run.py`): dispatch a synthetic `ClipboardEvent("paste")` carrying a `DataTransfer` with **only** `text/plain` set to a tab-separated value (TSV) string. Rows separated by `\n`, fields by `\t`. Sheets accepts the paste and splits across cells. **Do not** also set `text/html` — Sheets prefers HTML and collapses tabs/newlines into a single-cell string.
- Append target row = `1 + (count of non-empty data rows)`. Header is always row 1.
- For multiple new rows, paste a multi-line TSV at A`<next_row>` — Sheets fills the rectangle downward in one operation.
- Verify by re-reading the gviz CSV; cost cells may come back as `$23.60` even when you wrote `23.6` — compare numerically (strip non-`[0-9.\-]`), don't compare strings.

## If the sheet's column layout changes

- If column headers (`Idx`, `Description`, `Cost`, `Invoice Number (if available)`) move, update the column mapping in `append_rows` and in this fallback. The skill assumes the first three data columns are exactly Idx, Description, Cost.
