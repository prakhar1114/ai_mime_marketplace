"""Blinkit add-to-cart flow — runs INSIDE a browser-harness `-c` block.

Loaded via:
    browser-harness -c 'exec(open(".../blinkit_flow.py").read())'

Harness globals available via exec (NOT imported here):
    js, cdp, ask_llm, new_tab, goto_url, wait_for_load, page_info

Inputs come from env:
    BLINKIT_ITEMS   — comma-separated grocery items (optional)
    BLINKIT_QUERY   — natural-language request, e.g. "add dairy products" (optional)
    BLINKIT_MAX_ORDERS — how many recent orders to read for brand context (default 10)

At least one of BLINKIT_ITEMS / BLINKIT_QUERY must be provided. When BLINKIT_QUERY
is given, the last orders are read and an LLM composes the matching items from the
products the user has previously bought.

Output: prints a single line `RESULT_JSON:<json>` to stdout. The JSON shape:
    {
      "cart_url": "https://blinkit.com",
      "brands": ["Amul", "Tata Sampann", ...],
      "query": "add dairy products" | null,
      "composed_items": ["Amul Taaza Toned Milk", ...],  # items derived from query
      "results": [
        {"item": "...", "status": "added"|"skipped"|"failed",
         "product": str|None, "size": str|None, "price": str|None,
         "reason": str|None}
      ]
    }

This file deliberately does NOT use cart_fsm.py (which hard-requires
GEMINI_API_KEY). It re-implements search -> AI-pick -> add using the harness
ask_llm helper, which works without those keys, and biases the pick toward the
brands the user usually buys.
"""

import json as _json
import os as _os
import random as _random
import re as _re
import time as _time
import urllib.parse as _urlparse


def _log(msg):
    print(msg, flush=True)


# ---------- brand context from order history ----------

_ORDER_IDS_JS = r"""
const isFiberKey = k => k.startsWith("__reactFiber") || k.startsWith("__reactInternalInstance");
let fiber = null;
for (const el of document.querySelectorAll("*")) {
  const k = Object.keys(el).find(isFiberKey);
  if (k) { fiber = el[k]; break; }
}
if (!fiber) return [];
const out = []; const seen = new WeakSet();
function walkProps(node, depth) {
  if (!node || typeof node !== "object" || depth > 12 || seen.has(node)) return;
  seen.add(node);
  if (Array.isArray(node)) { for (const v of node) walkProps(v, depth + 1); return; }
  const id = node.identity && node.identity.id;
  if (typeof id === "string") { const m = id.match(/^order_(\d+)_(\d+)$/); if (m) out.push({orderId: m[1], merchantId: m[2]}); }
  for (const key of Object.keys(node)) { try { walkProps(node[key], depth + 1); } catch (e) {} }
}
function walkFiber(f, depth) { if (!f || depth > 400) return; if (f.memoizedProps) walkProps(f.memoizedProps, 0); walkFiber(f.child, depth + 1); walkFiber(f.sibling, depth + 1); }
walkFiber(fiber, 0);
const dedup = []; const keys = new Set();
for (const o of out) { const key = o.orderId + ":" + o.merchantId; if (!keys.has(key)) { keys.add(key); dedup.push(o); } }
return dedup;
"""

_ORDER_ITEMS_JS = r"""
const isFiberKey = k => k.startsWith("__reactFiber") || k.startsWith("__reactInternalInstance");
let fiber = null;
for (const el of document.querySelectorAll("*")) { const k = Object.keys(el).find(isFiberKey); if (k) { fiber = el[k]; break; } }
if (!fiber) return [];
let products = null; const seen = new WeakSet();
function walkProps(node, depth) {
  if (products || !node || typeof node !== "object" || depth > 14 || seen.has(node)) return; seen.add(node);
  if (Array.isArray(node)) {
    const hits = node.filter(s => s && typeof s === "object" && typeof s.widget_type === "string"
      && s.widget_type.startsWith("z_v3_image_text_snippet") && s.data && s.data.title && s.data.subtitle1 && s.data.subtitle3);
    if (hits.length) { products = hits; return; }
    for (const v of node) walkProps(v, depth + 1); return;
  }
  for (const k of Object.keys(node)) { try { walkProps(node[k], depth + 1); } catch (e) {} }
}
function walkFiber(f, d) { if (!f || d > 400 || products) return; if (f.memoizedProps) walkProps(f.memoizedProps, 0); walkFiber(f.child, d + 1); walkFiber(f.sibling, d + 1); }
walkFiber(fiber, 0);
if (!products) return [];
return products.map(p => ({ name: (p.data.title && p.data.title.text) || "" }));
"""


def _goto(url):
    cur = (page_info() or {}).get("url", "")
    if "blinkit.com" in cur:
        goto_url(url)
    else:
        new_tab(url)
    wait_for_load()
    _time.sleep(1.5)


def collect_brand_context(max_orders=10):
    """Return a list of product names from the user's recent orders (for brand bias)."""
    names = []
    try:
        _goto("https://blinkit.com/account/orders")
        ids = js(_ORDER_IDS_JS) or []
        ids = ids[:max_orders]
        _log(f"[orders] found {len(ids)} recent orders")
        for o in ids:
            url = f"https://blinkit.com/account/orders/{o['merchantId']}/{o['orderId']}"
            try:
                _goto(url)
                rows = js(_ORDER_ITEMS_JS) or []
                for r in rows:
                    nm = (r.get("name") or "").strip()
                    if nm:
                        names.append(nm)
            except Exception as e:
                _log(f"[orders] skip {url}: {e}")
            _time.sleep(_random.uniform(0.5, 1.0))
    except Exception as e:
        _log(f"[orders] brand context failed (continuing without it): {e}")
    return names


def derive_brands(product_names):
    """Heuristic brand tokens: the leading 1-2 words of each product name, ranked by frequency."""
    counts = {}
    for nm in product_names:
        toks = nm.split()
        if not toks:
            continue
        # leading capitalized words form the brand (e.g. "Tata Sampann", "Mother's")
        brand_words = []
        for t in toks[:3]:
            if _re.match(r"^[A-Z][\w'&.-]*$", t):
                brand_words.append(t)
            else:
                break
        brand = " ".join(brand_words).strip()
        if len(brand) >= 3:
            counts[brand] = counts.get(brand, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [b for b, _c in ranked]


def compose_items_from_query(query, product_names):
    """Given a natural-language request and the products the user previously
    ordered, use the LLM to compose the list of items to add to the cart.

    Returns a list of item strings (drawn from / inspired by past orders) and the
    LLM's short reasoning. Returns ([], reason) if nothing matches.
    """
    # Dedupe past products preserving order, cap to keep the prompt small.
    seen = set()
    uniq = []
    for nm in product_names:
        key = nm.lower()
        if nm and key not in seen:
            seen.add(key)
            uniq.append(nm)
    uniq = uniq[:60]

    if not uniq:
        return [], "no past order history to match the request against"

    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["items", "reason"],
    }
    prompt = (
        f"The user said: {query!r}.\n"
        "Below is the list of grocery products the user has bought in their recent "
        "Blinkit orders. Select the products that match the category / request the "
        "user described (e.g. a request for 'dairy products' matches milk, paneer, "
        "curd, butter, cheese, ghee; 'vegetables' matches tomato, onion, ginger, "
        "garlic, etc.). Return each chosen item as a concise search term — you may "
        "reuse the product name as-is or simplify it to the core product. Do not "
        "invent items the user never bought. If nothing matches, return an empty list.\n\n"
        f"Past ordered products (JSON):\n{_json.dumps(uniq, indent=2, ensure_ascii=False)}"
    )
    try:
        res = ask_llm(prompt, schema)
    except Exception as e:
        return [], f"query compose failed: {e}"
    items = [str(x).strip() for x in (res.get("items") or []) if str(x).strip()]
    # Dedupe again (case-insensitive) preserving order.
    seen2 = set()
    out = []
    for it in items:
        k = it.lower()
        if k not in seen2:
            seen2.add(k)
            out.append(it)
    return out, res.get("reason", "")


# ---------- search + add to cart ----------

_CARD_PARSER_JS = r"""
const out = [];
document.querySelectorAll('[role="button"][id]').forEach(el => {
  if (!/^\d+$/.test(el.id)) return;
  const lines = (el.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  if (!lines.includes('ADD') && !lines.some(l => /^\d+$/.test(l))) return;
  const addIdx = lines.indexOf('ADD');
  const head = addIdx >= 0 ? lines.slice(0, addIdx) : lines;
  const discount = head.find(s => /%\s*OFF/i.test(s)) || '';
  const eta = head.find(s => /\bMINS?\b/i.test(s)) || '';
  const prices = head.filter(s => /^₹/.test(s));
  const price = prices[0] || '';
  const mrp = prices[1] || '';
  const meta = new Set([discount, eta, ...prices].filter(Boolean));
  const rest = head.filter(s => !meta.has(s));
  const name = rest[0] || '';
  const size = rest[1] || '';
  if (!name) return;
  out.push({ id: el.id, name, size, price, mrp, discount, eta });
});
const seen = new Set();
return out.filter(r => { if (seen.has(r.id)) return false; seen.add(r.id); return true; });
"""

_LOCATE_ADD_JS = r"""
const card = document.getElementById(__PRODUCT_ID__);
if (!card) return {found: false, reason: 'card not on page'};
card.scrollIntoView({block: 'center', behavior: 'instant'});
const plus = card.querySelector('.icon-plus');
const addEl = [...card.querySelectorAll('div, button, span')].find(e => (e.textContent || '').trim() === 'ADD');
const target = plus || addEl;
if (!target) return {found: false, reason: 'no ADD or + control'};
const r = target.getBoundingClientRect();
return { found: true, mode: plus ? 'increment' : 'add', x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2) };
"""


def _wait_for_results(timeout=15.0):
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        n = js(r"""
const cards = document.querySelectorAll('[role="button"][id]');
let n = 0;
cards.forEach(el => { if (!/^\d+$/.test(el.id)) return; const t = el.innerText || ''; if (t.includes('ADD') || /₹/.test(t)) n++; });
return n;
""")
        if n and n > 0:
            return n
        _time.sleep(0.3)
    return 0


def _slow_click(x, y, jitter=5, steps=3):
    tx = int(x + _random.uniform(-jitter, jitter))
    ty = int(y + _random.uniform(-jitter, jitter))
    sx = tx + _random.randint(-120, 120)
    sy = ty + _random.randint(-120, 120)
    for i in range(1, steps + 1):
        t = i / steps
        ix = int(sx + (tx - sx) * t + _random.uniform(-2, 2))
        iy = int(sy + (ty - sy) * t + _random.uniform(-2, 2))
        cdp("Input.dispatchMouseEvent", type="mouseMoved", x=ix, y=iy)
        _time.sleep(_random.uniform(0.02, 0.08))
    cdp("Input.dispatchMouseEvent", type="mouseMoved", x=tx, y=ty)
    _time.sleep(_random.uniform(0.04, 0.12))
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=tx, y=ty, button="left", clickCount=1)
    _time.sleep(_random.uniform(0.04, 0.12))
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=tx, y=ty, button="left", clickCount=1)


def _is_in_cart(product_id):
    return bool(js(f"""
const card = document.getElementById({_json.dumps(str(product_id))});
if (!card) return false;
return !!card.querySelector('.icon-plus');
"""))


def _locate_add(product_id):
    return js(_LOCATE_ADD_JS.replace("__PRODUCT_ID__", _json.dumps(str(product_id))))


def _llm_pick(item, candidates, brands):
    schema = {
        "type": "object",
        "properties": {
            "chosen_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["chosen_id", "reason"],
    }
    brand_hint = (
        f"The user frequently buys these brands (most-used first): {', '.join(brands[:15])}.\n"
        "Strongly prefer one of these brands when a candidate matches it and the product fits.\n"
        if brands else ""
    )
    prompt = (
        f"User wants to buy: {item!r}.\n"
        f"{brand_hint}"
        "Pick the single best matching product id from the candidates below. "
        "If none is a reasonable match for what the user asked, return the string 'none' as chosen_id. "
        "Match the product type to the request, prefer a sensible default pack size, "
        "and avoid combos/multipacks unless the user explicitly asked for one. "
        "Return the candidate's `id` field exactly as given.\n\n"
        f"Candidates (JSON):\n{_json.dumps(candidates, indent=2, ensure_ascii=False)}"
    )
    res = ask_llm(prompt, schema)
    chosen = (res.get("chosen_id") or "").strip()
    if chosen.lower() in ("", "none", "null"):
        return None, res.get("reason", "")
    return chosen, res.get("reason", "")


def add_item(item, brands):
    """Search + AI-pick + add one item. Returns a result dict."""
    res = {"item": item, "status": "failed", "product": None, "size": None, "price": None, "reason": None}
    try:
        url = f"https://blinkit.com/s/?q={_urlparse.quote(item)}"
        _log(f"[search] {item}")
        _goto(url)

        n = _wait_for_results(timeout=15.0)
        if n == 0:
            res["reason"] = "no results (delivery address not set or page did not load)"
            return res

        js("window.scrollTo(0, 600)")
        _time.sleep(_random.uniform(0.4, 0.8))
        js("window.scrollTo(0, 0)")
        _time.sleep(_random.uniform(0.4, 0.8))

        candidates = (js(_CARD_PARSER_JS) or [])[:20]
        if not candidates:
            res["reason"] = "no product cards parsed"
            return res

        chosen_id, reason = _llm_pick(item, candidates, brands)
        if chosen_id is None:
            res["status"] = "skipped"
            res["reason"] = reason or "no good match"
            _log(f"[skip] {item}: {res['reason']}")
            return res

        chosen = next((c for c in candidates if c["id"] == chosen_id), None)
        if not chosen:
            res["status"] = "skipped"
            res["reason"] = f"picker returned id not in list ({chosen_id})"
            return res

        res["product"] = chosen.get("name")
        res["size"] = chosen.get("size")
        res["price"] = chosen.get("price")

        if _is_in_cart(chosen_id):
            res["status"] = "added"
            res["reason"] = "already in cart"
            _log(f"[ok] {item}: already in cart ({chosen.get('name')})")
            return res

        last_err = None
        for attempt in range(3):
            loc = _locate_add(chosen_id)
            if not loc or not loc.get("found"):
                last_err = f"locate failed: {loc}"
                _time.sleep(_random.uniform(0.6, 1.4))
                continue
            _time.sleep(_random.uniform(0.4, 0.8))
            _slow_click(loc["x"], loc["y"])
            _time.sleep(_random.uniform(1.6, 3.2))
            if _is_in_cart(chosen_id):
                res["status"] = "added"
                res["reason"] = reason
                _log(f"[added] {item} -> {chosen.get('name')} ({chosen.get('size')}, {chosen.get('price')})")
                return res
            last_err = "stepper did not appear after click"
            _time.sleep(_random.uniform(0.6, 1.4))

        res["reason"] = last_err or "add failed after 3 attempts"
        return res
    except Exception as e:
        res["reason"] = f"{type(e).__name__}: {e}"
        return res


def main():
    items_csv = _os.environ.get("BLINKIT_ITEMS", "")
    query = _os.environ.get("BLINKIT_QUERY", "").strip()
    max_orders = int(_os.environ.get("BLINKIT_MAX_ORDERS", "10"))
    items = [s.strip() for s in items_csv.split(",") if s.strip()]

    out = {"cart_url": "https://blinkit.com", "brands": [],
           "query": query or None, "composed_items": [], "results": []}

    if not items and not query:
        out["error"] = "no items or query provided"
        print("RESULT_JSON:" + _json.dumps(out, ensure_ascii=False), flush=True)
        return

    # Read recent orders once: used both for brand bias and (if a query is given)
    # to compose the list of items from what the user previously bought.
    names = collect_brand_context(max_orders=max_orders)
    brands = derive_brands(names)
    out["brands"] = brands
    _log(f"[brands] {brands[:15]}")

    if query:
        composed, reason = compose_items_from_query(query, names)
        out["composed_items"] = composed
        _log(f"[query] {query!r} -> {composed} ({reason})")
        # Append composed items, skipping any already in the explicit list.
        have = {i.lower() for i in items}
        for it in composed:
            if it.lower() not in have:
                items.append(it)
                have.add(it.lower())

    if not items:
        out["error"] = (f"query {query!r} did not match any products in your recent orders"
                        if query else "no items provided")
        print("RESULT_JSON:" + _json.dumps(out, ensure_ascii=False), flush=True)
        return

    for it in items:
        out["results"].append(add_item(it, brands))
        _time.sleep(_random.uniform(0.6, 1.4))

    print("RESULT_JSON:" + _json.dumps(out, ensure_ascii=False), flush=True)


main()
