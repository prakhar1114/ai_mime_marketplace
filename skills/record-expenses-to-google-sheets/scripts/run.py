#!/usr/bin/env python3
"""record-expenses-to-google-sheets — end-to-end runner.

Reads every supported receipt file from a folder, parses it into a
structured expense record, and appends one new row per *pending* receipt to a
fixed Google Sheets expense tracker (next sequential Idx, Description, Cost).

Invocation:
    python scripts/run.py --inputs-json /path/to/inputs.json

inputs.json:
    { "receipts_folder_path": "/abs/path/to/folder" }

Progress events are emitted as JSON lines on stderr (see SKILL.md
'## Progress log format').
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

EXPENSES_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1HZIQttKO_0cFmPOsC0Z64d75k1Bvrx0DqSHN2mfPiyw/edit?gid=0#gid=0"
)
SHEET_ID = "1HZIQttKO_0cFmPOsC0Z64d75k1Bvrx0DqSHN2mfPiyw"
SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff", ".gif"}
IMAGE_EXTS = SUPPORTED_EXTS - {".pdf"}


# ---- progress log ----------------------------------------------------------

def event(kind: str, **fields: Any) -> None:
    rec = {"event": kind, **fields}
    sys.stderr.write(json.dumps(rec) + "\n")
    sys.stderr.flush()


def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


# ---- step 1: enumerate -----------------------------------------------------

def enumerate_receipts(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        raise RuntimeError(f"receipts_folder_path does not exist or is not a folder: {folder}")
    out: list[str] = []
    for name in os.listdir(folder):
        ext = os.path.splitext(name)[1].lower()
        if ext in SUPPORTED_EXTS:
            out.append(os.path.join(folder, name))
    return sorted(out)


# ---- step 2: extract structured fields -------------------------------------

GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "description": {"type": "string"},
        "item_price": {"type": "number"},
        "total_paid": {"type": "number"},
    },
    "required": ["merchant", "description", "item_price", "total_paid"],
}

_DESC_GUIDANCE = (
    "description: a human-readable description suitable for an expenses sheet "
    "Description column. Make it specific enough that two receipts from the "
    "same merchant for the same product can be told apart at a glance — "
    "include the date or billing period when present (e.g. "
    "'Claude Pro subscription (April 2025)', "
    "'Uber rideshare Mountain View → SFO on 2025-11-01', "
    "'Small cappuccino at Black Point Cafe on 2025-11-01'). Keep it to one "
    "short line."
)

GEMINI_TEXT_PROMPT = (
    "Following is extracted text from a receipt. Extract: merchant; "
    f"{_DESC_GUIDANCE} item_price (primary line item; number, currency "
    "stripped; 0 if N/A); total_paid (final total actually paid by the user; "
    "number, currency stripped).\n\nReceipt text:\n"
)

GEMINI_IMAGE_PROMPT = (
    "This is a receipt image. Extract: merchant; "
    f"{_DESC_GUIDANCE} item_price (primary line item; number, currency "
    "stripped; 0 if N/A); total_paid (final total actually paid by the user; "
    "number, currency stripped)."
)


def _ask_llm_subprocess(prompt: str, image_path: str | None) -> dict:
    """Shell out to AI_MIME_BROWSER_HARNESS_BIN/browser-harness for ask_llm."""
    code = (
        "import json, sys\n"
        "from browser_harness.helpers import ask_llm\n"
        f"prompt = {json.dumps(prompt)}\n"
        f"schema = {json.dumps(GEMINI_SCHEMA)}\n"
        f"images = {json.dumps([image_path]) if image_path else 'None'}\n"
        "out = ask_llm(prompt, schema, images=images)\n"
        "sys.stdout.write(json.dumps(out))\n"
    )
    res = subprocess.run(
        [_browser_harness_bin(), "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"AI_MIME_BROWSER_HARNESS_BIN/browser-harness ask_llm failed (rc={res.returncode}): "
            f"{res.stderr.strip()[-2000:]}"
        )
    return json.loads(res.stdout.strip().splitlines()[-1])


def _browser_harness_bin() -> str:
    value = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not value:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is not configured")
    return value


def _pdf_text(path: str) -> str:
    import pdfplumber  # local import; declared as a script dep below
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            pages.append(pg.extract_text() or "")
    return "\n".join(pages)


def _heic_to_jpg(path: str) -> str:
    """ask_llm doesn't accept .heic; convert via macOS-native sips."""
    if not shutil.which("sips"):
        raise RuntimeError(
            "Cannot process .heic without macOS `sips` (not found on PATH)."
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    res = subprocess.run(
        ["sips", "-s", "format", "jpeg", path, "--out", tmp.name],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"sips failed: {res.stderr.strip()}")
    return tmp.name


def extract_record(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = _pdf_text(path)
        out = _ask_llm_subprocess(GEMINI_TEXT_PROMPT + text, image_path=None)
    elif ext in IMAGE_EXTS:
        img_path = _heic_to_jpg(path) if ext == ".heic" else path
        try:
            out = _ask_llm_subprocess(GEMINI_IMAGE_PROMPT, image_path=img_path)
        finally:
            if ext == ".heic":
                try:
                    os.unlink(img_path)
                except OSError:
                    pass
    else:
        raise RuntimeError(f"unsupported extension: {ext}")
    out["source_file"] = path
    return out


# ---- step 3: read sheet + append ------------------------------------------

def _bh_run(code: str, timeout: float = 60.0) -> str:
    """Run a snippet inside AI_MIME_BROWSER_HARNESS_BIN/browser-harness."""
    res = subprocess.run(
        [_browser_harness_bin(), "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"AI_MIME_BROWSER_HARNESS_BIN/browser-harness failed (rc={res.returncode}): "
            f"{res.stderr.strip()[-2000:]}"
        )
    return res.stdout


def _parse_csv(csv_text: str) -> list[list[str]]:
    import csv
    import io
    return list(csv.reader(io.StringIO(csv_text)))


def fetch_sheet_csv() -> list[list[str]]:
    """Open the sheet edit URL, then fetch the gviz CSV from the page's own
    origin (so the user's Google session cookies authenticate the request).
    """
    code = f"""
import json, time
new_tab({json.dumps(EXPENSES_SHEET_URL)})
wait_for_load()
time.sleep(1.5)
csv = js(\"\"\"(async () => {{
  const r = await fetch("/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&gid=0", {{credentials:"include"}});
  return await r.text();
}})()\"\"\")
print(json.dumps({{"csv": csv}}))
"""
    stdout = _bh_run(code, timeout=60)
    payload = None
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and "csv" in payload:
                break
        except json.JSONDecodeError:
            continue
    if not payload:
        raise RuntimeError(f"could not read sheet csv; raw: {stdout[-500:]}")
    return _parse_csv(payload["csv"])


def next_idx_and_row(sheet_rows: list[list[str]]) -> tuple[int, int]:
    """Returns (next_idx, next_row_1based). Header is row 1.

    next_idx = max numeric Idx in column A across data rows + 1 (1 if none).
    next_row = 1 + count(data rows in sheet) + 1 = first empty row 1-based.
    """
    data_rows = sheet_rows[1:]  # drop header
    max_idx = 0
    last_nonempty_row = 1  # header
    for i, row in enumerate(data_rows, start=2):  # row 2 is first data row
        if not row or all((c or "").strip() == "" for c in row):
            continue
        last_nonempty_row = i
        a = (row[0] if row else "").strip()
        if a.isdigit():
            v = int(a)
            if v > max_idx:
                max_idx = v
    return max_idx + 1, last_nonempty_row + 1


def select_records_to_append(records: list[dict]) -> list[dict]:
    """No deduplication: one sheet row per receipt file. Skip only records
    whose description is empty (Gemini failure)."""
    return [r for r in records if (r.get("description") or "").strip()]


def append_rows(records: list[dict], next_idx: int, next_row: int) -> dict:
    """Paste records as a TSV block into A<next_row> via a synthetic
    ClipboardEvent('paste') with text/plain. Requires the sheet edit URL to
    already be open in the active tab (fetch_sheet_csv leaves it that way)."""
    appended: list[dict] = []
    tsv_lines: list[str] = []
    for offset, r in enumerate(records):
        idx = next_idx + offset
        desc = (r.get("description") or "").replace("\t", " ").replace("\n", " ")
        cost = r.get("total_paid")
        if cost is None:
            cost = r.get("item_price") or 0
        tsv_lines.append(f"{idx}\t{desc}\t{cost}")
        appended.append({"idx": idx, "description": desc, "cost": cost,
                         "source_file": r.get("source_file")})
    tsv = "\n".join(tsv_lines)

    # Build the browser-harness script. We intentionally do NOT embed `tsv`
    # via an outer f-string into a Python triple-quoted string passed to
    # js(...) — Python would consume the \t / \n escapes and JS would see
    # raw whitespace inside the string literal (syntax error). Instead, we
    # pass `tsv` as a Python local to the inner script and let json.dumps
    # build a proper JS string literal there at runtime, concatenated into
    # the JS source as a single token.
    code = (
        "import json, time\n"
        f"click_at_xy(50, 125)\n"
        "time.sleep(0.4)\n"
        f"type_text({json.dumps(f'A{next_row}')})\n"
        'press_key("Enter")\n'
        "time.sleep(0.6)\n"
        f"tsv = {json.dumps(tsv)}\n"
        "js_src = ("
        "  '(() => { '"
        "  '  const text = ' + json.dumps(tsv) + ';'"
        "  '  const dt = new DataTransfer();'"
        "  '  dt.setData(\"text/plain\", text);'"
        "  '  const target = document.activeElement || document.body;'"
        "  '  const ev = new ClipboardEvent(\"paste\", { clipboardData: dt, bubbles: true, cancelable: true });'"
        "  '  target.dispatchEvent(ev);'"
        "  '  return target.tagName + \" \" + (target.className||\"\");'"
        "  '})()'"
        ")\n"
        "ok = js(js_src)\n"
        "time.sleep(1.8)\n"
        f'csv = js(\'(async () => {{ const r = await fetch("/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&gid=0", {{credentials:"include"}}); return await r.text(); }})()\')\n'
        'print(json.dumps({"target": ok, "csv": csv}))\n'
    )
    stdout = _bh_run(code, timeout=90)
    payload = None
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "csv" in obj:
                payload = obj
                break
        except json.JSONDecodeError:
            continue
    if not payload:
        raise RuntimeError(f"could not verify paste; raw: {stdout[-500:]}")
    rows = _parse_csv(payload["csv"])
    # Confirm each expected row landed.
    by_idx = {r[0]: r for r in rows[1:] if r}
    for a in appended:
        rec = by_idx.get(str(a["idx"]))
        if not rec or len(rec) < 3:
            raise RuntimeError(f"row idx={a['idx']} not found after paste")
        # Cost in the cell may be currency-formatted; compare numeric.
        cell_cost = re.sub(r"[^0-9.\-]", "", rec[2] or "")
        try:
            if abs(float(cell_cost) - float(a["cost"])) > 0.01:
                raise RuntimeError(
                    f"row idx={a['idx']} cost mismatch: got {rec[2]!r} expected {a['cost']!r}"
                )
        except ValueError:
            raise RuntimeError(f"row idx={a['idx']} non-numeric cost: {rec[2]!r}")
    return {"rows_appended": len(appended), "appended_rows": appended}


# ---- main ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs-json", required=True)
    args = ap.parse_args()

    inputs = json.loads(Path(args.inputs_json).read_text())
    folder = inputs.get("receipts_folder_path") or "/Users/prakharjain/Desktop/expenses"

    # Step 1
    event("step_start", id="enumerate_receipt_files", title="List receipt files in the expenses folder")
    try:
        paths = enumerate_receipts(folder)
    except Exception as e:
        event("step_failed", id="enumerate_receipt_files", error=str(e), recoverable=False)
        return 2
    event("step_done", id="enumerate_receipt_files",
          outputs={"receipt_file_paths": paths},
          summary=f"found {len(paths)} receipt file(s)")
    if not paths:
        event("workflow_done", outputs={"rows_appended": 0, "appended_rows": []})
        return 0

    # Step 2
    event("step_start", id="extract_receipt_fields",
          title="Parse each receipt file into structured expense fields")
    records: list[dict] = []
    for p in paths:
        log(f"  extracting {os.path.basename(p)}")
        try:
            records.append(extract_record(p))
        except Exception as e:
            event("step_failed", id="extract_receipt_fields",
                  error=f"{p}: {e}", recoverable=False)
            return 3
    event("step_done", id="extract_receipt_fields",
          outputs={"receipt_expense_records": records},
          summary=f"extracted {len(records)} record(s)")

    # Step 3
    event("step_start", id="append_expense_rows_in_sheet",
          title="Open expense tracker and append a row per pending receipt")
    try:
        sheet_rows = fetch_sheet_csv()
        to_append = select_records_to_append(records)
        if not to_append:
            log("  no valid records to append")
            result = {"rows_appended": 0, "appended_rows": []}
        else:
            next_idx, next_row = next_idx_and_row(sheet_rows)
            log(f"  appending {len(to_append)} row(s) starting at A{next_row} (next Idx={next_idx})")
            result = append_rows(to_append, next_idx, next_row)
    except Exception as e:
        event("step_failed", id="append_expense_rows_in_sheet",
              error=str(e), recoverable=False)
        return 4
    event("step_done", id="append_expense_rows_in_sheet",
          outputs=result,
          summary=f"appended {result['rows_appended']} row(s)")

    event("workflow_done", outputs=result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
