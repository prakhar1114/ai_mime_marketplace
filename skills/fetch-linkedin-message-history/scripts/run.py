#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys


INNER_SCRIPT = r'''
import json
import os
import re
import sys
import time


MESSENGER_MESSAGES_QUERY_ID = "messengerMessages.5846eeb71c981f11e0134cb6626cc314"
INPUTS = json.loads(os.environ["AI_MIME_LINKEDIN_INPUTS_JSON"])


def log(message):
    print(message, file=sys.stderr, flush=True)


def is_thread_url(url):
    return bool(re.search(r"/messaging/thread/([^/?#]+)/?", url or ""))


def thread_id_from_url(url):
    match = re.search(r"/messaging/thread/([^/?#]+)/?", url or "")
    return match.group(1) if match else None


def check_page_state():
    return js(r"""
    (() => {
      const text = document.body ? document.body.innerText.slice(0, 3000) : "";
      const login = /sign in|join now|email or phone|password/i.test(text) && /linkedin/i.test(text);
      const checkpoint = /security check|checkpoint|captcha|verify|unusual activity|temporarily restricted|rate limit/i.test(text);
      return {href: location.href, title: document.title, login, checkpoint, text: text.slice(0, 500)};
    })()
    """)


def require_safe_page():
    state = check_page_state()
    if state.get("login"):
        raise RuntimeError("LinkedIn is showing a login page. Please log in in Chrome and rerun.")
    if state.get("checkpoint"):
        raise RuntimeError("LinkedIn is showing a security, checkpoint, or rate-limit screen. Stopping without further actions.")
    return state


def fetch_messages_api(conversation_urn=None, thread_id=None, query_id=None):
    payload = {
        "conversationUrn": conversation_urn,
        "threadId": thread_id,
        "queryId": query_id or MESSENGER_MESSAGES_QUERY_ID,
    }
    return js(f"""
    (async () => {{
      const payload = {json.dumps(payload)};
      function cookie(name) {{
        const esc = name.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
        const m = document.cookie.match(new RegExp('(?:^|; )' + esc + '=([^;]*)'));
        return m ? decodeURIComponent(m[1]).replace(/^"|"$/g, '') : '';
      }}
      function strictEncode(value) {{
        return encodeURIComponent(value).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
      }}
      function headers(accept) {{
        return {{
          'csrf-token': cookie('JSESSIONID'),
          'x-restli-protocol-version': '2.0.0',
          'accept': accept || 'application/json'
        }};
      }}
      function textOf(value) {{
        if (!value) return "";
        if (typeof value === "string") return value.trim();
        if (value.text) return String(value.text).trim();
        if (value.firstName || value.lastName) return [value.firstName, value.lastName].filter(Boolean).join(" ").trim();
        if (value.localizedFirstName || value.localizedLastName) return [value.localizedFirstName, value.localizedLastName].filter(Boolean).join(" ").trim();
        return "";
      }}
      function participantName(participant, viewerProfileUrn) {{
        if (!participant) return null;
        const member = participant.participantType && participant.participantType.member;
        if (member) {{
          const memberName = [textOf(member.firstName), textOf(member.lastName)].filter(Boolean).join(" ").trim();
          if (memberName) return memberName;
        }}
        const direct = [
          participant.name,
          participant.fullName,
          participant.title,
          participant.profileName,
          participant.participantName
        ].map(textOf).find(Boolean);
        if (direct) return direct;
        const nested = [participant.profile, participant.miniProfile, participant.member, participant.identity]
          .map(textOf).find(Boolean);
        if (nested) return nested;
        if (participant.entityUrn && viewerProfileUrn && participant.entityUrn.includes(viewerProfileUrn)) return "You";
        return null;
      }}
      function profileUrnFromParticipantUrn(urn) {{
        if (!urn) return null;
        const marker = "urn:li:msg_messagingParticipant:";
        return urn.startsWith(marker) ? urn.slice(marker.length) : null;
      }}
      function parseMessages(data, viewerProfileUrn, sourceUrl) {{
        const included = Array.isArray(data && data.included) ? data.included : [];
        const byUrn = new Map();
        for (const item of included) {{
          if (item && item.entityUrn) byUrn.set(item.entityUrn, item);
        }}
        const participants = new Map();
        for (const item of included) {{
          if (item && String(item["$type"] || "").includes("MessagingParticipant") && item.entityUrn) {{
            participants.set(item.entityUrn, item);
          }}
        }}
        const elementUrns = (((data || {{}}).data || {{}}).data || {{}}).messengerMessagesBySyncToken
          && (((data || {{}}).data || {{}}).data || {{}}).messengerMessagesBySyncToken["*elements"];
        let rawMessages = [];
        if (Array.isArray(elementUrns)) {{
          rawMessages = elementUrns.map(urn => byUrn.get(urn)).filter(Boolean);
        }}
        if (!rawMessages.length) {{
          rawMessages = included.filter(item => item && String(item["$type"] || "").includes("Message") && item.deliveredAt);
        }}
        const messages = rawMessages.map((message, index) => {{
          const senderUrn = message["*sender"] || message["*actor"] || "";
          const senderProfileUrn = profileUrnFromParticipantUrn(senderUrn);
          const participant = participants.get(senderUrn);
          const senderDisplayName = participantName(participant, viewerProfileUrn);
          const direction = senderProfileUrn && viewerProfileUrn && senderProfileUrn === viewerProfileUrn ? "self" : "other";
          let text = (message.body && message.body.text) || message.renderContentFallbackText || "";
          let contentType = message.messageBodyRenderFormat || "DEFAULT";
          let hostUrn = null;
          let hostType = null;
          if (!text && Array.isArray(message.renderContent) && message.renderContent.length) {{
            for (const content of message.renderContent) {{
              if (content && content.hostUrnData && content.hostUrnData.hostUrn) {{
                hostUrn = content.hostUrnData.hostUrn;
                hostType = content.hostUrnData.type || null;
                break;
              }}
            }}
            text = "[LinkedIn shared content]";
            contentType = "LINKEDIN_CONTENT";
          }}
          if (!text && message.messageBodyRenderFormat === "RECALLED") {{
            text = "[recalled message]";
            contentType = "RECALLED";
          }}
          const deliveredAt = Number(message.deliveredAt || 0);
          const activityMatch = hostUrn && hostUrn.match(/urn:li:activity:(\\d+)/);
          const activityId = activityMatch ? activityMatch[1] : null;
          const sharedContent = hostUrn ? {{
            source: "messenger_api_direct",
            host_urn: hostUrn,
            host_type: hostType,
            activity_id: activityId,
            derived_linkedin_url: activityId ? `https://www.linkedin.com/feed/update/urn:li:activity:${{activityId}}/` : null,
            preview_text: message.renderContentFallbackText || null,
            note: "No shared URL was opened or fetched. Preview text is only present when LinkedIn includes it directly in the message payload."
          }} : null;
          return {{
            id: message.entityUrn || message.backendUrn || String(index),
            backend_urn: message.backendUrn || null,
            delivered_at_ms: deliveredAt || null,
            delivered_at_iso: deliveredAt ? new Date(deliveredAt).toISOString() : null,
            sender_profile_urn: senderProfileUrn,
            sender_name: senderDisplayName,
            sender: direction === "self" ? "You" : (senderDisplayName || "Unknown"),
            text,
            content_type: contentType,
            shared_content_host_urn: hostUrn,
            shared_content: sharedContent,
            source_url: sourceUrl
          }};
        }}).filter(m => m.delivered_at_ms || m.text);
        messages.sort((a, b) => (a.delivered_at_ms || 0) - (b.delivered_at_ms || 0));
        return messages;
      }}
      const meRes = await fetch('/voyager/api/me', {{
        credentials: 'include',
        headers: headers('application/json')
      }});
      const meText = await meRes.text();
      let me = null;
      try {{ me = JSON.parse(meText); }} catch (e) {{}}
      if (!meRes.ok || !me || !me.miniProfile || !me.miniProfile.dashEntityUrn) {{
        return {{
          ok: false,
          status: meRes.status,
          error: "Could not read the logged-in LinkedIn profile from /voyager/api/me."
        }};
      }}
      const viewerProfileUrn = me.miniProfile.dashEntityUrn;
      const conversationUrn = payload.conversationUrn || `urn:li:msg_conversation:(${{viewerProfileUrn}},${{payload.threadId}})`;
      if (!conversationUrn || conversationUrn.includes("null") || conversationUrn.includes("undefined")) {{
        return {{ok: false, error: "Could not determine the LinkedIn conversation URN."}};
      }}
      const variables = `(conversationUrn:${{strictEncode(conversationUrn)}})`;
      const apiUrl = `/voyager/api/voyagerMessagingGraphQL/graphql?queryId=${{payload.queryId}}&variables=${{variables}}`;
      const res = await fetch(apiUrl, {{
        credentials: 'include',
        headers: headers('application/vnd.linkedin.normalized+json+2.1')
      }});
      const text = await res.text();
      let data = null;
      try {{ data = JSON.parse(text); }} catch (e) {{}}
      if (!res.ok || !data) {{
        return {{
          ok: false,
          status: res.status,
          error: `LinkedIn messaging API returned HTTP ${{res.status}}.`,
          body_start: text.slice(0, 500),
          conversation_urn: conversationUrn,
          query_id: payload.queryId
        }};
      }}
      const messages = parseMessages(data, viewerProfileUrn, location.href);
      return {{
        ok: true,
        status: res.status,
        viewer_profile_urn: viewerProfileUrn,
        conversation_urn: conversationUrn,
        query_id: payload.queryId,
        api_url: apiUrl,
        messages
      }};
    }})()
    """)


def extract_compose_url_from_profile():
    return js(r"""
    (() => {
      const links = Array.from(document.querySelectorAll('a[href*="/messaging/compose/"]'));
      const candidates = links.map(a => ({
        href: a.href,
        text: (a.innerText || a.textContent || '').trim(),
        aria: a.getAttribute('aria-label') || ''
      })).filter(x => /message/i.test([x.text, x.aria, x.href].join(' ')));
      candidates.sort((a, b) => {
        const aPrefilled = /[?&](body|subject)=/i.test(a.href) ? 1 : 0;
        const bPrefilled = /[?&](body|subject)=/i.test(b.href) ? 1 : 0;
        return aPrefilled - bPrefilled;
      });
      const profileName = (document.querySelector('h1') && document.querySelector('h1').innerText.trim()) || document.title.replace(/\s*\|\s*LinkedIn.*/, '').trim();
      return {compose_url: candidates[0] && candidates[0].href, profile_name: profileName, candidates};
    })()
    """)


def extract_message_api_resource():
    return js(r"""
    (() => {
      const resources = performance.getEntriesByType('resource').map(r => r.name)
        .filter(name => /voyagerMessagingGraphQL\/graphql/.test(name) && /queryId=messengerMessages/.test(name) && /conversationUrn/.test(name));
      const latest = resources[resources.length - 1] || null;
      if (!latest) return {url: null};
      const q = latest.match(/[?&]queryId=([^&]+)/);
      const c = latest.match(/variables=\(conversationUrn:([^)]+)\)/);
      return {
        url: latest,
        query_id: q ? decodeURIComponent(q[1]) : null,
        conversation_urn: c ? decodeURIComponent(c[1]) : null
      };
    })()
    """)


def extract_dom_messages(source_url):
    return js(f"""
    (() => {{
      const sourceUrl = {json.dumps(source_url)};
      const events = Array.from(document.querySelectorAll('.msg-s-message-list__event'));
      let currentDate = null;
      const messages = [];
      for (const event of events) {{
        const dateHeading = event.querySelector('.msg-s-message-list__time-heading');
        if (dateHeading && dateHeading.innerText.trim()) currentDate = dateHeading.innerText.trim();
        const items = Array.from(event.querySelectorAll('.msg-s-event-listitem[data-event-urn], .msg-s-event-listitem'));
        for (const item of items) {{
          const senderLink = item.querySelector('.msg-s-event-listitem__link + a, a.inline-block');
          const senderName = senderLink ? senderLink.innerText.trim() : null;
          const timeEl = item.querySelector('.msg-s-message-group__timestamp');
          const timeText = timeEl ? timeEl.innerText.trim() : null;
          const clone = item.cloneNode(true);
          for (const selector of ['button', 'svg', '.msg-s-event-listitem__link', '.msg-s-message-group__timestamp', '.msg-reactions__entry-point']) {{
            clone.querySelectorAll(selector).forEach(el => el.remove());
          }}
          let text = (clone.innerText || '').trim().replace(/\\s+/g, ' ');
          if (senderName && text.startsWith(senderName)) text = text.slice(senderName.length).trim();
          if (timeText && text.startsWith(timeText)) text = text.slice(timeText.length).trim();
          if (!text) text = (item.innerText || '').trim().replace(/\\s+/g, ' ');
          if (text) {{
            messages.push({{
              id: item.getAttribute('data-event-urn') || null,
              backend_urn: null,
              delivered_at_ms: null,
              delivered_at_iso: null,
              visible_date: currentDate,
              visible_time: timeText,
              sender_profile_urn: null,
              sender_name: senderName,
              sender: senderName || 'Unknown',
              text,
              content_type: 'DOM_VISIBLE',
              source_url: sourceUrl
            }});
          }}
        }}
      }}
      return messages;
    }})()
    """)


def filter_messages(messages, days):
    if days is None:
        sorted_messages = sorted(messages, key=lambda m: (m.get("delivered_at_ms") is None, m.get("delivered_at_ms") or 0))
        if len(sorted_messages) > 20:
            return sorted_messages[-20:]
        return sorted_messages
    cutoff_ms = int((time.time() - float(days) * 86400) * 1000)
    with_dates = [m for m in messages if m.get("delivered_at_ms")]
    if with_dates:
        return [m for m in messages if m.get("delivered_at_ms") and m["delivered_at_ms"] >= cutoff_ms]
    return messages


def possibly_truncated(messages, days):
    if days is None or len(messages) < 20:
        return False
    dated = [m.get("delivered_at_ms") for m in messages if m.get("delivered_at_ms")]
    if not dated:
        return False
    cutoff_ms = int((time.time() - float(days) * 86400) * 1000)
    return min(dated) >= cutoff_ms


def markdown_escape(text):
    return str(text or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def markdown_link(url):
    if not url:
        return ""
    return f"[{markdown_escape(url)}]({url})"


def linkify_text(text):
    pattern = re.compile(r"https?://[^\s)\]]+")
    return pattern.sub(lambda match: markdown_link(match.group(0)), str(text or ""))


def message_timestamp(message):
    return message.get("delivered_at_iso") or " ".join(
        value for value in [message.get("visible_date"), message.get("visible_time")] if value
    ) or "unknown time"


def message_markdown(message):
    sender = message.get("sender") or message.get("sender_name") or "Unknown"
    if message.get("shared_content") and message["shared_content"].get("derived_linkedin_url"):
        shared = message["shared_content"]
        activity_id = shared.get("activity_id") or "LinkedIn activity"
        body = f"Shared LinkedIn content {markdown_link(shared.get('derived_linkedin_url'))}"
        if activity_id:
            body += f" (activity {markdown_escape(activity_id)})"
        if shared.get("preview_text"):
            body += f": {linkify_text(shared['preview_text'])}"
    else:
        body = linkify_text(message.get("text") or "")
    return f"- {message_timestamp(message)} - {markdown_escape(sender)}: {body}"


def attach_markdown(messages):
    for message in messages:
        message["text_markdown"] = linkify_text(message.get("text") or "")
        message["markdown"] = message_markdown(message)
    return messages


def run_thread_case(url, days):
    tab_id = None
    try:
        thread_id = thread_id_from_url(url)
        if not thread_id:
            raise RuntimeError("Could not parse the LinkedIn thread id from the URL.")
        log("Opening a neutral LinkedIn page for authenticated API access...")
        tab_id = new_tab("https://www.linkedin.com/feed/")
        wait_for_load()
        time.sleep(2)
        require_safe_page()
        log("Reading messages through LinkedIn's first-party messaging API...")
        api_result = fetch_messages_api(thread_id=thread_id)
        if not api_result.get("ok"):
            raise RuntimeError(api_result.get("error") or "LinkedIn messaging API request failed.")
        all_messages = api_result.get("messages") or []
        selected = attach_markdown(filter_messages(all_messages, days))
        return {
            "success": True,
            "input_url": url,
            "days": days,
            "method": "linkedin_first_party_api",
            "conversation_urn": api_result.get("conversation_urn"),
            "query_id": api_result.get("query_id"),
            "message_count": len(selected),
            "fetched_message_count": len(all_messages),
            "possibly_truncated": possibly_truncated(all_messages, days),
            "messages": selected,
            "message_history_markdown": "\n".join(message.get("markdown", "") for message in selected),
        }
    finally:
        if tab_id:
            try:
                cdp("Target.closeTarget", targetId=tab_id)
                log("Closed the LinkedIn tab opened for this run.")
            except Exception as exc:
                log(f"Could not close the LinkedIn tab automatically: {exc}")


def run_profile_case(url, days):
    tab_id = None
    try:
        log("Opening the LinkedIn profile...")
        tab_id = new_tab(url)
        wait_for_load()
        time.sleep(3)
        require_safe_page()
        profile = extract_compose_url_from_profile()
        compose_url = profile.get("compose_url")
        if not compose_url:
            raise RuntimeError("Could not find a Message button for this LinkedIn profile.")
        log("Opening the profile's Message view to locate the existing conversation...")
        cdp("Page.navigate", url=compose_url)
        wait_for_load()
        time.sleep(5)
        require_safe_page()
        resource = extract_message_api_resource()
        api_result = None
        if resource.get("conversation_urn"):
            log("Reading messages through LinkedIn's first-party messaging API...")
            api_result = fetch_messages_api(
                conversation_urn=resource.get("conversation_urn"),
                query_id=resource.get("query_id") or MESSENGER_MESSAGES_QUERY_ID,
            )
        if api_result and api_result.get("ok"):
            all_messages = api_result.get("messages") or []
            method = "linkedin_first_party_api_after_profile_message_view"
        else:
            log("Falling back to visible message extraction...")
            all_messages = extract_dom_messages(compose_url)
            method = "linkedin_visible_dom"
        selected = attach_markdown(filter_messages(all_messages, days))
        return {
            "success": True,
            "input_url": url,
            "days": days,
            "method": method,
            "profile_name": profile.get("profile_name"),
            "conversation_urn": (api_result or {}).get("conversation_urn") or resource.get("conversation_urn"),
            "query_id": (api_result or {}).get("query_id") or resource.get("query_id"),
            "message_count": len(selected),
            "fetched_message_count": len(all_messages),
            "possibly_truncated": possibly_truncated(all_messages, days),
            "messages": selected,
            "message_history_markdown": "\n".join(message.get("markdown", "") for message in selected),
        }
    finally:
        if tab_id:
            try:
                cdp("Target.closeTarget", targetId=tab_id)
                log("Closed the LinkedIn tab opened for this run.")
            except Exception as exc:
                log(f"Could not close the LinkedIn tab automatically: {exc}")


def normalize_days(value):
    if value is None or value == "":
        return None
    number = int(value)
    if number < 0:
        raise ValueError("days must be null or a non-negative integer")
    return number


def clean_optional_url(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() == "null":
        return None
    return value


def resolve_case_url(case):
    profile_url = clean_optional_url(case.get("profile_url"))
    thread_url = clean_optional_url(case.get("thread_url"))
    legacy_url = clean_optional_url(case.get("url"))
    if legacy_url and not profile_url and not thread_url:
        if is_thread_url(legacy_url):
            thread_url = legacy_url
        else:
            profile_url = legacy_url
    provided = [value for value in [profile_url, thread_url] if value]
    if len(provided) != 1:
        raise ValueError("Provide exactly one of 'profile_url' or 'thread_url'. Do not provide both and do not leave both null.")
    url = provided[0]
    if "linkedin.com" not in url:
        raise ValueError("The URL must be a linkedin.com URL.")
    if thread_url and not is_thread_url(thread_url):
        raise ValueError("'thread_url' must be a LinkedIn messaging thread URL.")
    if profile_url and is_thread_url(profile_url):
        raise ValueError("'profile_url' must be a LinkedIn profile URL, not a messaging thread URL.")
    return profile_url, thread_url, url


def run_case(case):
    profile_url, thread_url, url = resolve_case_url(case)
    days = normalize_days(case.get("days"))
    if thread_url:
        return run_thread_case(url, days)
    return run_profile_case(url, days)


def main():
    if INPUTS.get("validation_cases"):
        cases = INPUTS["validation_cases"]
    else:
        cases = [{
            "profile_url": INPUTS.get("profile_url"),
            "thread_url": INPUTS.get("thread_url"),
            "days": INPUTS.get("days"),
        }]
    outputs = []
    for idx, case in enumerate(cases, start=1):
        name = case.get("name") or f"case_{idx}"
        log(f"Running {name}...")
        try:
            result = run_case(case)
            result["name"] = name
            outputs.append(result)
        except Exception as exc:
            outputs.append({
                "success": False,
                "name": name,
                "input_url": case.get("url") or case.get("profile_url") or case.get("thread_url"),
                "days": case.get("days"),
                "error": str(exc),
                "messages": [],
                "message_count": 0,
            })
    overall_success = all(item.get("success") for item in outputs)
    print(json.dumps({
        "success": overall_success,
        "runs": outputs,
        "run_count": len(outputs),
    }, ensure_ascii=False))


main()
'''


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-json", required=True)
    return parser.parse_args()


def load_inputs(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("inputs JSON must be an object")
    return data


def is_thread_url(url: str | None) -> bool:
    return bool(re.search(r"/messaging/thread/([^/?#]+)/?", url or ""))


def clean_optional_url(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() == "null":
        return None
    return value


def normalize_days(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("days must be null or a non-negative integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("days must be null or a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("days must be null or a non-negative integer") from exc
    if number < 0:
        raise ValueError("days must be null or a non-negative integer")
    return number


def validate_case(case: dict, name: str) -> dict:
    profile_url = clean_optional_url(case.get("profile_url"))
    thread_url = clean_optional_url(case.get("thread_url"))
    legacy_url = clean_optional_url(case.get("url"))
    if legacy_url and not profile_url and not thread_url:
        if is_thread_url(legacy_url):
            thread_url = legacy_url
        else:
            profile_url = legacy_url

    provided = [value for value in (profile_url, thread_url) if value]
    if len(provided) != 1:
        raise ValueError(
            f"{name}: provide exactly one of profile_url or thread_url. "
            "profile_url is optional, but one LinkedIn target URL is required."
        )

    url = provided[0]
    if "linkedin.com" not in url:
        raise ValueError(f"{name}: the URL must be a linkedin.com URL.")
    if thread_url and not is_thread_url(thread_url):
        raise ValueError(f"{name}: thread_url must be a LinkedIn messaging thread URL.")
    if profile_url and is_thread_url(profile_url):
        raise ValueError(f"{name}: profile_url must be a LinkedIn profile URL, not a messaging thread URL.")

    return {
        "name": name,
        "profile_url": profile_url,
        "thread_url": thread_url,
        "input_url": url,
        "days": normalize_days(case.get("days")),
    }


def validation_cases_from_inputs(inputs: dict) -> list[dict]:
    if inputs.get("validation_cases"):
        cases = inputs["validation_cases"]
        if not isinstance(cases, list):
            raise ValueError("validation_cases must be a list of input objects.")
        return cases
    return [{
        "profile_url": inputs.get("profile_url"),
        "thread_url": inputs.get("thread_url"),
        "url": inputs.get("url"),
        "days": inputs.get("days"),
    }]


def validate_inputs(inputs: dict) -> list[dict]:
    cases = validation_cases_from_inputs(inputs)
    validated = []
    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"case_{idx}: each validation case must be an object.")
        validated.append(validate_case(case, case.get("name") or f"case_{idx}"))
    return validated


def workflow_done(outputs: dict) -> None:
    print(json.dumps({"event": "workflow_done", "outputs": outputs}, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    try:
        inputs = load_inputs(args.inputs_json)
        validate_inputs(inputs)
    except Exception as exc:
        message = str(exc)
        workflow_done({
            "success": False,
            "validation_message": message,
            "error": message,
            "runs": [],
            "run_count": 0,
        })
        return 0

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN") or "/Users/prakharjain/Library/Application Support/AI Mime/bin/browser-harness"
    env = os.environ.copy()
    env["AI_MIME_LINKEDIN_INPUTS_JSON"] = json.dumps(inputs)
    log("Starting LinkedIn message history fetch...")
    proc = subprocess.run(
        [harness_bin, "-c", INNER_SCRIPT],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout = proc.stdout.strip()
    try:
        result = json.loads(stdout.splitlines()[-1])
    except Exception as exc:
        log(f"Could not parse browser result: {exc}")
        if stdout:
            log(stdout)
        workflow_done({
            "success": False,
            "error": "Could not parse the browser automation result.",
            "detail": str(exc),
            "runs": [],
            "run_count": 0,
        })
        return 0
    workflow_done(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
