#!/usr/bin/env python3
"""Find restaurants on Google Maps and send them to a WhatsApp contact.

Step 1 (browser_harness): open Google Maps search results for the query, extract
the configured number of top restaurant names and URLs, then close the Maps tab.
Step 2 (ui_agent): drive the native WhatsApp Mac app to open the contact's chat
and send one intro message plus one separate message per restaurant.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys


INTRO_MESSAGE = "suggested places to eat, do a thumbsup where we should meet"
DEFAULT_RESULT_LIMIT = 5


def log_event(event_type, **kwargs):
    event = {"event": event_type, **kwargs}
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


# --- Step 1: Google Maps extraction via browser-harness -------------------

HARNESS_TEMPLATE = r'''
import json, time, urllib.parse

query = __QUERY__
limit = __LIMIT__
url = "https://www.google.com/maps/search/" + urllib.parse.quote(query)

new_tab(url)
wait_for_load()
time.sleep(4)

try:
    places = js("""
((limit) => {
  const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  const seenNames = new Set();
  const feed = document.querySelector('div[role=feed]');
  const cards = feed ? Array.from(feed.querySelectorAll('div.Nv2PK'))
                     : Array.from(document.querySelectorAll('div.Nv2PK'));
  for (const c of cards) {
    const nameEl = c.querySelector('.qBF1Pd') || c.querySelector('a[aria-label]');
    const linkEl = c.querySelector('a.hfpxzc[href]') ||
      c.querySelector('a[href*="/maps/place/"]') ||
      c.querySelector('a[href]');
    const name = normalize(nameEl ? (nameEl.textContent || nameEl.getAttribute('aria-label')) : '');
    const href = linkEl ? linkEl.href : '';
    const nameKey = name.toLowerCase();
    if (!name || !href || seenNames.has(nameKey)) continue;
    seenNames.add(nameKey);
    out.push({name, url: href});
    if (out.length >= limit) break;
  }
  return out;
})(%d)
""" % limit)
finally:
    try:
        js("window.close(); true")
    except Exception:
        pass

print("RESULT_JSON:" + json.dumps(places or [], ensure_ascii=False))
'''


def find_top_restaurants(search_query, result_limit):
    step_id = "find_top_restaurants"
    step_title = "Search Google Maps and extract top restaurant names and URLs"
    log_event("step_start", id=step_id, title=step_title)

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        log_event("step_failed", id=step_id, error="AI_MIME_BROWSER_HARNESS_BIN not configured", recoverable=False)
        sys.exit(1)

    script_code = (
        HARNESS_TEMPLATE
        .replace("__QUERY__", json.dumps(search_query))
        .replace("__LIMIT__", json.dumps(result_limit))
    )
    try:
        proc = subprocess.run([harness_bin, "-c", script_code], stdout=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        log_event("step_failed", id=step_id, error=f"Browser harness failed: {e}", recoverable=False)
        sys.exit(1)

    places = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            try:
                places = json.loads(line[len("RESULT_JSON:"):])
            except json.JSONDecodeError:
                places = None
            break

    if not places:
        log_event(
            "step_failed",
            id=step_id,
            error=f"Could not extract restaurants from Google Maps. stdout: {proc.stdout[-500:]}",
            recoverable=False,
        )
        sys.exit(1)

    restaurant_places = [
        {"name": str(place.get("name", "")).strip(), "url": str(place.get("url", "")).strip()}
        for place in places[:result_limit]
        if place.get("name") and place.get("url")
    ]
    if len(restaurant_places) < result_limit:
        log_event(
            "step_failed",
            id=step_id,
            error=f"Expected {result_limit} restaurants with URLs, found {len(restaurant_places)}: {restaurant_places}",
            recoverable=False,
        )
        sys.exit(1)

    restaurant_messages = [INTRO_MESSAGE] + [
        f"{i}. {place['name']} - {place['url']}"
        for i, place in enumerate(restaurant_places, start=1)
    ]

    log_event(
        "step_done",
        id=step_id,
        outputs={"restaurant_places": restaurant_places, "restaurant_messages": restaurant_messages},
        summary=f"Extracted {len(restaurant_places)} restaurants with URLs and closed the Maps search tab",
    )
    return restaurant_places, restaurant_messages


# --- Step 2: Send WhatsApp messages via the UI agent ----------------------

def send_whatsapp_messages(contact_name, restaurant_messages):
    step_id = "send_whatsapp_message"
    step_title = "Open WhatsApp chat and send restaurant suggestions"
    log_event("step_start", id=step_id, title=step_title)

    ui_agent_cmd = os.environ.get("AI_MIME_UI_AGENT_CMD")
    if not ui_agent_cmd:
        log_event("step_failed", id=step_id, error="AI_MIME_UI_AGENT_CMD not configured", recoverable=False)
        sys.exit(1)

    messages_json = json.dumps(restaurant_messages, ensure_ascii=False)
    task_prompt = (
        "Target and constraints: Drive the native WhatsApp Mac app (bundle id "
        "net.whatsapp.WhatsApp), NOT WhatsApp Web. This is the user's real personal "
        "WhatsApp. Never guess, never click blind, and do not send anything until the "
        "right chat is confirmed.\n\n"
        "Known setup: Bring WhatsApp to the foreground with exactly this command first: "
        "osascript -e 'tell application \"WhatsApp\" to activate'. Then take one "
        "screenshot to confirm the WhatsApp window is frontmost. Do not relaunch the app "
        "or loop through activation methods.\n\n"
        "Performance rules: WhatsApp is an Electron app. Prefer screenshot/vision for "
        "locating controls. Do not dump the full accessibility tree unless a screenshot "
        "is genuinely ambiguous. Enter text by clipboard paste plus Cmd+V, never "
        "char-by-char typing. After the correct chat and compose box are verified once, "
        "do not screenshot or inspect after every message; send the remaining messages "
        "in a tight clipboard paste + Return loop with only a short pause between sends.\n\n"
        "Goal: Open the correct chat and send these exact messages as separate outgoing "
        f"WhatsApp messages, in order: {messages_json}\n\n"
        "Important completion rule: existing outgoing bubbles from earlier runs do not "
        "count as completion for this run. After this run starts, send every provided "
        "message once in the listed order unless you have personally just sent it in "
        "this same run.\n\n"
        "Action sequence:\n"
        "1. If the correct chat is not already open, click the chat search field at the "
        "top of the left sidebar (placeholder 'Search'), paste the contact name "
        f"{json.dumps(contact_name)}, and wait for results under the Chats heading.\n"
        "2. Open only the top chat entry whose displayed name matches the contact name. "
        f"A self-chat may appear as '{contact_name} (You)' and is a correct match. If no "
        "entry clearly matches, stop and return sent=false with a note.\n"
        "3. Confirm the right-pane chat header shows the contact name, or the contact "
        "name followed by '(You)'. If it is anyone else, stop and return sent=false.\n"
        "4. Click the message compose box at the bottom of the right pane. If stale draft "
        "text is present, use Cmd+A before the first paste so the first message replaces it.\n"
        "5. Verify the first pasted message is in the compose box once. Press the physical "
        "Return key to send it, using key='enter' if the UI tool names Return that way. "
        "Confirm the compose box clears after this first send.\n"
        "6. For each remaining message, use this fast loop without intermediate screenshots "
        "or accessibility lookups: set clipboard to the next exact message, click/focus the "
        "compose box if needed, Cmd+V, press key='enter', wait briefly for the compose box "
        "to clear, then continue. Do not click the send button. Each restaurant must be "
        "its own separate message; do not combine messages or insert line breaks.\n"
        "7. After the last message, take one final screenshot and verify a new outgoing "
        "right-aligned message bubble for the final place is visible and the compose box "
        "is clear.\n\n"
        "Recovery: If the text remains unsent in the compose box, click the compose box "
        "again to restore focus and press the physical Return key again using key='enter' "
        "if needed. Do not use the green send/paper-plane button. If Return still does "
        "not send, stop and return sent=false with a note.\n\n"
        f"Return JSON with sent=true and messages_sent exactly equal to {len(restaurant_messages)} "
        "after final verification; otherwise sent=false with a note."
    )
    schema = {
        "type": "object",
        "properties": {
            "sent": {"type": "boolean"},
            "messages_sent": {"type": "integer"},
            "note": {"type": "string"},
        },
        "required": ["sent"],
    }

    cmd = shlex.split(ui_agent_cmd) + [task_prompt, "--schema", json.dumps(schema), "--json"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
        result = json.loads(proc.stdout)
    except subprocess.CalledProcessError as e:
        log_event("step_failed", id=step_id, error=f"UI Agent command failed to run: {e}", recoverable=False)
        sys.exit(1)
    except json.JSONDecodeError:
        log_event("step_failed", id=step_id, error="UI Agent returned invalid JSON output", recoverable=False)
        sys.exit(1)

    out = extract_ui_result(result)
    if not out:
        log_event("step_failed", id=step_id, error=result.get("error") or "UI Agent task failed", recoverable=False)
        sys.exit(1)

    if out.get("sent"):
        if "messages_sent" not in out:
            out["messages_sent"] = len(restaurant_messages)
        try:
            messages_sent = int(out["messages_sent"])
        except (TypeError, ValueError):
            messages_sent = -1
        if messages_sent != len(restaurant_messages):
            log_event(
                "step_failed",
                id=step_id,
                error=f"UI Agent reported {messages_sent} messages sent; expected {len(restaurant_messages)}",
                recoverable=False,
            )
            sys.exit(1)
        log_event(
            "step_done",
            id=step_id,
            outputs={"sent_confirmation": out},
            summary=result.get("summary", f"Sent {len(restaurant_messages)} WhatsApp messages to {contact_name}"),
        )
        return out

    log_event("step_failed", id=step_id, error=out.get("note") or "UI Agent task failed", recoverable=False)
    sys.exit(1)


def extract_ui_result(result):
    if result.get("status") == "success" and isinstance(result.get("result_json"), dict):
        return result["result_json"]
    if isinstance(result.get("sent"), bool):
        return result

    # Some UI-agent runs emit the schema JSON inside a textual summary even when
    # the wrapper status is failed because an accessibility lookup did not expose
    # the already visually verified WhatsApp bubble.
    for key in ("summary", "error", "note"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        start = value.rfind("{")
        end = value.rfind("}")
        if start == -1 or end == -1 or end <= start:
            continue
        try:
            candidate = json.loads(value[start:end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("sent"), bool):
            return candidate
    return None


def read_inputs(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    except Exception as e:
        print(f"Error reading inputs: {e}", file=sys.stderr)
        sys.exit(1)

    search_query = inputs.get("search_query")
    contact_name = inputs.get("contact_name")
    raw_limit = inputs.get("result_limit", DEFAULT_RESULT_LIMIT)

    if not search_query:
        print("Missing required input: search_query", file=sys.stderr)
        sys.exit(1)
    if not contact_name:
        print("Missing required input: contact_name", file=sys.stderr)
        sys.exit(1)
    try:
        result_limit = int(raw_limit)
    except (TypeError, ValueError):
        print("Input result_limit must be an integer", file=sys.stderr)
        sys.exit(1)
    if result_limit < 1:
        print("Input result_limit must be at least 1", file=sys.stderr)
        sys.exit(1)

    return search_query, contact_name, result_limit


def main():
    parser = argparse.ArgumentParser(description="Find restaurants on Google Maps and send them on WhatsApp")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    search_query, contact_name, result_limit = read_inputs(args.inputs_json)

    restaurant_places, restaurant_messages = find_top_restaurants(search_query, result_limit)
    sent_confirmation = send_whatsapp_messages(contact_name, restaurant_messages)

    log_event("workflow_done", outputs={
        "restaurant_places": restaurant_places,
        "restaurant_messages": restaurant_messages,
        "sent_confirmation": sent_confirmation,
    })


if __name__ == "__main__":
    main()
