#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


SENTINEL = "AI_MIME_RESULT_JSON="


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), file=sys.stderr, flush=True)


def fail(step_id, message, recoverable=False):
    emit("step_failed", id=step_id, error=message, recoverable=recoverable)
    raise SystemExit(1)


def parse_inputs(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("inputs JSON must be an object")

    query = str(data.get("query", "")).strip()
    if not query:
        raise ValueError("input 'query' is required")

    limit = int(data.get("limit") or 100)
    if limit < 1 or limit > 1000:
        raise ValueError("input 'limit' must be between 1 and 1000")

    until = str(data.get("until") or "").strip()
    since = str(data.get("since") or "").strip()
    today = dt.date.today()
    if not until:
        until = today.isoformat()
    if not since:
        since = (parse_date_or_datetime(until).date() - dt.timedelta(days=1)).isoformat()

    return {"query": query, "since": since, "until": until, "limit": limit}


def parse_date_or_datetime(value):
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        parsed_date = dt.date.fromisoformat(value)
        return dt.datetime.combine(parsed_date, dt.time.min)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def build_search_terms(inputs):
    query = inputs["query"].strip()
    terms = [f'"{query}"']
    for key, operator in (("until", "until"), ("since", "since")):
        value = inputs.get(key, "").strip()
        parsed = parse_date_or_datetime(value)
        date_only = "T" not in value and " " not in value and len(value) <= 10
        if date_only:
            terms.append(f"{operator}:{parsed.date().isoformat()}")
        else:
            epoch = int(parsed.replace(tzinfo=dt.timezone.utc).timestamp())
            terms.append(f"{operator}_time:{epoch}")
    return " ".join(terms)


def browser_harness_code(inputs):
    encoded_inputs = json.dumps(inputs, ensure_ascii=False)
    return f"""
import json
import re
import sys
import time
from urllib.parse import quote

INPUTS = json.loads({encoded_inputs!r})
SENTINEL = {SENTINEL!r}


def progress(message):
    print(message, file=sys.stderr, flush=True)


def parse_date_or_datetime(value):
    import datetime as dt
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        parsed_date = dt.date.fromisoformat(value)
        return dt.datetime.combine(parsed_date, dt.time.min)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def build_search_terms(inputs):
    terms = [f'"{{inputs["query"].strip()}}"']
    for key, operator in (("until", "until"), ("since", "since")):
        value = inputs.get(key, "").strip()
        parsed = parse_date_or_datetime(value)
        date_only = "T" not in value and " " not in value and len(value) <= 10
        if date_only:
            terms.append(f"{{operator}}:{{parsed.date().isoformat()}}")
        else:
            epoch = int(parsed.replace(tzinfo=__import__("datetime").timezone.utc).timestamp())
            terms.append(f"{{operator}}_time:{{epoch}}")
    return " ".join(terms)


def parse_count(label, word):
    if not label:
        return 0
    match = re.search(r"([0-9][0-9,]*)\\s+" + re.escape(word), label, re.I)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def parse_author(user_name_text, url):
    name = ""
    username = ""
    if user_name_text:
        lines = [line.strip() for line in user_name_text.splitlines() if line.strip() and line.strip() != "·"]
        for line in lines:
            if line.startswith("@") and not username:
                username = line
            elif not name and not line.startswith("@"):
                name = line
    if not username and url:
        parts = url.split("/")
        if len(parts) > 3 and parts[3]:
            username = "@" + parts[3]
    return name, username


def extract_visible():
    expr = \"\"\"
    (() => Array.from(document.querySelectorAll(`article[data-testid="tweet"], article`)).map((a) => {{
      const statusLinks = Array.from(a.querySelectorAll(`a[href*="/status/"]`)).map(x => x.href).filter(h => !h.includes(`/analytics`));
      const analytics = Array.from(a.querySelectorAll(`a[href*="/analytics"]`)).map(x => x.getAttribute(`aria-label`)).filter(Boolean);
      const url = statusLinks[0] || null;
      const textNodes = Array.from(a.querySelectorAll(`[data-testid="tweetText"]`)).map(x => x.innerText.trim()).filter(Boolean);
      const reply = a.querySelector(`[data-testid="reply"]`);
      const like = a.querySelector(`[data-testid="like"]`);
      const userName = a.querySelector(`[data-testid="User-Name"]`);
      return {{
        url,
        content: textNodes[0] || ``,
        user_name_text: userName ? userName.innerText : ``,
        reply_aria: reply ? reply.getAttribute(`aria-label`) : null,
        like_aria: like ? like.getAttribute(`aria-label`) : null,
        views_aria: analytics[0] || null
      }};
    }}).filter(x => x.url))()
    \"\"\"
    return js(expr)


terms = build_search_terms(INPUTS)
search_url = f"https://x.com/search?f=top&q={{quote(terms)}}&src=typed_query"
progress(f"opening X search: {{search_url}}")
new_tab(search_url)
time.sleep(6)

page = page_info()
body_text = js("document.body ? document.body.innerText.slice(0, 2000) : ''")
if "Log in" in body_text and "Search timeline" not in body_text and "Top" not in body_text:
    raise RuntimeError("X search is not accessible. Please log in to X in Chrome and rerun the skill.")

limit = int(INPUTS["limit"])
seen = {{}}
stall = 0
last_count = 0
max_scrolls = max(30, min(280, limit * 4))

for step in range(max_scrolls):
    for item in extract_visible():
        seen[item["url"]] = item
    count = len(seen)
    progress(f"scroll {{step}}: collected {{count}}/{{limit}}")
    if count >= limit:
        break
    if count == last_count:
        stall += 1
    else:
        stall = 0
    if stall >= 14:
        progress("stopping after repeated scrolls with no new posts")
        break
    last_count = count
    js("window.scrollBy(0, Math.floor(window.innerHeight * 0.9))")
    time.sleep(1.8)

posts = []
for item in seen.values():
    name, username = parse_author(item.get("user_name_text") or "", item.get("url") or "")
    posts.append({{
        "name": name,
        "username": username,
        "likes": parse_count(item.get("like_aria"), "Likes"),
        "comments": parse_count(item.get("reply_aria"), "Replies"),
        "views": parse_count(item.get("views_aria"), "views"),
        "url": item.get("url") or "",
        "content": item.get("content") or ""
    }})

posts.sort(key=lambda p: p["likes"], reverse=True)
posts = posts[:limit]
result = {{
    "query": INPUTS["query"],
    "since": INPUTS["since"],
    "until": INPUTS["until"],
    "limit": limit,
    "search_url": search_url,
    "count": len(posts),
    "posts": posts
}}
print(SENTINEL + json.dumps(result, ensure_ascii=False), flush=True)
"""


def run_browser_harness(inputs):
    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness:
        fail("run_search", "AI_MIME_BROWSER_HARNESS_BIN is required", recoverable=True)
    if not Path(harness).exists():
        fail("run_search", f"browser harness not found at {harness}", recoverable=True)

    cmd = [harness, "-c", browser_harness_code(inputs)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
    stdout, _ = proc.communicate()
    if proc.returncode != 0:
        fail("run_search", f"browser harness exited with code {proc.returncode}", recoverable=True)

    for line in reversed(stdout.splitlines()):
        if line.startswith(SENTINEL):
            return json.loads(line[len(SENTINEL):])
    fail("run_search", "browser harness did not return result JSON", recoverable=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-json", required=True)
    args = parser.parse_args()

    emit("step_start", id="load_inputs", title="Load inputs")
    try:
        inputs = parse_inputs(args.inputs_json)
    except Exception as exc:
        fail("load_inputs", str(exc), recoverable=True)
    emit("step_done", id="load_inputs", outputs=inputs, summary="Inputs loaded")

    emit("step_start", id="run_search", title="Search X and extract posts")
    result = run_browser_harness(inputs)
    emit(
        "step_done",
        id="run_search",
        outputs={"count": result.get("count"), "search_url": result.get("search_url")},
        summary=f"Extracted {result.get('count', 0)} posts",
    )
    emit("workflow_done", outputs={"count": result.get("count"), "search_url": result.get("search_url")})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
