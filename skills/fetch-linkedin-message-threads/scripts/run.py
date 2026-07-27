#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import textwrap


BROWSER_CODE_TEMPLATE = r'''
import json
import sys
import time
import urllib.parse

LOOKBACK_DAYS = __LOOKBACK_DAYS__
MAX_THREADS = __MAX_THREADS__
MAX_PAGES = max(1, min(5, (MAX_THREADS + 19) // 20))
PAGE_DELAY_SECONDS = 0.9
INITIAL_QUERY_ID = "messengerConversations.0d5e6781bbee71c3e51c8843c6519f48"
OLDER_QUERY_ID = "messengerConversations.9501074288a12f3ae9e3c7ea243bccbf"


def log(message):
    print(message, file=sys.stderr, flush=True)


def fetch_linkedin_json(url):
    script = f"""
(async () => {{
  const url = {json.dumps(url)};
  const csrf = (document.cookie.match(/JSESSIONID="?([^";]+)"?/) || [])[1] || '';
  const headers = {{
    'accept': 'application/vnd.linkedin.normalized+json+2.1',
    'csrf-token': csrf,
    'x-restli-protocol-version': '2.0.0'
  }};
  const res = await fetch(url, {{credentials: 'include', headers}});
  const text = await res.text();
  let payload = null;
  try {{
    payload = JSON.parse(text);
  }} catch (error) {{
    return {{ok: false, status: res.status, error: `LinkedIn returned non-JSON: ${{text.slice(0, 180)}}`}};
  }}
  if (!res.ok) {{
    return {{ok: false, status: res.status, error: JSON.stringify(payload).slice(0, 240)}};
  }}
  return {{ok: true, status: res.status, payload}};
}})()
"""
    response = js(script)
    if not response or not response.get("ok"):
        status = response.get("status") if isinstance(response, dict) else "unknown"
        error = response.get("error") if isinstance(response, dict) else "No response"
        raise RuntimeError(f"LinkedIn request failed ({status}): {error}")
    return response["payload"]


def attributed_text(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return None


def participant_name(participant):
    participant_type = (participant or {}).get("participantType") or {}
    member = participant_type.get("member")
    if member:
        return " ".join(part for part in [attributed_text(member.get("firstName")), attributed_text(member.get("lastName"))] if part).strip() or None
    organization = participant_type.get("organization")
    if organization:
        return attributed_text(organization.get("name")) or organization.get("name")
    custom = participant_type.get("custom")
    if custom:
        return attributed_text(custom.get("displayName")) or custom.get("displayName")
    agent = participant_type.get("agent")
    if agent:
        return attributed_text(agent.get("name")) or agent.get("name")
    return None


def extract_conversations(payload):
    included = payload.get("included") or []
    by_urn = {item["entityUrn"]: item for item in included if item.get("entityUrn")}
    conversations = [
        item for item in included
        if item.get("conversationUrl") and isinstance(item.get("lastActivityAt"), (int, float))
    ]
    conversations.sort(key=lambda item: item["lastActivityAt"], reverse=True)
    return conversations, by_urn


def pick_contact_name(conversation, by_urn, self_fsd_urn, self_name):
    if conversation.get("groupChat") and conversation.get("title"):
        return attributed_text(conversation.get("title")) or str(conversation.get("title"))
    names = []
    for participant_urn in conversation.get("*conversationParticipants") or []:
        participant = by_urn.get(participant_urn)
        if not participant:
            continue
        name = participant_name(participant)
        host_urn = participant.get("hostIdentityUrn") or ""
        is_self = host_urn == self_fsd_urn or bool(self_name and name == self_name)
        if name and not is_self:
            names.append(" ".join(name.split()))
    if names:
        return ", ".join(names)
    if conversation.get("title"):
        return attributed_text(conversation.get("title")) or str(conversation.get("title"))
    fallback = [
        participant_name(by_urn.get(urn))
        for urn in (conversation.get("*conversationParticipants") or [])
    ]
    fallback = [name for name in fallback if name]
    return ", ".join(fallback) if fallback else "Unknown contact"


opened_tab = None

try:
    log("Opening LinkedIn...")
    opened_tab = new_tab("https://www.linkedin.com/feed/")
    wait_for_load()
    time.sleep(2)

    log("Reading LinkedIn profile...")
    me = fetch_linkedin_json("https://www.linkedin.com/voyager/api/me")
    mini_profile_urn = (me.get("data") or {}).get("*miniProfile")
    mini_profile = next((item for item in (me.get("included") or []) if item.get("entityUrn") == mini_profile_urn), None)
    if mini_profile is None and me.get("included"):
        mini_profile = me["included"][0]
    mini_profile = mini_profile or {}
    self_fsd_urn = mini_profile.get("dashEntityUrn") or (mini_profile_urn or "").replace("urn:li:fs_miniProfile:", "urn:li:fsd_profile:")
    self_name = " ".join(part for part in [mini_profile.get("firstName"), mini_profile.get("lastName")] if part).strip()
    if not self_fsd_urn.startswith("urn:li:fsd_profile:"):
        raise RuntimeError("Could not determine the logged-in LinkedIn profile. Please make sure LinkedIn is logged in.")

    cutoff_ms = int(time.time() * 1000) - LOOKBACK_DAYS * 24 * 60 * 60 * 1000
    seen = {}
    combined_by_urn = {}
    pages_fetched = 0
    oldest_activity = None
    stopped_because = "date cutoff reached"

    for page in range(MAX_PAGES):
        if page == 0:
            variables = f"(mailboxUrn:{urllib.parse.quote(self_fsd_urn, safe='')})"
            url = f"https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql?queryId={INITIAL_QUERY_ID}&variables={variables}"
        else:
            if oldest_activity is None:
                break
            time.sleep(PAGE_DELAY_SECONDS)
            variables = (
                "(query:(predicateUnions:List((conversationCategoryPredicate:(category:PRIMARY_INBOX)))),"
                f"count:20,mailboxUrn:{urllib.parse.quote(self_fsd_urn, safe='')},lastUpdatedBefore:{oldest_activity})"
            )
            url = f"https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql?queryId={OLDER_QUERY_ID}&variables={variables}"

        log(f"Reading thread page {page + 1}...")
        payload = fetch_linkedin_json(url)
        pages_fetched += 1
        conversations, by_urn = extract_conversations(payload)
        combined_by_urn.update(by_urn)
        if not conversations:
            stopped_because = "no more conversations returned"
            break

        page_oldest = min(conversation["lastActivityAt"] for conversation in conversations)
        new_count = 0
        for conversation in conversations:
            key = conversation.get("entityUrn") or conversation.get("conversationUrl")
            if key not in seen:
                new_count += 1
            seen.setdefault(key, conversation)
        oldest_activity = page_oldest

        if new_count == 0 and page > 0:
            stopped_because = "pagination returned duplicate conversations"
            break
        if len(seen) >= MAX_THREADS:
            stopped_because = "maximum thread limit reached"
            break

        if page_oldest < cutoff_ms:
            stopped_because = "date cutoff reached"
            break
        if len(conversations) < 20:
            stopped_because = "last page returned fewer than 20 conversations"
            break
        if page == MAX_PAGES - 1:
            stopped_because = "pagination cap reached"

    all_conversations = sorted(seen.values(), key=lambda item: item["lastActivityAt"], reverse=True)
    threads = []
    for conversation in all_conversations:
        if conversation["lastActivityAt"] < cutoff_ms:
            continue
        threads.append({
            "contact_name": pick_contact_name(conversation, combined_by_urn, self_fsd_urn, self_name),
            "last_message_date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(conversation["lastActivityAt"] / 1000)),
            "thread_url": conversation["conversationUrl"],
            "new": bool((conversation.get("unreadCount") or 0) > 0 or conversation.get("read") is False),
        })
        if len(threads) >= MAX_THREADS:
            break

    print(json.dumps({
        "success": True,
        "lookback_days": LOOKBACK_DAYS,
        "maximum_threads": MAX_THREADS,
        "threads": threads,
        "count": len(threads),
        "pages_fetched": pages_fetched,
        "stopped_because": stopped_because,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"success": False, "error": str(exc)}), flush=True)
    raise
finally:
    if opened_tab:
        try:
            log("Closing LinkedIn tab...")
            cdp("Target.closeTarget", targetId=opened_tab)
        except Exception as close_error:
            log(f"Could not close LinkedIn tab automatically: {close_error}")
'''


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_inputs(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Inputs JSON must be an object.")
    return data


def parse_days(inputs: dict) -> int:
    value = inputs.get("last_message_within_days")
    if isinstance(value, bool):
        raise ValueError("last_message_within_days must be a whole number.")
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("last_message_within_days must be a whole number.") from exc
    if days < 0:
        raise ValueError("last_message_within_days must be zero or greater.")
    return days


def parse_maximum_threads(inputs: dict) -> int:
    value = inputs.get("maximum_threads")
    if value is None or value == 0:
        return 20
    if isinstance(value, bool):
        raise ValueError("maximum_threads must be a whole number, null, or 0.")
    try:
        maximum_threads = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("maximum_threads must be a whole number, null, or 0.") from exc
    if maximum_threads < 0:
        raise ValueError("maximum_threads must be zero or greater.")
    if maximum_threads == 0:
        return 20
    if maximum_threads > 100:
        raise ValueError("maximum_threads must be 100 or less to keep LinkedIn access low-volume.")
    return maximum_threads


def run_browser_harness(days: int, maximum_threads: int) -> dict:
    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is not set.")

    browser_code = (
        BROWSER_CODE_TEMPLATE
        .replace("__LOOKBACK_DAYS__", str(days))
        .replace("__MAX_THREADS__", str(maximum_threads))
    )
    cmd = [harness, "-c", browser_code]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"LinkedIn browser step failed with exit code {proc.returncode}.")

    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("LinkedIn browser step did not return data.")
    last_json_line = stdout.splitlines()[-1]
    result = json.loads(last_json_line)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "LinkedIn extraction failed.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-json", required=True)
    args = parser.parse_args()

    try:
        log("Preparing LinkedIn message thread export...")
        inputs = load_inputs(args.inputs_json)
        days = parse_days(inputs)
        maximum_threads = parse_maximum_threads(inputs)
        log(f"Collecting up to {maximum_threads} threads from the last {days} days...")
        result = run_browser_harness(days, maximum_threads)
        outputs = {
            "threads": result["threads"],
            "count": result["count"],
            "last_message_within_days": days,
            "maximum_threads": maximum_threads,
            "pages_fetched": result.get("pages_fetched"),
            "stopped_because": result.get("stopped_because"),
        }
        print(json.dumps({"event": "workflow_done", "outputs": outputs}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
