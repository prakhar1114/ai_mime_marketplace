import argparse
import json
import os
import subprocess
import sys

JIRA_BASE = "https://aimime.atlassian.net"


def log_event(event_type, **kwargs):
    """Emit a structured execution log event to stderr."""
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


def run_harness(script_code):
    """Run a browser-harness CDP script and return (stdout, stderr)."""
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN not configured")
    proc = subprocess.run([harness_bin, "-c", script_code], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"browser-harness failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout, proc.stderr


def main():
    parser = argparse.ArgumentParser(description="Add a comment to a Jira ticket")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        with open(args.inputs_json, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    except Exception as e:
        print(f"Error reading inputs: {e}", file=sys.stderr)
        sys.exit(1)

    ticket = (inputs.get("ticket") or "").strip()
    comment = inputs.get("comment")

    if not ticket:
        log_event("step_failed", id="validate_inputs", error="Missing required input: ticket", recoverable=False)
        sys.exit(1)
    if not comment or not str(comment).strip():
        log_event("step_failed", id="validate_inputs", error="Missing required input: comment", recoverable=False)
        sys.exit(1)
    comment = str(comment)

    ticket_url = f"{JIRA_BASE}/browse/{ticket}"

    # --- Single browser-harness step: open ticket, open editor, type, save via Cmd+Enter ---
    log_event("step_start", id="post_comment", title=f"Posting comment on {ticket}")

    # JSON-encode values so they embed safely as Python string literals in the harness script.
    url_lit = json.dumps(ticket_url)
    comment_lit = json.dumps(comment)
    ticket_lit = json.dumps(ticket)

    harness_code = f'''
import time, json

new_tab({url_lit})
wait_for_load()
time.sleep(2)

# Detect a login wall (not authenticated) before doing anything else.
info = page_info()
cur_url = info.get("url", "")
if "id.atlassian.com" in cur_url or "/login" in cur_url:
    print("RESULT:" + json.dumps({{"ok": False, "reason": "auth_wall", "url": cur_url}}))
else:
    # Confirm the ticket actually loaded (key should appear on the page).
    has_ticket = js("""(() => document.body.innerText.includes({ticket_lit}) )()""")

    if has_ticket != True:
        print("RESULT:" + json.dumps({{"ok": False, "reason": "ticket_not_found", "url": cur_url}}))
    else:
        # 'm' is Jira's shortcut to open + focus the comment editor (body must have focus).
        press_key("m")
        time.sleep(2)

        # Locate the contenteditable comment editor and click to ensure focus.
        loc = js("""
        (() => {{
          const ed = document.querySelector("div[contenteditable=true]");
          if(!ed) return null;
          const r = ed.getBoundingClientRect();
          return JSON.stringify({{x: r.x + 20, y: r.y + 15, visible: r.width > 0}});
        }})()
        """)
        if not loc:
            print("RESULT:" + json.dumps({{"ok": False, "reason": "no_editor", "url": cur_url}}))
        else:
            c = json.loads(loc)
            click_at_xy(int(c["x"]), int(c["y"]))
            time.sleep(0.8)

            type_text({comment_lit})
            time.sleep(1)

            # Save with Cmd+Enter (modifiers bitfield: 4 = Meta/Cmd).
            press_key("Enter", modifiers=4)
            time.sleep(3)

            # Success when the editor cleared AND no pending "Save" button remains.
            state = js("""
            (() => {{
              const ed = document.querySelector("div[contenteditable=true]");
              const draft = ed ? ed.innerText.trim() : "";
              const saveBtn = [...document.querySelectorAll("button")].find(b => b.textContent.trim() === "Save");
              return JSON.stringify({{draft: draft, saveBtn: !!saveBtn}});
            }})()
            """)
            st = json.loads(state)
            saved = (st["draft"] == "") and (not st["saveBtn"])
            print("RESULT:" + json.dumps({{"ok": saved, "reason": "posted" if saved else "not_saved", "url": cur_url}}))
'''

    try:
        stdout, _ = run_harness(harness_code)
    except Exception as e:
        log_event("step_failed", id="post_comment", error=str(e), recoverable=False)
        sys.exit(1)

    result = None
    for line in stdout.splitlines():
        if line.startswith("RESULT:"):
            try:
                result = json.loads(line[len("RESULT:"):])
            except json.JSONDecodeError:
                pass

    if result is None:
        log_event("step_failed", id="post_comment", error=f"No result returned from browser. Output: {stdout.strip()}", recoverable=False)
        sys.exit(1)

    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        messages = {
            "auth_wall": "Not logged in to Jira in Chrome. Please log in to aimime.atlassian.net and retry.",
            "ticket_not_found": f"Could not load ticket {ticket}. Check the ticket key.",
            "no_editor": "Could not open the comment editor on the ticket.",
            "not_saved": "The comment did not save successfully.",
        }
        log_event("step_failed", id="post_comment", error=messages.get(reason, f"Failed: {reason}"), recoverable=False)
        sys.exit(1)

    log_event("step_done", id="post_comment", outputs={"ticket": ticket, "url": ticket_url},
              summary=f"Posted comment on {ticket}")

    log_event("workflow_done", outputs={
        "ticket": ticket,
        "ticket_url": ticket_url,
        "comment": comment,
        "posted": True,
    })


if __name__ == "__main__":
    main()
