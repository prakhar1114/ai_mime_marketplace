import argparse
import json
import os
import re
import subprocess
import sys
import textwrap


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


def fail(step_id, error, recoverable=False):
    log_event("step_failed", id=step_id, error=str(error), recoverable=recoverable)
    sys.exit(1)


def load_inputs(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise ValueError(f"Could not read inputs JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Inputs JSON must be an object")

    post_url = str(data.get("post_url") or data.get("link") or data.get("url") or "").strip()
    reply_text = str(data.get("reply_text") or data.get("comment") or data.get("comment_text") or "").strip()
    if not post_url:
        raise ValueError("Missing required input: post_url")
    if not reply_text:
        raise ValueError("Missing required input: reply_text")
    match = re.search(r"/status/(\d+)", post_url)
    if not match:
        raise ValueError("post_url must be an X status URL containing /status/<id>")
    return post_url, reply_text, match.group(1)


def run_harness(post_url, reply_text, original_id):
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is not configured")

    harness_code = f"""
import json, time

post_url = {json.dumps(post_url)}
reply_text = {json.dumps(reply_text)}
original_id = {json.dumps(original_id)}

def visible_editors():
    return json.loads(js(r'''
(() => {{
  return JSON.stringify(Array.from(document.querySelectorAll("div[role=textbox][data-testid^=tweetTextarea]"))
    .map((e, i) => {{
      const r = e.getBoundingClientRect();
      return {{i, text:e.innerText || "", visible:r.width > 0 && r.height > 0, x:r.x, y:r.y, w:r.width, h:r.height}};
    }})
    .filter(e => e.visible));
}})()
'''))

def visible_reply_buttons():
    return json.loads(js(r'''
(() => {{
  return JSON.stringify(Array.from(document.querySelectorAll("button[data-testid=tweetButtonInline], button[data-testid=tweetButton]"))
    .map((b, i) => {{
      const r = b.getBoundingClientRect();
      return {{i, testid:b.getAttribute("data-testid"), text:b.innerText || "", disabled:b.disabled || b.getAttribute("aria-disabled") === "true", visible:r.width > 0 && r.height > 0, x:r.x, y:r.y, w:r.width, h:r.height}};
    }})
    .filter(b => b.visible));
}})()
'''))

def page_text():
    return js("document.body ? document.body.innerText.slice(0, 2000) : ''")

new_tab(post_url)
wait_for_load(30)
wait(5)

deadline = time.time() + 25
editors = []
while time.time() < deadline:
    editors = visible_editors()
    if editors:
        break
    wait(0.5)

if not editors:
    text = page_text()
    if "Sign in" in text or "Log in" in text:
        raise RuntimeError("X is asking for login. Sign in to X in Chrome and rerun the skill.")
    raise RuntimeError("Could not find a visible X reply composer for this post.")

js(r'''
(() => {{
  const e = document.querySelector("div[role=textbox][data-testid^=tweetTextarea]");
  if (e) e.scrollIntoView({{block: "center", inline: "nearest"}});
}})()
''')
wait(1)
editors = visible_editors()
if not editors:
    raise RuntimeError("Reply composer disappeared after scrolling.")

editor = editors[0]
click_at_xy(editor["x"] + min(30, max(5, editor["w"] / 2)), editor["y"] + min(16, max(5, editor["h"] / 2)))
wait(0.4)

select_all = {{"key": "a", "code": "KeyA", "modifiers": 4, "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65}}
cdp("Input.dispatchKeyEvent", type="rawKeyDown", **select_all)
cdp("Input.dispatchKeyEvent", type="keyUp", **select_all)
press_key("Backspace")
wait(0.2)
type_text(reply_text)
wait(1)

draft_ok = False
for editor in visible_editors():
    if editor.get("text", "").strip() == reply_text:
        draft_ok = True
        break
if not draft_ok:
    raise RuntimeError("Reply text was not entered into the X composer.")

buttons = visible_reply_buttons()
enabled = [b for b in buttons if b.get("testid") in ("tweetButtonInline", "tweetButton") and not b.get("disabled")]
if not enabled:
    raise RuntimeError("Reply button did not become enabled after entering text.")

press_key("Enter", modifiers=4)
wait(3)

# If Cmd+Return did not submit, click the enabled Reply button.
still_draft = any(e.get("text", "").strip() == reply_text for e in visible_editors())
if still_draft:
    buttons = visible_reply_buttons()
    enabled = [b for b in buttons if b.get("testid") in ("tweetButtonInline", "tweetButton") and not b.get("disabled")]
    if enabled:
        b = enabled[0]
        click_at_xy(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)

wait_for_network_idle(timeout=20, idle_ms=800)

reply_url = None
for _ in range(60):
    expr = r'''
(() => {{
  const replyText = __REPLY_TEXT__;
  const originalId = __ORIGINAL_ID__;
  const norm = s => (s || '').replace(/\\\\s+/g, ' ').trim();
  const articles = Array.from(document.querySelectorAll('article'));
  for (const article of articles) {{
    const text = norm(article.innerText);
    if (!text.includes(replyText)) continue;
    const hrefs = Array.from(article.querySelectorAll('a[href*="/status/"]')).map(a => a.href.split('?')[0]);
    const candidate = hrefs.find(h => h.includes('/status/') && !h.includes('/status/' + originalId));
    if (candidate) return candidate;
  }}
  return null;
}})()
'''.replace("__REPLY_TEXT__", json.dumps(reply_text)).replace("__ORIGINAL_ID__", json.dumps(original_id))
    found = js(expr)
    if found:
        reply_url = found
        break
    wait(0.5)

if not reply_url:
    raise RuntimeError("Reply was submitted, but the new reply URL could not be found on the page.")

print("RESULT_JSON " + json.dumps({{"reply_url": reply_url}}, ensure_ascii=False), flush=True)
"""

    proc = subprocess.run(
        [harness_bin, "-c", textwrap.dedent(harness_code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"browser-harness failed: {detail}")

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT_JSON "):
            return json.loads(line.removeprefix("RESULT_JSON "))
    raise RuntimeError(f"browser-harness did not return RESULT_JSON. stdout={proc.stdout!r}")


def main():
    parser = argparse.ArgumentParser(description="Reply to an X post/comment and return the reply URL.")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        log_event("step_start", id="load_inputs", title="Load inputs")
        post_url, reply_text, original_id = load_inputs(args.inputs_json)
        log_event(
            "step_done",
            id="load_inputs",
            outputs={"post_url": post_url, "reply_text_length": len(reply_text)},
            summary="Inputs loaded",
        )
    except Exception as exc:
        fail("load_inputs", exc, recoverable=True)

    try:
        log_event("step_start", id="post_reply", title="Post reply on X")
        result = run_harness(post_url, reply_text, original_id)
        log_event("step_done", id="post_reply", outputs=result, summary="Reply posted")
        log_event("workflow_done", outputs=result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:
        fail("post_reply", exc, recoverable=True)


if __name__ == "__main__":
    main()
