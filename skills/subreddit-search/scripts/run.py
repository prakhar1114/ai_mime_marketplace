#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote


VALID_TIME_FRAMES = {"hour", "day", "week", "month", "year", "all"}
RESULT_SENTINEL = "__AI_MIME_REDDIT_RESULT__"


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


def fail(step_id, error, recoverable=False):
    log_event("step_failed", id=step_id, error=error, recoverable=recoverable)
    sys.exit(1)


def load_inputs(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        fail("prepare_inputs", f"Could not read inputs JSON: {exc}")


def normalize_subreddit(raw):
    subreddit = str(raw or "").strip()
    subreddit = subreddit.removeprefix("https://www.reddit.com/r/")
    subreddit = subreddit.removeprefix("https://reddit.com/r/")
    subreddit = subreddit.removeprefix("www.reddit.com/r/")
    subreddit = subreddit.removeprefix("reddit.com/r/")
    subreddit = subreddit.strip("/")
    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]
    subreddit = subreddit.strip("/")
    if not subreddit:
        fail("prepare_inputs", "Missing required input: target_subreddit")
    if not re.fullmatch(r"[A-Za-z0-9_]+", subreddit):
        fail("prepare_inputs", "target_subreddit must be a subreddit name such as 'SaaS' or 'r/SaaS'")
    return subreddit


def parse_post_count(raw):
    if raw in (None, ""):
        return 10
    try:
        count = int(raw)
    except (TypeError, ValueError):
        fail("prepare_inputs", "post_count must be an integer")
    if count < 1:
        fail("prepare_inputs", "post_count must be at least 1")
    return count


def build_target_url(subreddit, query, time_frame):
    if query:
        return (
            f"https://www.reddit.com/r/{subreddit}/search/"
            f"?q={quote(query, safe='')}&restrict_sr=1&sort=top&t={time_frame}"
        )
    return f"https://www.reddit.com/r/{subreddit}/top/?t={time_frame}"


def browser_script(feed_url, post_count):
    code = r'''
import json

FEED_URL = __FEED_URL__
POST_COUNT = __POST_COUNT__
RESULT_SENTINEL = "__AI_MIME_REDDIT_RESULT__"

def collect_links():
    return js(r"""
    (() => {
      const out = [];
      const seen = new Set();
      const add = (href) => {
        if (!href) return;
        try {
          const u = new URL(href, location.origin);
          if (!/\/r\/[^/]+\/comments\/[^/]+/i.test(u.pathname)) return;
          u.search = "";
          u.hash = "";
          const clean = u.origin + u.pathname;
          if (!seen.has(clean)) {
            seen.add(clean);
            out.push(clean);
          }
        } catch (e) {}
      };
      for (const post of document.querySelectorAll("shreddit-post")) {
        add(post.getAttribute("permalink"));
        add(post.getAttribute("content-href"));
        for (const a of post.querySelectorAll("a[slot=full-post-link], a[slot=title], a[href*='/comments/']")) {
          add(a.href || a.getAttribute("href"));
        }
      }
      for (const a of document.querySelectorAll("a[href*='/comments/']")) {
        add(a.href || a.getAttribute("href"));
      }
      return out;
    })()
    """) or []


extract_post_js = r"""
(() => {
  const postEl = document.querySelector("shreddit-post");
  const text = (el) => el && el.innerText ? el.innerText.trim() : "";
  const parseNumber = (raw) => {
    if (raw === null || raw === undefined) return 0;
    let s = String(raw).trim().toLowerCase().replace(/,/g, "");
    if (!s || s === "vote" || s === "score hidden") return 0;
    let mult = 1;
    if (s.endsWith("k")) {
      mult = 1000;
      s = s.slice(0, -1);
    } else if (s.endsWith("m")) {
      mult = 1000000;
      s = s.slice(0, -1);
    }
    const m = s.match(/-?\d+(?:\.\d+)?/);
    return m ? Math.round(parseFloat(m[0]) * mult) : 0;
  };
  if (!postEl) {
    return {
      title: text(document.querySelector("h1")),
      url: location.href,
      upvotes: 0,
      comments: 0,
      body_text: "[Media/Link Post]"
    };
  }
  const title = (
    text(postEl.querySelector("h1, [slot=title]")) ||
    postEl.getAttribute("post-title") ||
    text(document.querySelector("h1"))
  );
  const bodyRoot = postEl.querySelector("[slot=text-body] .md, [slot=text-body]");
  let body = "";
  if (bodyRoot) {
    const paras = Array.from(bodyRoot.querySelectorAll("p")).map((p) => text(p)).filter(Boolean);
    body = paras.length ? paras.join("\n\n") : text(bodyRoot);
  }
  if (!body) body = "[Media/Link Post]";

  const attrNumber = (names) => {
    for (const name of names) {
      const val = postEl.getAttribute(name);
      if (val !== null && val !== "") return parseNumber(val);
    }
    return 0;
  };

  let upvotes = attrNumber(["score", "post-score", "upvote-count", "upvotes"]);
  let comments = attrNumber(["comment-count", "comments", "num-comments", "num_comments"]);

  if (!upvotes) {
    const scoreEl = postEl.querySelector("faceplate-number[number]");
    upvotes = parseNumber(scoreEl ? (scoreEl.getAttribute("number") || scoreEl.innerText) : "");
  }

  if (!comments) {
    const candidates = Array.from(postEl.querySelectorAll("a, button, span, faceplate-number"));
    for (const el of candidates) {
      const hay = ((el.getAttribute("aria-label") || "") + " " + text(el)).toLowerCase();
      if (hay.includes("comment")) {
        comments = parseNumber(el.getAttribute("number") || text(el) || hay);
        if (comments) break;
      }
    }
  }

  return {
    title,
    url: location.href,
    upvotes,
    comments,
    body_text: body
  };
})()
"""


new_tab(FEED_URL)
wait_for_load()
wait(3.0)

post_links = []
max_scrolls = max(8, min(60, (POST_COUNT // 3) + 8))
for _ in range(max_scrolls):
    post_links = collect_links()
    if len(post_links) >= POST_COUNT:
        break
    js("window.scrollBy(0, 1800)")
    wait(1.0)

post_links = post_links[:POST_COUNT]
results = []

if post_links:
    goto_url(post_links[0])
    wait_for_load()
    wait(2.0)
    data = js(extract_post_js) or {}
    data["url"] = post_links[0]
    results.append(data)

for link in post_links[1:]:
    goto_url(link)
    wait_for_load()
    wait(2.0)
    data = js(extract_post_js) or {}
    data["url"] = link
    results.append(data)

print(RESULT_SENTINEL + json.dumps({"results": results}, ensure_ascii=False))
'''
    return code.replace("__FEED_URL__", json.dumps(feed_url)).replace("__POST_COUNT__", str(post_count))


def run_browser_harness(script_code):
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        fail("scrape_reddit", "AI_MIME_BROWSER_HARNESS_BIN is required")

    proc = subprocess.run(
        [harness_bin, "-c", script_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        fail("scrape_reddit", f"Browser harness failed: {details}")

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(RESULT_SENTINEL):
            try:
                return json.loads(line[len(RESULT_SENTINEL):])
            except json.JSONDecodeError as exc:
                fail("scrape_reddit", f"Browser harness returned invalid JSON: {exc}")

    tail = "\n".join(proc.stdout.splitlines()[-10:])
    fail("scrape_reddit", f"Browser harness did not return a result payload. Output tail: {tail}")


def main():
    parser = argparse.ArgumentParser(description="Scrape top Reddit posts from a subreddit.")
    parser.add_argument("--inputs-json", required=True, help="Path to the inputs JSON file")
    args = parser.parse_args()

    log_event("step_start", id="prepare_inputs", title="Prepare Reddit scrape inputs")
    inputs = load_inputs(args.inputs_json)
    subreddit = normalize_subreddit(inputs.get("target_subreddit"))
    query = str(inputs.get("query") or "").strip()
    time_frame = str(inputs.get("time_frame") or "month").strip()
    if time_frame not in VALID_TIME_FRAMES:
        fail("prepare_inputs", "time_frame must be one of: hour, day, week, month, year, all")
    post_count = parse_post_count(inputs.get("post_count", 10))
    target_url = build_target_url(subreddit, query, time_frame)
    log_event(
        "step_done",
        id="prepare_inputs",
        outputs={"target_url": target_url, "post_count": post_count},
        summary="Prepared Reddit URL and limits",
    )

    log_event("step_start", id="scrape_reddit", title="Scrape Reddit posts in browser")
    outputs = run_browser_harness(browser_script(target_url, post_count))
    results = outputs.get("results", [])
    log_event(
        "step_done",
        id="scrape_reddit",
        outputs={"result_count": len(results)},
        summary=f"Extracted {len(results)} posts",
    )
    final_outputs = {"results": results}
    log_event("workflow_done", outputs=final_outputs)
    print(json.dumps(final_outputs, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
