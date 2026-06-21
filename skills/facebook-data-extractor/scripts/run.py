#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def log_event(event, **payload):
    message = {"event": event, **payload}
    print(json.dumps(message, ensure_ascii=False), file=sys.stderr, flush=True)


def fail(step_id, error, recoverable=False):
    log_event("step_failed", id=step_id, error=str(error), recoverable=recoverable)
    raise SystemExit(1)


def load_inputs(path):
    with open(path, "r", encoding="utf-8") as fh:
        inputs = json.load(fh)
    group_url = str(inputs.get("group_url", "")).strip()
    if not re.match(r"^https://(www\.)?facebook\.com/groups/[^/?#]+", group_url):
        raise ValueError("Input 'group_url' must be a Facebook group URL.")
    days = int(inputs.get("days", 0))
    if days < 1 or days > 365:
        raise ValueError("Input 'days' must be an integer from 1 to 365.")
    result = {"group_url": group_url, "days": days}
    if inputs.get("max_scrolls") is not None:
        max_scrolls = int(inputs.get("max_scrolls"))
        if max_scrolls < 5 or max_scrolls > 500:
            raise ValueError("Input 'max_scrolls' must be an integer from 5 to 500 when provided.")
        result["max_scrolls"] = max_scrolls
    if inputs.get("max_hydration_pages") is not None:
        max_hydration_pages = int(inputs.get("max_hydration_pages"))
        if max_hydration_pages < 0 or max_hydration_pages > 100:
            raise ValueError("Input 'max_hydration_pages' must be an integer from 0 to 100 when provided.")
        result["max_hydration_pages"] = max_hydration_pages
    return result


def output_dir():
    env_dir = os.environ.get("AI_MIME_OUTPUT_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parents[3] / "outputs"


def extract_group_id(url):
    match = re.search(r"/groups/([^/?#]+)", url)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", match.group(1)) if match else "facebook_group"


BROWSER_SCRIPT = r'''
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

payload = json.loads(os.environ["AI_MIME_FB_EXTRACT_INPUT"])
group_url = payload["group_url"]
days = int(payload["days"])
max_scrolls_override = payload.get("max_scrolls")
max_hydration_pages_override = payload.get("max_hydration_pages")

now = datetime.now(timezone.utc)
cutoff = now - timedelta(days=days)

def compact(value):
    return re.sub(r"\s+", " ", value or "").strip()

def parse_facebook_time(value):
    text = compact(value).lower()
    if not text:
        return None
    text = text.replace("updated ", "").replace("posted ", "")
    m = re.search(r"\b(\d+)\s*(m|min|mins|minute|minutes)\b", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.search(r"\b(\d+)\s*(h|hr|hrs|hour|hours)\b", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.search(r"\b(\d+)\s*(d|day|days)\b", text)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.search(r"\b(\d+)\s*(w|week|weeks)\b", text)
    if m:
        return now - timedelta(weeks=int(m.group(1)))
    m = re.search(r"\byesterday\s+at\s+(\d{1,2}):(\d{2})\s*([ap]m)\b", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "yesterday" in text:
        return now - timedelta(days=1)
    if "just now" in text or "now" == text:
        return now
    for fmt in ("%B %d at %I:%M %p", "%b %d at %I:%M %p", "%B %d", "%b %d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text.title(), fmt)
            parsed = parsed.replace(year=now.year, tzinfo=timezone.utc)
            if parsed > now + timedelta(days=1):
                parsed = parsed.replace(year=now.year - 1)
            return parsed
        except ValueError:
            pass
    for fmt in ("%B %d, %Y at %I:%M %p", "%b %d, %Y at %I:%M %p", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.title(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def visible_posts(group_id):
    js_group_id = json.dumps(group_id)
    return js(r"""
(() => {
  const compact = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const groupId = GROUP_ID_PLACEHOLDER;
  const visibleRoots = () => {
    const roots = [];
    const seen = new Set();
    const xs = [0.35, 0.45, 0.55, 0.65].map((ratio) => Math.floor(window.innerWidth * ratio));
    const ys = [];
    for (let y = 120; y < window.innerHeight - 40; y += 120) ys.push(y);
    for (const x of xs) {
      for (const y of ys) {
        let node = document.elementFromPoint(x, y);
        let candidate = null;
        for (let depth = 0; node && depth < 18; depth += 1, node = node.parentElement) {
          const rect = node.getBoundingClientRect();
          if (rect.width < 280 || rect.height < 60) continue;
          if (node.getAttribute('role') === 'article') {
            candidate = node;
            break;
          }
          const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
          if (!text) continue;
          if (/Like|Comment|Share/.test(text) && text.length > 30 && rect.height < 1400) {
            candidate = node;
          }
        }
        if (candidate && !seen.has(candidate)) {
          seen.add(candidate);
          roots.push(candidate);
        }
      }
    }
    return roots;
  };
  const cleanPostText = (text) => compact(
    text
      .replace(/\bLike\b.*$/s, '')
      .replace(/\bWrite a public comment.*$/s, '')
      .replace(/\bSee more\b/g, '')
      .replace(/^Facebook\s+/g, '')
  );
  const visibleLinkText = (a) => {
    const ar = a.getBoundingClientRect();
    const spans = Array.from(a.querySelectorAll('span'));
    if (spans.length === 0) {
      return compact(a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || a.textContent);
    }
    const chars = spans
      .filter((s) => s.children.length === 0 && s.textContent && s.textContent.length <= 2)
      .map((s) => {
        const r = s.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return null;
        if (r.y < ar.y - 1 || r.y > ar.y + ar.height + 1 || r.x < ar.x - 1 || r.x > ar.x + ar.width + 1) return null;
        const cs = getComputedStyle(s);
        return {text: s.textContent, x: r.x, y: r.y, w: r.width, h: r.height, display: cs.display, visibility: cs.visibility, opacity: cs.opacity};
      })
      .filter((c) =>
        c &&
        c.display !== 'none' &&
        c.visibility !== 'hidden' &&
        c.opacity !== '0'
      )
      .sort((a, b) => (a.y - b.y) || (a.x - b.x))
      .map((c) => c.text)
      .join('');
    return compact(chars || a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || a.textContent);
  };
  const fallbackBody = (fullText, author) => {
    let text = fullText.replace(/Facebook\s+/g, ' ');
    if (author) text = text.replaceAll(author, ' ');
    const afterDot = text.includes('·') ? text.split('·').slice(-1)[0] : text;
    return cleanPostText(afterDot);
  };
  const roots = visibleRoots();

  return roots.map((article, index) => {
    const rect = article.getBoundingClientRect();
    const text = compact(article.innerText);
    const anchors = Array.from(article.querySelectorAll('a[href]')).map((a) => ({
      text: compact(a.innerText || a.getAttribute('aria-label') || ''),
      aria: compact(a.getAttribute('aria-label') || ''),
      title: compact(a.getAttribute('title') || ''),
      href: a.href || ''
    }));
    const authorLink = anchors.find((a) => /\/groups\/[^/]+\/user\//.test(a.href) && (a.aria || a.text)) ||
      anchors.find((a) => a.text && !/facebook|like|comment|share|view|photo/i.test(a.text));
    const authorName = authorLink ? compact(authorLink.aria || authorLink.text) : null;
    let body = Array.from(article.querySelectorAll('[data-ad-comet-preview="message"], [data-ad-preview="message"]'))
      .map((node) => cleanPostText(node.innerText))
      .filter(Boolean)
      .sort((a, b) => b.length - a.length)[0] || '';
    if (!body) body = fallbackBody(text, authorName);

    let timestampText = null;
    const rawTimeLink = Array.from(article.querySelectorAll('a[href]')).find((a) => {
      const r = a.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0 && r.width < 160)) return false;
      if (/\/user\/|\/profile\.php/.test(a.href || '')) return false;
      const visual = visibleLinkText(a);
      if (/\b(?:\d+\s*[mhdw]?|yesterday|now)\b/i.test(visual)) {
        timestampText = visual;
        return true;
      }
      return false;
    });
    const postLink = anchors.find((a) => /\/posts\/|permalink|story_fbid|multi_permalinks/.test(a.href));
    const postIdFromPhoto = anchors.map((link) => /[?&]set=pcb\.(\d+)/.exec(link.href)).find(Boolean);
    return {
      index,
      text: body,
      author: authorName,
      url: postLink ? postLink.href : (postIdFromPhoto ? `https://www.facebook.com/groups/${groupId}/posts/${postIdFromPhoto[1]}/` : null),
      anchors,
      time_candidates: timestampText ? [{text: timestampText, aria: "", title: "", href: rawTimeLink ? rawTimeLink.href : ""}] : [],
      top: rect.top,
      height: rect.height
    };
  }).filter((item) => item.text.length > 10 || item.url);
})()
""".replace("GROUP_ID_PLACEHOLDER", js_group_id))

def expand_visible_posts():
    return js(r"""
(() => {
  let clicked = 0;
  const visibleRoots = () => {
    const roots = [];
    const seen = new Set();
    const xs = [0.35, 0.45, 0.55, 0.65].map((ratio) => Math.floor(window.innerWidth * ratio));
    for (const x of xs) {
      for (let y = 120; y < window.innerHeight - 40; y += 120) {
        let node = document.elementFromPoint(x, y);
        let candidate = null;
        for (let depth = 0; node && depth < 18; depth += 1, node = node.parentElement) {
          const rect = node.getBoundingClientRect();
          if (rect.width < 280 || rect.height < 60) continue;
          if (node.getAttribute('role') === 'article') {
            candidate = node;
            break;
          }
          const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
          if (!text) continue;
          if (/Like|Comment|Share/.test(text) && text.length > 30 && rect.height < 1400) {
            candidate = node;
          }
        }
        if (candidate && !seen.has(candidate)) {
          seen.add(candidate);
          roots.push(candidate);
        }
      }
    }
    return roots;
  };
  const buttons = visibleRoots().flatMap((root) => Array.from(root.querySelectorAll('[role="button"], [role="link"]')))
    .filter((el, index, all) => {
      const text = (el.textContent || el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
      const rect = el.getBoundingClientRect();
      return all.indexOf(el) === index && /^see more$/i.test(text) && rect.width > 0 && rect.height > 0;
    })
    .slice(0, 12);
  for (const button of buttons) {
    button.scrollIntoView({block: 'center', inline: 'nearest'});
    button.click();
    clicked += 1;
  }
  return clicked;
})()
""")

def normalize_post(raw):
    candidates = []
    for anchor in raw.get("time_candidates", []):
        for key in ("aria", "title", "text"):
            value = compact(anchor.get(key))
            if value and value not in candidates:
                candidates.append(value)
    text = raw.get("text") or ""
    for match in re.findall(r"\b(?:Just now|Yesterday|\d+\s*(?:m|min|mins|h|hr|hrs|d|day|days|hours?))\b", text, flags=re.I):
        if match not in candidates:
            candidates.append(match)

    parsed_at = None
    timestamp_text = None
    for candidate in candidates:
        parsed = parse_facebook_time(candidate)
        if parsed:
            parsed_at = parsed
            timestamp_text = candidate
            break

    post_text = text
    if raw.get("author") and post_text.startswith(raw["author"]):
        post_text = post_text[len(raw["author"]):].strip()

    reactions = None
    m = re.search(r"\b(\d[\d,.KMBkmb]*)\s+(?:comments?|shares?|reactions?)\b", text)
    if m:
        reactions = m.group(0)

    stable_key = raw.get("url") or compact(post_text[:300])
    return {
        "author": raw.get("author"),
        "timestamp_text": timestamp_text,
        "timestamp_iso": parsed_at.isoformat() if parsed_at else None,
        "post_url": raw.get("url"),
        "text": post_text,
        "visible_engagement": reactions,
        "_parsed_at": parsed_at,
        "_stable_key": stable_key
    }

def hydrate_post_text(post_url):
    new_tab(post_url)
    wait_for_load()
    time.sleep(2)
    for _ in range(3):
        clicked = js(r"""
(() => {
  const buttons = Array.from(document.querySelectorAll('[role="button"], [role="link"]'))
    .filter((el) => {
      const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
      const rect = el.getBoundingClientRect();
      return /^see more$/i.test(text) && rect.width > 0 && rect.height > 0;
    })
    .slice(0, 8);
  for (const button of buttons) button.click();
  return buttons.length;
})()
""") or 0
        if not clicked:
            break
        time.sleep(0.8)
    return js(r"""
(() => {
  const compact = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const clean = (text) => compact(
    text
      .replace(/\bLike\b.*$/s, '')
      .replace(/\bWrite a public comment.*$/s, '')
      .replace(/\bSee more\b/g, '')
      .replace(/^Facebook\s+/g, '')
  );
  const bodies = Array.from(document.querySelectorAll('[data-ad-comet-preview="message"], [data-ad-preview="message"]'))
    .map((node) => clean(node.innerText || node.textContent || ''))
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  if (bodies.length) return bodies[0];
  const articles = Array.from(document.querySelectorAll('[role="article"]'))
    .map((node) => clean(node.innerText || node.textContent || ''))
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  return articles[0] || null;
})()
""")

chronological_url = group_url.rstrip("/") + "/?sorting_setting=CHRONOLOGICAL"
group_id_match = re.search(r"/groups/([^/?#]+)", group_url)
group_id = group_id_match.group(1) if group_id_match else ""

new_tab(chronological_url)
wait_for_load()
for _ in range(30):
    article_count = js("document.querySelectorAll('[role=\"article\"]').length")
    body_text = js("(document.body && document.body.innerText || '').slice(0, 1000)")
    if article_count or "content isn't available" in (body_text or "").lower():
        break
    time.sleep(1)
time.sleep(3)

status = js(r"""
(() => ({
  href: location.href,
  title: document.title,
  bodyText: (document.body && document.body.innerText || '').slice(0, 1500)
}))()
""")

status_text = compact((status.get("title") or "") + " " + (status.get("bodyText") or "")).lower()
if "login" in (status.get("href") or "").lower() or "log in to facebook" in status_text or "you must log in" in status_text:
    raise RuntimeError("Facebook login is required. Open Chrome, log in to Facebook, then rerun the skill.")
if "content isn't available" in status_text or "this content isn't available" in status_text:
    raise RuntimeError("The logged-in account cannot access this Facebook group or its posts.")

seen = {}
older_hits = 0
no_new_scrolls = 0
last_unique_count = 0
max_scrolls = int(max_scrolls_override) if max_scrolls_override else min(25, max(10, days * 15))
max_hydration_pages = int(max_hydration_pages_override) if max_hydration_pages_override is not None else 5
diagnostics = {
    "visible_articles": 0,
    "dated_articles": 0,
    "expanded_see_more": 0,
    "expand_errors": 0,
    "hydrated_truncated_posts": 0,
    "hydrate_errors": 0,
    "scrolls": 0,
    "older_hits": 0,
    "max_scrolls": max_scrolls,
    "hit_max_scrolls": False,
    "reached_cutoff": False,
    "coverage_complete": False,
    "unique_posts_seen": 0,
    "oldest_timestamp_iso": None,
    "sample_time_candidates": [],
    "page_href": status.get("href"),
    "page_title": status.get("title"),
    "body_sample": compact(status.get("bodyText"))[:500],
}

for scroll_index in range(max_scrolls):
    diagnostics["scrolls"] = scroll_index + 1
    expanded_count = 0
    try:
        batch_expanded = expand_visible_posts() or 0
        expanded_count += batch_expanded
        if batch_expanded:
            time.sleep(0.8)
    except Exception:
        diagnostics["expand_errors"] += 1
    diagnostics["expanded_see_more"] += expanded_count

    for raw in visible_posts(group_id):
        diagnostics["visible_articles"] += 1
        post = normalize_post(raw)
        parsed_at = post.pop("_parsed_at")
        key = post.pop("_stable_key")
        if post.get("timestamp_text") and len(diagnostics["sample_time_candidates"]) < 10:
            diagnostics["sample_time_candidates"].append(post.get("timestamp_text"))
        if parsed_at and parsed_at < cutoff:
            older_hits += 1
            diagnostics["older_hits"] = older_hits
            diagnostics["reached_cutoff"] = True
            continue
        if parsed_at is None:
            continue
        diagnostics["dated_articles"] += 1
        if parsed_at and (
            diagnostics["oldest_timestamp_iso"] is None or parsed_at.isoformat() < diagnostics["oldest_timestamp_iso"]
        ):
            diagnostics["oldest_timestamp_iso"] = parsed_at.isoformat()
        if key not in seen:
            seen[key] = post

    diagnostics["unique_posts_seen"] = len(seen)
    if len(seen) == last_unique_count:
        no_new_scrolls += 1
    else:
        no_new_scrolls = 0
        last_unique_count = len(seen)

    if older_hits >= 8 and scroll_index >= 4:
        break
    if no_new_scrolls >= 10 and scroll_index >= 10:
        break

    try:
        scroll(640, 400, dy=1000)
    except Exception:
        js("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
    time.sleep(2.7)

diagnostics["hit_max_scrolls"] = diagnostics["scrolls"] >= max_scrolls and not diagnostics["reached_cutoff"]
diagnostics["coverage_complete"] = diagnostics["reached_cutoff"] and not diagnostics["hit_max_scrolls"]

posts = list(seen.values())
posts.sort(key=lambda p: p.get("timestamp_iso") or "", reverse=True)
hydrated_count = 0
for post in posts:
    if not (post.get("text") or "").rstrip().endswith("…"):
        continue
    if not post.get("post_url"):
        continue
    if hydrated_count >= max_hydration_pages:
        break
    try:
        hydrated_text = hydrate_post_text(post["post_url"])
        hydrated_count += 1
    except Exception:
        diagnostics["hydrate_errors"] += 1
        continue
    if hydrated_text and len(hydrated_text) > len(post.get("text") or ""):
        post["text"] = hydrated_text
        diagnostics["hydrated_truncated_posts"] += 1
diagnostics["truncated_text_posts"] = sum(1 for post in posts if (post.get("text") or "").rstrip().endswith("…"))
result = {
    "group_url": group_url,
    "days": days,
    "cutoff_iso": cutoff.isoformat(),
    "extracted_at": now.isoformat(),
    "post_count": len(posts),
    "diagnostics": diagnostics,
    "posts": posts
}

print("AI_MIME_RESULT_START")
print(json.dumps(result, ensure_ascii=False))
print("AI_MIME_RESULT_END")
'''


def run_browser_extraction(inputs):
    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is not set.")
    env = os.environ.copy()
    env["AI_MIME_FB_EXTRACT_INPUT"] = json.dumps(inputs)
    proc = subprocess.run(
        [harness, "-c", BROWSER_SCRIPT],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail[-2000:] or "Browser extraction failed.")
    match = re.search(r"AI_MIME_RESULT_START\s*(\{.*\})\s*AI_MIME_RESULT_END", proc.stdout, flags=re.S)
    if not match:
        raise RuntimeError("Browser extraction finished without a parseable result.")
    return json.loads(match.group(1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-json", required=True)
    args = parser.parse_args()

    log_event("step_start", id="load_inputs", title="Read inputs")
    try:
        inputs = load_inputs(args.inputs_json)
    except Exception as exc:
        fail("load_inputs", exc, recoverable=True)
    log_event("step_done", id="load_inputs", outputs=inputs, summary="Inputs validated.")

    log_event("step_start", id="extract_posts", title="Extract Facebook posts")
    try:
        result = run_browser_extraction(inputs)
    except Exception as exc:
        fail("extract_posts", exc, recoverable=True)
    log_event(
        "step_done",
        id="extract_posts",
        outputs={"post_count": result.get("post_count", 0)},
        summary=f"Collected {result.get('post_count', 0)} posts.",
    )

    log_event("step_start", id="write_output", title="Write output")
    try:
        out_dir = output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        group_id = extract_group_id(inputs["group_url"])
        out_path = out_dir / f"facebook_group_posts_{group_id}_{inputs['days']}d_{timestamp}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        fail("write_output", exc, recoverable=True)
    outputs = {"output_path": str(out_path), "post_count": result.get("post_count", 0)}
    log_event("step_done", id="write_output", outputs=outputs, summary="Output file written.")
    log_event("workflow_done", outputs=outputs)
    print(json.dumps(outputs, ensure_ascii=False))


if __name__ == "__main__":
    main()
