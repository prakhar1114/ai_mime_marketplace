#!/usr/bin/env python3
"""Upload a local file into a freshly created, date-named folder under a fixed
Google Drive parent folder, using the user's already-signed-in Chrome.

All values are constants (no user inputs):
  - parent Drive folder : the "ai mime - binary" folder
  - local file          : /Users/prakharjain/code/ai_mime/dist/AI Mime.dmg
  - new folder name      : "v0 - <today's date>" e.g. "v0 - 31 May"; if it already
                           exists under the parent, " - 2" / " - 3" ... is appended.

Invocation:
  "$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json /path/to/inputs.json
The inputs JSON is accepted for interface compatibility but is not required.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

# ---- constants (baked in; this skill takes no user inputs) -------------------
DRIVE_PARENT_ID = "1M1E4LNjEXLvaH7j5JY1Un3XRx6M6mtvV"  # "ai mime - binary"
FILE_PATH = "/Users/prakharjain/code/ai_mime/dist/AI Mime.dmg"
FOLDER_PREFIX = "v0"

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_FILE = os.path.join(HERE, "drive_flow.py")


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False),
          file=sys.stderr, flush=True)


def base_folder_name(today=None):
    today = today or datetime.date.today()
    # "v0 - 31 May" : day without leading zero, full month name.
    return "{} - {} {}".format(FOLDER_PREFIX, today.day, today.strftime("%B"))


def main():
    parser = argparse.ArgumentParser(description="Upload file to a new Google Drive folder")
    parser.add_argument("--inputs-json", required=False, help="Path to inputs JSON (optional; no inputs used)")
    args = parser.parse_args()

    if args.inputs_json:
        try:
            with open(args.inputs_json, "r", encoding="utf-8") as f:
                json.load(f)  # accepted but unused
        except Exception:
            pass

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        log_event("step_failed", id="create_folder_and_upload_via_drive_api",
                  error="AI_MIME_BROWSER_HARNESS_BIN not configured", recoverable=False)
        sys.exit(1)

    # Pre-flight: the local file must exist.
    if not os.path.isfile(FILE_PATH):
        log_event("step_failed", id="create_folder_and_upload_via_drive_api",
                  error="Local file not found: " + FILE_PATH, recoverable=False)
        sys.exit(1)

    base_name = base_folder_name()

    # ---- Step 1: create folder + upload (browser_harness) --------------------
    log_event("step_start", id="create_folder_and_upload_via_drive_api",
              title="Create Drive folder and upload file")

    with open(FLOW_FILE, "r", encoding="utf-8") as f:
        flow_code = f.read()

    env = dict(os.environ)
    env["DRIVE_PARENT_ID"] = DRIVE_PARENT_ID
    env["DRIVE_FILE_PATH"] = FILE_PATH
    env["DRIVE_BASE_NAME"] = base_name

    try:
        proc = subprocess.run([harness_bin, "-c", flow_code],
                              capture_output=True, text=True, env=env, timeout=900)
    except subprocess.TimeoutExpired:
        log_event("step_failed", id="create_folder_and_upload_via_drive_api",
                  error="Drive automation timed out", recoverable=True)
        sys.exit(1)

    # Parse the single RESULT_JSON line from harness stdout.
    result = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("RESULT_JSON:"):
            try:
                result = json.loads(line[len("RESULT_JSON:"):])
            except Exception:
                result = None

    if result is None:
        log_event("step_failed", id="create_folder_and_upload_via_drive_api",
                  error="No result from browser automation. stderr=" + (proc.stderr or "")[-800:],
                  recoverable=True)
        sys.exit(1)

    if not result.get("ok"):
        log_event("step_failed", id="create_folder_and_upload_via_drive_api",
                  error=result.get("error") or "Drive automation failed", recoverable=True)
        sys.exit(1)

    new_folder_id = result.get("new_folder_id")
    uploaded_file_id = result.get("uploaded_file_id")
    folder_name = result.get("folder_name", base_name)
    log_event("step_done", id="create_folder_and_upload_via_drive_api",
              outputs={"new_folder_id": new_folder_id,
                       "uploaded_file_id": uploaded_file_id,
                       "folder_name": folder_name},
              summary="Created folder '{}' and uploaded {}".format(
                  folder_name, os.path.basename(FILE_PATH)))

    # ---- Step 2: verify the file resides in the new folder -------------------
    log_event("step_start", id="verify_upload_complete",
              title="Verify file resides in the new folder")
    verified = bool(result.get("verified"))
    if not verified:
        log_event("step_failed", id="verify_upload_complete",
                  error="Uploaded file was not found inside the new folder",
                  recoverable=True)
        sys.exit(1)
    log_event("step_done", id="verify_upload_complete",
              outputs={"upload_verified": True, "upload_status": result.get("upload_status")},
              summary="Confirmed {} is inside folder '{}'".format(
                  os.path.basename(FILE_PATH), folder_name))

    log_event("workflow_done", outputs={
        "folder_name": folder_name,
        "new_folder_id": new_folder_id,
        "uploaded_file_id": uploaded_file_id,
        "upload_verified": True,
        "drive_folder_url": "https://drive.google.com/drive/u/0/folders/" + (new_folder_id or ""),
    })


if __name__ == "__main__":
    main()
