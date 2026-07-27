import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlparse


VALID_STATUSES = {"sent", "pending", "already_connected", "failed"}


def log(message):
    print(message, file=sys.stderr, flush=True)


def load_inputs(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("inputs JSON must be an object")
    profile_url = str(data.get("profile_url") or "").strip()
    custom_note = str(data.get("custom_note") or "")
    if not profile_url:
        raise ValueError("Missing required input: profile_url")
    parsed = urlparse(profile_url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or (hostname != "linkedin.com" and not hostname.endswith(".linkedin.com")):
        raise ValueError("profile_url must be a LinkedIn URL")
    return {"profile_url": profile_url, "custom_note": custom_note}


def browser_script(profile_url, custom_note):
    profile_literal = json.dumps(profile_url)
    note_literal = json.dumps(custom_note)
    parsed = urlparse(profile_url)
    parts = [part for part in parsed.path.split("/") if part]
    vanity_name = parts[1] if len(parts) >= 2 and parts[0] == "in" else ""
    vanity_literal = json.dumps(vanity_name)
    template = r"""
import json
import sys
import time

PROFILE_URL = __PROFILE_URL__
CUSTOM_NOTE = __CUSTOM_NOTE__
VANITY_NAME = __VANITY_NAME__


def log(message):
    print(message, file=sys.stderr, flush=True)


def normalize(value):
    return " ".join((value or "").split())


def ax_value(node, key):
    value = node.get(key)
    if isinstance(value, dict):
        return value.get("value", "") or ""
    return value or ""


def ax_tree():
    return cdp("Accessibility.getFullAXTree").get("nodes", [])


def find_ax_node(role=None, name=None):
    for node in ax_tree():
        node_role = ax_value(node, "role")
        node_name = ax_value(node, "name")
        if role is not None and node_role != role:
            continue
        if name is not None and node_name != name:
            continue
        return node
    return None


def invite_modal_ax_node():
    return find_ax_node(role="dialog", name="Add a note to your invitation?")


def click_ax_node(node):
    backend_id = node.get("backendDOMNodeId")
    if not backend_id:
        return False
    resolved = cdp("DOM.resolveNode", backendNodeId=backend_id)
    object_id = ((resolved.get("object") or {}).get("objectId"))
    if object_id:
        try:
            cdp(
                "Runtime.callFunctionOn",
                objectId=object_id,
                functionDeclaration="function(){ this.click(); return true; }",
                awaitPromise=True,
            )
            return True
        except Exception as exc:
            log(f"Accessible button DOM click failed: {exc}")
    try:
        model = cdp("DOM.getBoxModel", backendNodeId=backend_id).get("model") or {}
        quad = model.get("border") or model.get("content") or []
        if len(quad) >= 8:
            xs = quad[0::2]
            ys = quad[1::2]
            click_at_xy(sum(xs) / len(xs), sum(ys) / len(ys))
            return True
    except Exception as exc:
        log(f"Accessible button coordinate click failed: {exc}")
    return False


def click_invite_modal_button(name):
    modal = invite_modal_ax_node()
    if not modal:
        return False
    node = find_ax_node(role="button", name=name)
    if not node:
        return False
    return click_ax_node(node)


def any_invite_dialog_ax_node():
    # After clicking "Add a note", the dialog name drops the trailing "?"
    # (becomes "Add a note to your invitation"), so match on the prefix.
    for node in ax_tree():
        if ax_value(node, "role") == "dialog":
            name = ax_value(node, "name") or ""
            if name.startswith("Add a note to your invitation"):
                return node
    return invite_modal_ax_node()


def click_invite_dialog_button(name):
    if not any_invite_dialog_ax_node():
        return False
    node = find_ax_node(role="button", name=name)
    if not node:
        return False
    return click_ax_node(node)


def note_textbox_object_id():
    # The custom-note textarea lives only in Chrome's Accessibility tree
    # (page-level document.querySelectorAll cannot reach it), exposed as a
    # textbox described with the 300-character personal-note guidance.
    for node in ax_tree():
        if ax_value(node, "role") != "textbox":
            continue
        name = (ax_value(node, "name") or "").lower()
        if "personal note" in name or "300 char" in name:
            backend = node.get("backendDOMNodeId")
            if not backend:
                continue
            try:
                resolved = cdp("DOM.resolveNode", backendNodeId=backend)
            except Exception:
                continue
            object_id = ((resolved.get("object") or {}).get("objectId"))
            if object_id:
                return object_id
    return None


def set_note_via_ax(text):
    object_id = note_textbox_object_id()
    if not object_id:
        return None
    set_fn = (
        "function(text){"
        "this.focus();"
        "this.scrollIntoView({block:'center'});"
        "var proto = this.tagName==='TEXTAREA'"
        "? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
        "var setter = Object.getOwnPropertyDescriptor(proto,'value').set;"
        "setter.call(this, text);"
        "this.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));"
        "this.dispatchEvent(new Event('change',{bubbles:true}));"
        "return this.value;"
        "}"
    )
    try:
        res = cdp(
            "Runtime.callFunctionOn",
            objectId=object_id,
            functionDeclaration=set_fn,
            arguments=[{"value": text}],
            returnByValue=True,
        )
    except Exception as exc:
        log(f"Accessible note textbox set failed: {exc}")
        return None
    return ((res.get("result") or {}).get("value")) or ""


def close_opened_tab(opened_target_id):
    ids = []
    if opened_target_id:
        ids.append(opened_target_id)
    try:
        for tab in list_tabs(include_chrome=False):
            tab_id = tab.get("id") or tab.get("targetId")
            tab_url = tab.get("url") or ""
            if tab_id and tab_id not in ids and tab_url.rstrip("/") == PROFILE_URL.rstrip("/"):
                ids.append(tab_id)
    except Exception:
        pass
    for target_id in ids:
        try:
            cdp("Target.closeTarget", targetId=target_id)
            return
        except Exception as exc:
            log(f"Could not close LinkedIn tab cleanly: {exc}")


def keep_tab_open_with_error(opened_target_id, message):
    if opened_target_id:
        try:
            cdp("Target.activateTarget", targetId=opened_target_id)
        except Exception:
            pass
    payload = json.dumps({"message": message})
    try:
        js(r'''
(args => {
  const id = 'ai-mime-linkedin-error-banner';
  const existing = document.getElementById(id);
  if (existing) existing.remove();
  const banner = document.createElement('div');
  banner.id = id;
  banner.setAttribute('role', 'alert');
  banner.style.cssText = [
    'position:fixed',
    'top:0',
    'left:0',
    'right:0',
    'z-index:2147483647',
    'background:#b42318',
    'color:white',
    'font:600 15px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
    'padding:14px 18px',
    'box-shadow:0 2px 12px rgba(0,0,0,.28)',
    'white-space:pre-wrap'
  ].join(';');
  banner.textContent = 'AI Mime could not finish this LinkedIn invite. Please check this tab.\\n' + (args.message || '');
  document.documentElement.appendChild(banner);
  document.title = 'Check LinkedIn invite - ' + document.title.replace(/^Check LinkedIn invite - /, '');
  window.scrollTo({top: 0, behavior: 'instant'});
  return true;
})(''' + payload + r''')
''')
    except Exception as exc:
        log(f"Could not add visible error message to LinkedIn tab: {exc}")


def visible_text_snapshot():
    try:
        return js('document.body ? document.body.innerText : ""') or ""
    except Exception:
        return ""


def page_state():
    return js(r'''
(() => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const topSections = Array.from(document.querySelectorAll('main section')).slice(0, 3);
  const topText = norm(topSections.map(s => s.innerText || '').join('\\n'));
  // The profile owner's own degree lives in the FIRST top-card section only.
  // It uses a middot separator ("Name · 2nd"); feed/mutual badges use a
  // bullet ("• 1st"), so scoping to the first section and the middot form
  // avoids false positives from other people's 1st-degree badges in the feed.
  const firstSection = document.querySelector('main section');
  const firstText = firstSection ? norm(firstSection.innerText || '') : '';
  let ownerDegree = '';
  const degreeMatch = firstText.match(/·\\s*(1st|2nd|3rd)\\b/i);
  if (degreeMatch) ownerDegree = degreeMatch[1].toLowerCase();
  else if (/\\b1st degree connection\\b/i.test(firstText)) ownerDegree = '1st';
  const controls = Array.from(document.querySelectorAll('main button, main a, main [role="button"]'))
    .filter(visible)
    .map((el, index) => {
      const r = el.getBoundingClientRect();
      return {
        index,
        text: norm(el.innerText || el.textContent || ''),
        aria: norm(el.getAttribute('aria-label') || ''),
        role: el.getAttribute('role') || '',
        tag: el.tagName,
        top: r.top,
        left: r.left,
        width: r.width,
        height: r.height,
        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
      };
    });
  const topControls = controls.filter(c => c.top >= 0 && c.top < 760);
  return {
    url: location.href,
    title: document.title,
    bodyText: norm(document.body ? document.body.innerText : ''),
    topText,
    ownerDegree,
    controls: topControls
  };
})()
''')


def click_control(label, mode="exact", top_only=True):
    args = json.dumps({"label": label, "mode": mode, "topOnly": top_only})
    return js(r'''
(args => {
  const label = args.label.toLowerCase();
  const mode = args.mode;
  const topOnly = args.topOnly;
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const clickable = el => el.closest('button, a, [role="button"], [role="menuitem"]') || el;
  const nodes = Array.from(document.querySelectorAll('main button, main a, main [role="button"], button, a[role="button"], a[href*="/preload/custom-invite"], [role="button"], [role="menuitem"]'));
  const matches = [];
  for (const el of nodes) {
    if (!visible(el)) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    const r = el.getBoundingClientRect();
    if (topOnly && (r.top < 0 || r.top > 760)) continue;
    const text = norm(el.innerText || el.textContent || '');
    const aria = norm(el.getAttribute('aria-label') || '');
    const haystacks = [text, aria].map(s => s.toLowerCase()).filter(Boolean);
    const href = el.getAttribute('href') || '';
    if (label === 'connect' && href.includes('/preload/custom-invite')) {
      haystacks.push('connect');
    }
    const matched = haystacks.some(s => mode === 'exact' ? s === label : s.includes(label));
    if (!matched) continue;
    matches.push({el, text, aria, href, top: r.top, left: r.left});
  }
  if (!matches.length) return {clicked: false};
  if (label === 'connect') {
    matches.sort((a, b) => {
      const aMain = a.top > 100 && a.top < 650 ? 0 : 1;
      const bMain = b.top > 100 && b.top < 650 ? 0 : 1;
      return aMain - bMain || a.top - b.top || a.left - b.left;
    });
  } else {
    matches.sort((a, b) => a.top - b.top || a.left - b.left);
  }
  const match = matches[0];
  const target = clickable(match.el);
  target.scrollIntoView({block: 'center', inline: 'center'});
  const href = target.href || match.href || '';
  if (label === 'connect' && href.includes('/preload/custom-invite')) {
    window.location.href = href;
    return {clicked: true, navigated: true, text: match.text, aria: match.aria, href};
  }
  target.click();
  return {clicked: true, text: match.text, aria: match.aria, href};
  return {clicked: false};
})(''' + args + r''')
''')


def find_profile_invite_action():
    args = json.dumps({"vanityName": VANITY_NAME})
    return js(r'''
(args => {
  const vanityName = args.vanityName;
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const anchors = Array.from(document.querySelectorAll('main a[href*="/preload/custom-invite"]'));
  const matches = [];
  for (const el of anchors) {
    if (!visible(el)) continue;
    let href = el.getAttribute('href') || '';
    let parsed = null;
    try {
      parsed = new URL(href, location.origin);
    } catch (_) {
      continue;
    }
    if (vanityName && parsed.searchParams.get('vanityName') !== vanityName) continue;
    const r = el.getBoundingClientRect();
    matches.push({
      href: parsed.href,
      text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
      aria: (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim(),
      top: r.top,
      left: r.left,
      x: r.left + r.width / 2,
      y: r.top + r.height / 2
    });
  }
  if (!matches.length) return {found: false};
  matches.sort((a, b) => {
    const aMain = a.left < 760 && a.top > 100 && a.top < 650 ? 0 : 1;
    const bMain = b.left < 760 && b.top > 100 && b.top < 650 ? 0 : 1;
    return aMain - bMain || a.top - b.top || a.left - b.left;
  });
  return {found: true, match: matches[0]};
})(''' + args + r''')
''')


def invitation_prompt_ready():
    if invite_modal_ax_node():
        return True
    return bool(js(r'''
(() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .artdeco-modal, .artdeco-modal-overlay')).filter(visible);
  if (!dialogs.length) return false;
  if (dialogs.some(dialog => Array.from(dialog.querySelectorAll('textarea, [contenteditable="true"]')).some(visible))) return true;
  return dialogs.some(dialog => Array.from(dialog.querySelectorAll('button, a, [role="button"]'))
    .filter(visible)
    .some(el => {
      const value = norm((el.innerText || el.textContent || '') + ' ' + (el.getAttribute('aria-label') || ''));
      return value.includes('add a note') || value.includes('send without a note') || value === 'send' || value.includes('send invitation');
    }));
})()
'''))


def click_profile_invite_action():
    action = find_profile_invite_action()
    if not action.get("found"):
        return False
    match = action["match"]
    log("Opening invite dialog...")
    click_at_xy(match["x"], match["y"])
    for _ in range(12):
        time.sleep(0.5)
        if invitation_prompt_ready():
            return True
    return False


def find_status():
    state = page_state()
    top_text = normalize(state.get("topText", ""))
    body_text = normalize(state.get("bodyText", ""))
    controls = state.get("controls") or []
    lower_top = top_text.lower()
    lower_body = body_text.lower()
    def pending_profile_action(control):
        left = control.get("left")
        if left is not None and left > 760:
            return False
        text = normalize(control.get("text", "")).lower()
        aria = normalize(control.get("aria", "")).lower()
        values = {text, aria}
        return (
            "pending" in values
            or "invitation pending" in values
            or any(value.startswith("pending ") for value in values)
        )
    if "/login" in state.get("url", "") or ("sign in" in lower_body and "email or phone" in lower_body):
        return {"status": "failed", "message": "LinkedIn login is required before this skill can run."}
    if "this profile is not available" in lower_body or "page doesn't exist" in lower_body:
        return {"status": "failed", "message": "The LinkedIn profile did not load or is unavailable."}
    if any(pending_profile_action(control) for control in controls):
        return {"status": "pending", "message": "A connection request is already pending for this profile."}
    owner_degree = normalize(state.get("ownerDegree", "")).lower()
    if owner_degree == "1st":
        return {"status": "already_connected", "message": "This profile is already connected."}
    return {"status": None, "message": "", "state": state}


def click_connect():
    def clicked_connect(result):
        if not result.get("clicked"):
            return False
        if result.get("navigated"):
            wait_for_load()
            time.sleep(2.0)
        return True

    log("Looking for Connect...")
    if click_profile_invite_action():
        return True

    result = click_control("connect", mode="exact", top_only=True)
    if clicked_connect(result):
        return True
    result = click_control("connect", mode="contains", top_only=True)
    if clicked_connect(result):
        return True

    log("Opening More menu...")
    more = click_control("more", mode="exact", top_only=True)
    if not more.get("clicked"):
        more = click_control("more", mode="contains", top_only=True)
    if not more.get("clicked"):
        return False
    time.sleep(1.0)
    result = click_control("connect", mode="exact", top_only=False)
    if clicked_connect(result):
        return True
    result = click_control("connect", mode="contains", top_only=False)
    return clicked_connect(result)


def focus_textarea():
    return js(r'''
(() => {
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const area = Array.from(document.querySelectorAll('textarea, [contenteditable="true"]')).find(visible);
  if (!area) return false;
  area.focus();
  return true;
})()
''')


def read_note_text():
    return js(r'''
(() => {
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const area = Array.from(document.querySelectorAll('textarea, [contenteditable="true"]')).find(visible);
  if (!area) return null;
  return area.value !== undefined ? area.value : area.innerText;
})()
''')


def set_note_text_direct(text):
    payload = json.dumps(text)
    return js(r'''
(text => {
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const area = Array.from(document.querySelectorAll('textarea, [contenteditable="true"]')).find(visible);
  if (!area) return false;
  area.focus();
  if (area.value !== undefined) {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    if (setter) setter.call(area, text);
    else area.value = text;
  } else {
    area.textContent = text;
  }
  area.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
  area.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
})(''' + payload + r''')
''')


def type_note_human_like(text):
    if not text:
        return
    # Preferred path: the note textarea is only reachable through the
    # Accessibility tree (DOM gap), so set it directly and verify.
    ax_value_seen = set_note_via_ax(text)
    if ax_value_seen is not None and normalize(ax_value_seen) == normalize(text):
        return
    if not focus_textarea():
        # Fall back to the AX-read verification before giving up.
        if ax_value_seen is not None:
            time.sleep(0.4)
            if normalize(ax_value_seen) == normalize(text):
                return
        raise RuntimeError("Could not find the note text box.")
    time.sleep(0.25)
    try:
        cdp("Input.insertText", text=text)
    except Exception:
        for ch in text:
            cdp("Input.dispatchKeyEvent", type="char", text=ch, unmodifiedText=ch)
            time.sleep(0.02)
    time.sleep(0.4)
    if normalize(read_note_text()) != normalize(text):
        if not set_note_text_direct(text):
            raise RuntimeError("Could not set the note text.")
        time.sleep(0.4)
    if normalize(read_note_text()) != normalize(text):
        raise RuntimeError("The note text did not appear correctly in LinkedIn.")


def click_send_button():
    for _ in range(12):
        if click_invite_dialog_button("Send invitation"):
            return True
        if click_invite_dialog_button("Send"):
            return True
        if click_invite_modal_button("Send"):
            return True
        if click_invite_modal_button("Send invitation"):
            return True
        send = click_control("send", mode="exact", top_only=False)
        if send.get("clicked"):
            return True
        send = click_control("send invitation", mode="contains", top_only=False)
        if send.get("clicked"):
            return True
        time.sleep(0.5)
    return False


def handle_invitation_modal():
    time.sleep(1.5)
    if CUSTOM_NOTE.strip():
        if click_invite_modal_button("Add a note"):
            time.sleep(0.8)
        else:
            add_note = click_control("add a note", mode="contains", top_only=False)
            if add_note.get("clicked"):
                time.sleep(0.8)
        log("Typing note...")
        type_note_human_like(CUSTOM_NOTE)
        time.sleep(0.4)
        return click_send_button()

    if click_invite_modal_button("Send without a note"):
        return True
    send_without = click_control("send without a note", mode="contains", top_only=False)
    if send_without.get("clicked"):
        return True
    send_now = click_control("send", mode="exact", top_only=False)
    if send_now.get("clicked"):
        return True
    done = click_control("done", mode="exact", top_only=False)
    return bool(done.get("clicked"))


def refresh_profile_and_find_status():
    log("Checking profile status...")
    cdp("Page.navigate", url=PROFILE_URL)
    wait_for_load()
    time.sleep(3.0)
    status = find_status()
    if not status.get("status"):
        time.sleep(2.0)
        status = find_status()
    return status


def run():
    opened_target_id = None
    result = None
    try:
        log("Opening LinkedIn profile...")
        opened_target_id = new_tab(PROFILE_URL)
        wait_for_load()
        time.sleep(3.0)

        status = find_status()
        if status.get("status"):
            result = status
            return result

        if not click_connect():
            refreshed = find_status()
            if refreshed.get("status"):
                result = refreshed
                return result
            result = {"status": "failed", "message": "Could not find a Connect action on this profile."}
            return result

        if not handle_invitation_modal():
            refreshed = find_status()
            if refreshed.get("status"):
                result = refreshed
                return result
            result = {"status": "failed", "message": "Connect was clicked, but the Send action was not available."}
            return result

        time.sleep(2.0)
        refreshed = refresh_profile_and_find_status()
        if refreshed.get("status") == "pending":
            result = {"status": "sent", "message": "Connection request sent; the direct profile page now shows Pending."}
            return result
        if refreshed.get("status") == "failed":
            result = {
                "status": "failed",
                "message": "Connection request may have been sent, but the direct profile check failed: "
                + refreshed.get("message", "unknown status check error"),
            }
            return result
        result = {
            "status": "failed",
            "message": "Send was clicked, but the refreshed direct profile page did not show Pending. Please check this LinkedIn tab.",
        }
        return result
    except Exception as exc:
        result = {"status": "failed", "message": f"LinkedIn connection request failed: {exc}"}
        return result
    finally:
        if result and result.get("status") == "failed":
            keep_tab_open_with_error(opened_target_id, result.get("message", "Unknown error"))
        elif opened_target_id:
            close_opened_tab(opened_target_id)


result = run()
if result.get("status") not in {"sent", "pending", "already_connected", "failed"}:
    result = {"status": "failed", "message": "Skill returned an invalid status."}
print(json.dumps(result, ensure_ascii=False), flush=True)
"""
    return (
        template
        .replace("__PROFILE_URL__", profile_literal)
        .replace("__CUSTOM_NOTE__", note_literal)
        .replace("__VANITY_NAME__", vanity_literal)
    )


def run_browser_automation(inputs):
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is required")
    script = browser_script(inputs["profile_url"], inputs["custom_note"])
    cmd = [harness_bin, "-c", script]
    log("Running browser automation...")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"browser automation failed with exit code {proc.returncode}")
    if not stdout:
        raise RuntimeError("browser automation returned no result")
    last_line = stdout.splitlines()[-1]
    try:
        result = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"browser automation returned invalid JSON: {exc}") from exc
    if result.get("status") not in VALID_STATUSES:
        raise RuntimeError("browser automation returned an invalid status")
    return result


def main():
    parser = argparse.ArgumentParser(description="Send a LinkedIn connection request.")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        inputs = load_inputs(args.inputs_json)
        result = run_browser_automation(inputs)
        log(result.get("message", "Done."))
        print(json.dumps({"event": "workflow_done", "outputs": result}, ensure_ascii=False), flush=True)
        if result.get("status") == "failed":
            sys.exit(1)
    except Exception as exc:
        result = {"status": "failed", "message": str(exc)}
        print(json.dumps({"event": "workflow_done", "outputs": result}, ensure_ascii=False), flush=True)
        log(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
