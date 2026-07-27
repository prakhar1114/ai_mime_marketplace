import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlencode


DEFAULT_DEGREES = ["1st", "2nd", "3rd"]
DEGREE_TO_NETWORK = {
    "1st": "F",
    "2nd": "S",
    "3rd": "O",
    "3rd+": "O",
}


BROWSER_SCRIPT = r'''
import json
import sys
import time

CONFIG = json.loads(r"""__CONFIG_JSON__""")

def log(message):
    print(message, file=sys.stderr, flush=True)

log("Opening LinkedIn people search...")
search_tab_id = new_tab(CONFIG["url"])
wait_for_load()
time.sleep(1.0)

log("Reading visible people results...")
payload = js(r"""
(() => {
  const config = __JS_CONFIG_JSON__;
  const start = Date.now();
  const timeoutMs = 12000;

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function clean(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+/g, " ")
      .trim();
  }

  function cleanProfileUrl(value) {
    try {
      const url = new URL(value, window.location.href);
      const match = url.pathname.match(/^\/in\/[^/?#]+\/?/);
      if (match) {
        return `${url.origin}${match[0].endsWith("/") ? match[0] : match[0] + "/"}`;
      }
      url.search = "";
      url.hash = "";
      return url.toString();
    } catch (_) {
      return value || "";
    }
  }

  function profileLinks(root) {
    return Array.from(root.querySelectorAll("a[href]"))
      .filter(anchor => {
        const href = anchor.href || "";
        return href.includes("/in/") && !href.includes("/search/");
      });
  }

  function visibleText(element) {
    return clean(element.innerText || element.textContent || "");
  }

  function currentResultElements() {
    const oldListItems = Array.from(document.querySelectorAll("ul.reusable-search__entity-result-list > li"));
    const semanticItems = Array.from(document.querySelectorAll('[role="listitem"]'));
    const candidates = oldListItems.length ? oldListItems : semanticItems;
    const seen = new Set();
    return candidates.filter(item => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      const text = visibleText(item);
      if (!text) return false;
      return profileLinks(item).length > 0;
    });
  }

  function degreeFromText(text) {
    const match = clean(text).match(/(?:^|\s|[\n])(?:•\s*)?(1st|2nd|3rd\+?|3rd)(?:\s|$)/);
    return match ? match[1].replace("+", "") : "";
  }

  function isActionLine(line) {
    return /^(Connect|Message|Follow|Following|Pending|View profile|Save|More)$/i.test(line);
  }

  function connectionStatusFromLines(lines) {
    // LinkedIn renders the card's primary action on its own text line.
    // "Pending" => a connection request was already sent and is awaiting response.
    // "Connect" => not connected and no pending request (safe to send one).
    // "Message" / "Following" / "Follow" => already connected/following (no Connect action shown).
    for (const line of lines) {
      if (/^pending$/i.test(line)) return "pending";
    }
    for (const line of lines) {
      if (/^connect$/i.test(line)) return "can_connect";
    }
    for (const line of lines) {
      if (/^(message|following)$/i.test(line)) return "connected";
    }
    return "unknown";
  }

  function isSocialProofLine(line) {
    return /(mutual connection|mutual connections|followers?|shared connection)/i.test(line);
  }

  function isDegreeLine(line) {
    return /^•?\s*(1st|2nd|3rd\+?|3rd)\s*$/i.test(line);
  }

  function companyFromHeadline(headline) {
    const explicitCompany = clean(config.company);
    if (explicitCompany && headline.toLowerCase().includes(explicitCompany.toLowerCase())) {
      return explicitCompany;
    }
    const atMatch = headline.match(/(?:\bat\b|@)\s+([^|,;]+)/i);
    if (atMatch && atMatch[1]) {
      return clean(atMatch[1]);
    }
    return "";
  }

  function parseResult(item) {
    const rawLines = (item.innerText || "")
      .split(/\n+/)
      .map(clean)
      .filter(Boolean);

    const links = profileLinks(item);
    const primaryLink = links.find(anchor => clean(anchor.innerText).length > 0) || links[0] || null;
    const cardText = clean(item.innerText || "");
    const degree = degreeFromText(cardText);
    const connectionStatus = connectionStatusFromLines(rawLines);

    let name = "";
    if (rawLines.length) {
      name = rawLines[0].replace(/\s*•\s*(1st|2nd|3rd\+?|3rd).*$/i, "").trim();
    }
    if (!name && primaryLink) {
      name = clean(primaryLink.innerText).split(/\n+/)[0].replace(/\s*•\s*(1st|2nd|3rd\+?|3rd).*$/i, "").trim();
    }

    const contentLines = rawLines.filter(line => {
      if (!line || line === name) return false;
      if (name && line.startsWith(name) && degreeFromText(line)) return false;
      if (isDegreeLine(line) || isActionLine(line) || isSocialProofLine(line)) return false;
      return true;
    });

    let headline = contentLines[0] || "";
    let location = contentLines[1] || "";

    if (!location) {
      const fallbackLocation = contentLines.find(line =>
        /\b(India|United States|United Kingdom|Canada|Australia|Singapore|Germany|France|Bengaluru|Bangalore|Mumbai|Delhi|Gurugram|Pune|Hyderabad|Chennai|London|San Francisco|New York)\b/i.test(line)
      );
      if (fallbackLocation && fallbackLocation !== headline) {
        location = fallbackLocation;
      }
    }

    return {
      name,
      headline,
      location,
      profile_url: primaryLink ? cleanProfileUrl(primaryLink.href) : "",
      degree,
      current_company: companyFromHeadline(headline),
      pending: connectionStatus === "pending",
      connection_status: connectionStatus
    };
  }

  function hasUsableNextPage() {
    const controls = Array.from(document.querySelectorAll("button, a"));
    return controls.some(control => {
      const label = clean(control.getAttribute("aria-label") || control.innerText || control.textContent);
      if (!/\bnext\b/i.test(label)) return false;
      if (control.disabled) return false;
      if (control.getAttribute("aria-disabled") === "true") return false;
      const style = window.getComputedStyle(control);
      if (style.display === "none" || style.visibility === "hidden") return false;
      return true;
    });
  }

  return (async () => {
    while (Date.now() - start < timeoutMs) {
      if (window.location.href.includes("/login")) {
        return {ok: false, error: "LinkedIn opened a login page. Please sign in to LinkedIn in Chrome and run again."};
      }
      const items = currentResultElements();
      const text = document.body ? document.body.innerText || "" : "";
      if (items.length > 0 || /No results found|Try searching/i.test(text)) {
        break;
      }
      await sleep(500);
    }

    if (window.location.href.includes("/login")) {
      return {ok: false, error: "LinkedIn opened a login page. Please sign in to LinkedIn in Chrome and run again."};
    }

    const items = currentResultElements();
    const seenProfiles = new Set();
    const results = [];
    for (const item of items) {
      const parsed = parseResult(item);
      if (!parsed.profile_url || !parsed.name) continue;
      if (seenProfiles.has(parsed.profile_url)) continue;
      seenProfiles.add(parsed.profile_url);
      results.push(parsed);
    }

    return {
      ok: true,
      page: config.page,
      has_next_page: hasUsableNextPage(),
      results
    };
  })();
})()
""")

if CONFIG.get("close_tab_after", True):
    log("Closing the search tab...")
    try:
        cdp("Target.closeTarget", targetId=search_tab_id)
    except Exception as exc:
        log(f"Could not close the search tab: {exc}")

print(json.dumps(payload, ensure_ascii=False), flush=True)
'''


def log(message):
    print(message, file=sys.stderr, flush=True)


def load_inputs(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise ValueError(f"Could not read inputs JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Inputs JSON must be an object.")
    return data


def optional_string(inputs, key):
    value = inputs.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when provided.")
    return value.strip()


def normalize_close_tab_after(inputs):
    value = inputs.get("close_tab_after", True)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    raise ValueError("close_tab_after must be a boolean.")


def normalize_page(inputs):
    value = inputs.get("page", 1)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        value = 1
    try:
        page = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("page must be an integer.") from exc
    if page < 1:
        raise ValueError("page must be 1 or greater.")
    return page


def normalize_degrees(inputs):
    value = inputs.get("connection_degree", DEFAULT_DEGREES)
    if value in (None, "", []):
        value = DEFAULT_DEGREES
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("connection_degree must be an array.")

    degrees = []
    invalid = []
    for item in value:
        text = str(item).strip()
        if text == "":
            continue
        if text == "3rd+":
            text = "3rd"
        if text not in {"1st", "2nd", "3rd"}:
            invalid.append(str(item))
        elif text not in degrees:
            degrees.append(text)

    if invalid:
        raise ValueError("connection_degree contains unsupported values: " + ", ".join(invalid))
    return degrees or list(DEFAULT_DEGREES)


def build_search_url(inputs):
    keywords = optional_string(inputs, "keywords")
    title = optional_string(inputs, "title")
    company = optional_string(inputs, "company")
    location = optional_string(inputs, "location")
    page = normalize_page(inputs)
    degrees = normalize_degrees(inputs)
    close_tab_after = normalize_close_tab_after(inputs)

    query = " ".join(part for part in [keywords, title, company, location] if part)
    params = {
        "page": str(page),
    }
    if query:
        params["keywords"] = query

    network_values = [DEGREE_TO_NETWORK[degree] for degree in degrees]
    if network_values:
        params["network"] = json.dumps(network_values, separators=(",", ":"))

    return "https://www.linkedin.com/search/results/people/?" + urlencode(params), {
        "page": page,
        "company": company,
        "close_tab_after": close_tab_after,
    }


def parse_harness_json(stdout):
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Browser automation did not return JSON results.")


def run_browser_search(url, config):
    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise RuntimeError("AI_MIME_BROWSER_HARNESS_BIN is not configured.")

    browser_config = {
        "url": url,
        "page": config["page"],
        "company": config["company"],
        "close_tab_after": config["close_tab_after"],
    }
    browser_code = BROWSER_SCRIPT.replace("__CONFIG_JSON__", json.dumps(browser_config, ensure_ascii=False))
    browser_code = browser_code.replace("__JS_CONFIG_JSON__", json.dumps(browser_config, ensure_ascii=False))

    proc = subprocess.run(
        [harness_bin, "-c", browser_code],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Browser automation failed with exit code {proc.returncode}.")

    payload = parse_harness_json(proc.stdout)
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "LinkedIn search did not complete.")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Search LinkedIn people results in the browser.")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        inputs = load_inputs(args.inputs_json)
        url, config = build_search_url(inputs)
        log("Preparing LinkedIn search...")
        payload = run_browser_search(url, config)
    except Exception as exc:
        log(f"Error: {exc}")
        sys.exit(1)

    outputs = {
        "results": payload.get("results", []),
        "page": payload.get("page", config["page"]),
        "has_next_page": bool(payload.get("has_next_page", False)),
    }
    log(f"Found {len(outputs['results'])} visible people results.")
    print(json.dumps({"event": "workflow_done", "outputs": outputs}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
