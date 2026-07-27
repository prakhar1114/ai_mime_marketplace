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


INPUTS = json.loads(os.environ["AI_MIME_LINKEDIN_INPUTS_JSON"])


def log(message):
    print(message, file=sys.stderr, flush=True)


def is_thread_url(url):
    return bool(re.search(r"/messaging/thread/([^/?#]+)/?", url or ""))


def check_page_state():
    return js(r"""
    (() => {
      const text = document.body ? document.body.innerText.slice(0, 3000) : "";
      const login = /sign in|join now|email or phone|password/i.test(text) && /linkedin/i.test(text);
      const checkpoint = /security check|checkpoint|captcha|verify|unusual activity|temporarily restricted|rate limit/i.test(text);
      return {href: location.href, title: document.title, login, checkpoint};
    })()
    """)


def require_safe_page():
    state = check_page_state()
    if state.get("login"):
        raise RuntimeError("LinkedIn is showing a login page. Please log in in Chrome and rerun.")
    if state.get("checkpoint"):
        raise RuntimeError("LinkedIn is showing a security, checkpoint, or rate-limit screen. Stopping without sending.")
    return state


def wait_for_composer(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        has = js(r"""(() => !!document.querySelector('.msg-form__contenteditable'))()""")
        if has:
            return True
        time.sleep(1)
    return False


def extract_compose_url_from_profile():
    return js(r"""
    (() => {
      const links = Array.from(document.querySelectorAll('a[href*="/messaging/compose/"]'));
      const hrefs = links.map(a => a.href).filter(Boolean);
      const profileName = (document.querySelector('h1') && document.querySelector('h1').innerText.trim())
        || document.title.replace(/\s*\|\s*LinkedIn.*/, '').trim();
      return {compose_url: hrefs[0] || null, profile_name: profileName};
    })()
    """)


def fill_composer(message):
    return js(f"""
    (() => {{
      const message = {json.dumps(message)};
      const box = document.querySelector('.msg-form__contenteditable');
      if (!box) return {{ok: false, error: 'Message composer not found.'}};
      box.focus();
      box.innerHTML = '';
      const lines = String(message).split('\\n');
      for (const line of lines) {{
        const p = document.createElement('p');
        if (line.length) {{ p.textContent = line; }} else {{ p.appendChild(document.createElement('br')); }}
        box.appendChild(p);
      }}
      box.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: message}}));
      const send = document.querySelector('button.msg-form__send-button');
      return {{ok: true, send_disabled: send ? send.disabled : true, box_text: box.innerText}};
    }})()
    """)


def wait_for_send_enabled(timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        disabled = js(r"""(() => {
          const s = document.querySelector('button.msg-form__send-button');
          return s ? s.disabled : true;
        })()""")
        if not disabled:
            return True
        time.sleep(0.5)
    return False


def click_send():
    return js(r"""
    (() => {
      const send = document.querySelector('button.msg-form__send-button');
      if (!send) return {ok: false, error: 'Send button not found.'};
      if (send.disabled) return {ok: false, error: 'Send button is disabled; message did not register.'};
      send.click();
      return {ok: true};
    })()
    """)


def verify_sent(message):
    expected = " ".join(str(message).split())
    return js(f"""
    (() => {{
      const expected = {json.dumps(expected)};
      const box = document.querySelector('.msg-form__contenteditable');
      const boxEmpty = box ? !box.innerText.trim() : true;
      const items = Array.from(document.querySelectorAll('.msg-s-event-listitem__body'));
      let matched = false;
      for (let i = items.length - 1; i >= 0 && i >= items.length - 5; i--) {{
        const t = items[i].innerText.replace(/\\s+/g, ' ').trim();
        if (t === expected || t.indexOf(expected) !== -1) {{ matched = true; break; }}
      }}
      const send = document.querySelector('button.msg-form__send-button');
      return {{box_empty: boxEmpty, matched, send_disabled: send ? send.disabled : true}};
    }})()
    """)


def open_conversation(profile_url, thread_url):
    if thread_url:
        log("Opening the LinkedIn conversation...")
        tab_id = new_tab(thread_url)
        wait_for_load()
        time.sleep(4)
        require_safe_page()
        profile_name = None
    else:
        log("Opening the LinkedIn profile...")
        tab_id = new_tab(profile_url)
        wait_for_load()
        time.sleep(4)
        require_safe_page()
        profile = extract_compose_url_from_profile()
        compose_url = profile.get("compose_url")
        profile_name = profile.get("profile_name")
        if not compose_url:
            raise RuntimeError("Could not find a Message button for this LinkedIn profile.")
        log("Opening the message composer...")
        cdp("Page.navigate", url=compose_url)
        wait_for_load()
        time.sleep(5)
        require_safe_page()
    if not wait_for_composer():
        raise RuntimeError("The LinkedIn message composer did not load.")
    return tab_id, profile_name


def send_message(profile_url, thread_url, message):
    tab_id = None
    try:
        tab_id, profile_name = open_conversation(profile_url, thread_url)
        log("Typing the message...")
        filled = fill_composer(message)
        if not filled.get("ok"):
            raise RuntimeError(filled.get("error") or "Could not type the message.")
        if not wait_for_send_enabled():
            raise RuntimeError("LinkedIn did not accept the typed message (Send stayed disabled).")
        log("Sending the message...")
        clicked = click_send()
        if not clicked.get("ok"):
            raise RuntimeError(clicked.get("error") or "Could not click Send.")
        time.sleep(3)
        check = verify_sent(message)
        success = bool(check.get("box_empty") and check.get("matched"))
        if not success:
            # box cleared but not matched: treat as likely-sent-but-unverified failure
            if check.get("box_empty"):
                return {
                    "success": False,
                    "status_message": "Send was triggered but the message could not be confirmed in the thread.",
                    "profile_name": profile_name,
                }
            raise RuntimeError("Message did not send (composer still contains text).")
        return {
            "success": True,
            "status_message": "Message sent.",
            "profile_name": profile_name,
        }
    finally:
        if tab_id:
            try:
                cdp("Target.closeTarget", targetId=tab_id)
                log("Closed the LinkedIn tab opened for this run.")
            except Exception as exc:
                log(f"Could not close the LinkedIn tab automatically: {exc}")


def clean_optional_url(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() == "null":
        return None
    return value


def resolve_inputs():
    profile_url = clean_optional_url(INPUTS.get("profile_url"))
    thread_url = clean_optional_url(INPUTS.get("thread_url"))
    provided = [v for v in (profile_url, thread_url) if v]
    if len(provided) != 1:
        raise ValueError("Provide exactly one of 'profile_url' or 'thread_url'.")
    message = INPUTS.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("'message' must be a non-empty string.")
    url = provided[0]
    if "linkedin.com" not in url:
        raise ValueError("The URL must be a linkedin.com URL.")
    if thread_url and not is_thread_url(thread_url):
        raise ValueError("'thread_url' must be a LinkedIn messaging thread URL.")
    if profile_url and is_thread_url(profile_url):
        raise ValueError("'profile_url' must be a LinkedIn profile URL, not a messaging thread URL.")
    return profile_url, thread_url, message


def main():
    try:
        profile_url, thread_url, message = resolve_inputs()
    except Exception as exc:
        print(json.dumps({"success": False, "reason": str(exc), "status_message": str(exc), "error": str(exc)}, ensure_ascii=False))
        return
    try:
        result = send_message(profile_url, thread_url, message)
    except Exception as exc:
        result = {"success": False, "status_message": str(exc), "error": str(exc)}
    result.setdefault("input_url", thread_url or profile_url)
    result.setdefault("reason", result.get("status_message") or result.get("error") or "")
    print(json.dumps(result, ensure_ascii=False))


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


def is_thread_url(url):
    return bool(re.search(r"/messaging/thread/([^/?#]+)/?", url or ""))


def clean_optional_url(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() == "null":
        return None
    return value


def validate_inputs(inputs: dict) -> None:
    profile_url = clean_optional_url(inputs.get("profile_url"))
    thread_url = clean_optional_url(inputs.get("thread_url"))
    provided = [v for v in (profile_url, thread_url) if v]
    if len(provided) != 1:
        raise ValueError("Provide exactly one of profile_url or thread_url (not both, not neither).")
    message = inputs.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string.")
    url = provided[0]
    if "linkedin.com" not in url:
        raise ValueError("The URL must be a linkedin.com URL.")
    if thread_url and not is_thread_url(thread_url):
        raise ValueError("thread_url must be a LinkedIn messaging thread URL.")
    if profile_url and is_thread_url(profile_url):
        raise ValueError("profile_url must be a LinkedIn profile URL, not a messaging thread URL.")


def workflow_done(outputs: dict) -> None:
    print(json.dumps({"event": "workflow_done", "outputs": outputs}, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    try:
        inputs = load_inputs(args.inputs_json)
        validate_inputs(inputs)
    except Exception as exc:
        message = str(exc)
        workflow_done({"success": False, "reason": message, "validation_message": message, "error": message})
        return 0

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN") or \
        "/Users/prakharjain/Library/Application Support/AI Mime/bin/browser-harness"
    env = os.environ.copy()
    env["AI_MIME_LINKEDIN_INPUTS_JSON"] = json.dumps(inputs)
    log("Starting LinkedIn message send...")
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
        parse_msg = "Could not parse the browser automation result."
        workflow_done({
            "success": False,
            "reason": parse_msg,
            "status_message": parse_msg,
            "error": str(exc),
        })
        return 0
    if isinstance(result, dict):
        result.setdefault("reason", result.get("status_message") or result.get("validation_message") or result.get("error") or "")
    workflow_done(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
