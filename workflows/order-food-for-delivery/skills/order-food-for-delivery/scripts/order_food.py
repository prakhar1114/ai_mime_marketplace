#!/usr/bin/env browser-harness
"""
Swiggy food-delivery browser logic (the "domain skill").

This module is meant to be exec'd inside the browser-harness runtime, where
helpers (`js`, `goto_url`, `ask_llm`, `click_at_xy`, `type_text`,
`list_tabs`, `switch_tab`, `ensure_real_tab`, `wait_for_load`, `press_key`,
`page_info`) are pre-imported as globals. It exposes a single entrypoint:

    run(inputs: dict) -> dict

`inputs` keys:
    restaurant_name    (str, required)
    menu_search_query  (str, required)
    address_label      (str, optional, default "A2")

Pipeline:
  1. Search the restaurant and FETCH the result cards.
  2. ask_llm selects the right restaurant.
  3. Open the selected restaurant page.
  4. Search the food item and FETCH the dish cards.
  5. ask_llm selects the correct dish.
  6. Add to cart (customisation wizard is OPTIONAL — only driven if the modal
     appears), open cart, select saved delivery address.

Returns a dict with a "status" field. Possible statuses:
  success | not_logged_in | restaurant_not_found | item_not_found |
  item_unavailable | menu_search_unavailable | add_to_cart_failed |
  address_not_found | checkout_not_ready

Progress is logged via log() to stdout with a "[order]" prefix so the
orchestrator (scripts/run.py) can forward it to stderr.
"""
import json
import sys
import time

DEFAULT_ADDRESS_LABEL = "A2"


def log(msg):
    print(f"[order] {msg}", flush=True)


class OrderError(Exception):
    """A recoverable, reportable outcome (maps to a result status)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------
# Tab management — open ONE dedicated tab and reuse it for the whole flow
# --------------------------------------------------------------------------
def open_swiggy_tab():
    """Open a brand-new tab for the whole flow.

    The script ALWAYS works in a fresh tab so the user's existing tab(s) are
    never overwritten/navigated. After this, every step uses goto_url() on this
    same tab, so NO further tabs are created mid-flow.

    Returns the new tab's target id (a string)."""
    target = new_tab("about:blank")
    # new_tab may return a target-id string or a dict depending on harness build.
    if isinstance(target, dict):
        target = target.get("targetId") or target.get("target") or target.get("id")
    switch_tab(target)
    return target


# --------------------------------------------------------------------------
# Small DOM helpers
# --------------------------------------------------------------------------
def cart_count():
    """Single source of truth for cart state -> int (or -1 if unknown)."""
    txt = js("""
        const a = document.querySelector('a[href="/checkout"]');
        return a ? a.innerText : null;
    """)
    if not txt:
        return -1
    head = txt.strip().split("\n")[0].strip()
    return int(head) if head.isdigit() else -1


def modal_open():
    return bool(js("""
        return !!([...document.querySelectorAll('*')]
          .find(e=>e.children.length===0 && /Customise as per your taste/i.test(e.innerText||'')));
    """))


def assert_logged_in():
    """Raise OrderError('not_logged_in', ...) unless signed in. Must run while
    on the swiggy.com domain (document.cookie is per-domain)."""
    signin = js("const h=document.querySelector('header'); return h ? h.innerText.includes('Sign In') : null;")
    logged = js("return document.cookie.includes('_is_logged_in=1');")
    if signin or not logged:
        raise OrderError(
            "not_logged_in",
            "User is not logged in to Swiggy. Ask the user to sign in via the "
            "site's Sign In button — never type credentials.",
        )


# --------------------------------------------------------------------------
# 1. Search restaurant + fetch results (also enforces login)
# --------------------------------------------------------------------------
def search_restaurants(name):
    import urllib.parse
    goto_url("https://www.swiggy.com/search?query=" + urllib.parse.quote(name))
    wait_for_load()
    time.sleep(1)
    assert_logged_in()
    cards = []
    for _ in range(10):
        time.sleep(1)
        cards = js("""
            const seen=new Set(); const out=[];
            [...document.querySelectorAll('a[href*=rest]')].forEach(a=>{
              const href=a.getAttribute('href')||'';
              if(!/rest\\d+/.test(href) || seen.has(href)) return; seen.add(href);
              const r=a.getBoundingClientRect();
              if(r.width<=0) return;
              out.push({href, text:(a.innerText||'').trim().replace(/\\n/g,' | ').slice(0,260)});
            });
            return out.slice(0,10);
        """)
        if cards:
            break
    return cards


def pick_restaurant(name, cards):
    if not cards:
        raise OrderError("restaurant_not_found", f"No restaurant results for '{name}'.")
    listing = "\n".join(f"[{i}] {c['text']}  (href={c['href']})" for i, c in enumerate(cards))
    schema = {
        "type": "object",
        "properties": {
            "index": {"type": "integer", "nullable": True},
            "reason": {"type": "string"},
        },
        "required": ["index", "reason"],
    }
    pick = ask_llm(
        f"The user wants the restaurant '{name}' on Swiggy. "
        f"Choose the single best-matching restaurant card by index, or null if "
        f"none is a genuine match for that restaurant name.\n"
        f"Prefer the closest name match (ignore ad/deal prefixes). Cards:\n{listing}",
        schema
    )
    log(f"gemini(restaurant) -> {pick}")
    if pick["index"] is None or not (0 <= pick["index"] < len(cards)):
        raise OrderError(
            "restaurant_not_found",
            f"No restaurant matching '{name}'. {pick.get('reason', '')}".strip(),
        )
    return cards[pick["index"]]


# --------------------------------------------------------------------------
# 3 + 4. Open restaurant, search dish, fetch results
# --------------------------------------------------------------------------
def open_restaurant(href):
    url = href if href.startswith("http") else "https://www.swiggy.com" + href
    goto_url(url)
    wait_for_load()
    time.sleep(3)


def search_dishes(query):
    pill = js("""
        const el=[...document.querySelectorAll('*')]
          .find(e=>e.children.length===0 && /Search for dishes/i.test(e.innerText||''));
        if(!el) return null; const r=el.getBoundingClientRect();
        return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
    """)
    if not pill:
        raise OrderError(
            "menu_search_unavailable",
            "Could not find the 'Search for dishes' control on the restaurant page.",
        )
    click_at_xy(pill["x"], pill["y"])
    time.sleep(2)
    js("const i=document.querySelector('input'); if(i) i.focus();")
    type_text(query)
    time.sleep(3)

    cards = []
    for _ in range(8):
        cards = js("""
            const adds=[...document.querySelectorAll('button')]
              .filter(b=>(b.innerText||'').trim()==='ADD' && b.offsetWidth>0);
            const lowers=[];
            for(let i=0;i<adds.length;i++){
              const a=adds[i], b=adds[i+1];
              if(b && Math.abs(a.getBoundingClientRect().x-b.getBoundingClientRect().x)<5){ lowers.push(b); i++; }
              else lowers.push(a);
            }
            const out=[]; const seen=new Set();
            lowers.forEach(btn=>{
              const r=btn.getBoundingClientRect();
              let p=btn, card=null;
              for(let i=0;i<12;i++){ if(!p.parentElement)break; p=p.parentElement;
                const t=(p.innerText||'');
                if(/rupees|₹/.test(t) && t.length<1600){ card=p; break; }
              }
              if(!card) return;
              const txt=(card.innerText||'').trim();
              if(seen.has(txt)) return; seen.add(txt);
              let cx=Math.round(r.left+r.width/2), cy=Math.round(r.top+r.height/2);
              for(let k=0;k<6;k++){ if(document.elementFromPoint(cx,cy)===btn) break; cy+=4; }
              const unavail=/Next available/i.test(txt);
              out.push({add_x:cx, add_y:cy,
                customisable:/customis|customiz/i.test(txt),
                unavailable:unavail,
                text:txt.replace(/\\n/g,' ').slice(0,300)});
            });
            return out.slice(0,10);
        """)
        if cards:
            break
        time.sleep(1)
    return cards


def pick_dish(query, cards):
    if not cards:
        raise OrderError("item_not_found", f"No dish results for '{query}'.")
    listing = "\n".join(
        f"[{i}] {c['text']}  (customisable={c['customisable']}, unavailable={c['unavailable']})"
        for i, c in enumerate(cards)
    )
    schema = {
        "type": "object",
        "properties": {
            "index": {"type": "integer", "nullable": True},
            "reason": {"type": "string"},
        },
        "required": ["index", "reason"],
    }
    pick = ask_llm(
        f"The user searched for the dish '{query}' on a restaurant menu. "
        f"Choose the single best-matching dish by index, or null if none is a "
        f"genuine match for that dish. "
        f"Prefer the closest name match; avoid items marked unavailable when an "
        f"equivalent available one exists. Cards:\n{listing}",
        schema
    )
    log(f"gemini(dish) -> {pick}")
    if pick["index"] is None or not (0 <= pick["index"] < len(cards)):
        raise OrderError(
            "item_not_found",
            f"No dish matching '{query}'. {pick.get('reason', '')}".strip(),
        )
    chosen = cards[pick["index"]]
    if chosen["unavailable"]:
        raise OrderError(
            "item_unavailable",
            f"Best match is not currently available (closed pre-order window): "
            f"{chosen['text'][:80]}",
        )
    return chosen


# --------------------------------------------------------------------------
# 6. Add to cart (customisation wizard is OPTIONAL) + checkout + address
# --------------------------------------------------------------------------
def customisation_wizard():
    """Drive 'Customise as per your taste'. Cheapest defaults are pre-selected;
    leave optional add-ons unchecked. Click Continue until 'Add Item to cart'."""
    for _ in range(12):
        btn = js("""
            const b=[...document.querySelectorAll('button')]
              .find(e=>e.offsetWidth>0 && /^(Continue|Add Item to cart)$/.test((e.innerText||'').trim()));
            if(!b) return null; const r=b.getBoundingClientRect();
            return {t:b.innerText.trim(), x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
        """)
        if not btn:
            return
        log(f"  customise: clicking '{btn['t']}'")
        click_at_xy(btn["x"], btn["y"])
        time.sleep(2)
        if btn["t"] == "Add Item to cart":
            return


def _click_add_and_settle(chosen, before, y_offset=0):
    """Click ADD, then wait for EITHER the (optional) customisation modal OR a
    cart increment. Drive the wizard only if a modal actually opened."""
    click_at_xy(chosen["add_x"], chosen["add_y"] + y_offset)
    saw_modal = False
    for _ in range(8):
        time.sleep(0.5)
        if modal_open():
            saw_modal = True
            break
        if cart_count() > before:
            return cart_count()
    if saw_modal:
        log("  customisation modal appeared -> driving wizard")
        customisation_wizard()
        time.sleep(2)
    else:
        log("  no customisation modal (item added directly)")
    return cart_count()


def add_item(chosen):
    before = cart_count()
    after = _click_add_and_settle(chosen, before)
    if after <= before:
        log("  cart unchanged; closing item-detail modal and retrying lower")
        press_key("Escape")
        time.sleep(1)
        after = _click_add_and_settle(chosen, before, y_offset=6)
    if after <= before:
        raise OrderError(
            "add_to_cart_failed",
            f"Clicked ADD but cart count never incremented (stayed {after}).",
        )
    log(f"cart count: {before} -> {after}")
    return after


def open_cart_select_address(label):
    # Navigate straight to /checkout (cart is server-side for logged-in users).
    goto_url("https://www.swiggy.com/checkout")
    wait_for_load()
    time.sleep(3)

    lbl_js = json.dumps(label)
    confirmed = js("""
        const want=%s;
        const has=[...document.querySelectorAll('*')].some(e=>e.children.length===0 && (e.innerText||'').trim()==='CHANGE');
        const lbl=document.body.innerText.includes(want);
        return has && lbl;
    """ % lbl_js)
    if confirmed:
        log(f"address already confirmed ({label})")
        return True

    target = js("""
        const want=%s;
        const hit=[...document.querySelectorAll('*')]
          .filter(e=>e.offsetWidth>0 && (e.innerText||'').trim()==='DELIVER HERE')
          .find(e=>{ let p=e; for(let i=0;i<6;i++){ p=p.parentElement; if(!p)break;
                       if((p.innerText||'').includes(want)) return true; } return false; });
        if(!hit) return null; const r=hit.getBoundingClientRect();
        return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
    """ % lbl_js)
    if not target:
        raise OrderError(
            "address_not_found",
            f"Saved delivery address '{label}' was not found at checkout.",
        )
    click_at_xy(target["x"], target["y"])
    time.sleep(3)
    ok = js("return [...document.querySelectorAll('*')].some(e=>e.children.length===0 && (e.innerText||'').trim()==='CHANGE');")
    log(f"address {label} selected -> confirmed={bool(ok)}")
    return bool(ok)


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def run(inputs):
    restaurant_name = (inputs.get("restaurant_name") or "").strip()
    menu_search_query = (inputs.get("menu_search_query") or "").strip()
    address_label = (inputs.get("address_label") or DEFAULT_ADDRESS_LABEL).strip()

    result = {
        "status": None,
        "checkout_ready_confirmation": False,
        "restaurant": None,
        "dish": None,
        "address": address_label,
        "cart_count": None,
        "url": None,
        "message": None,
    }
    try:
        if not restaurant_name or not menu_search_query:
            raise OrderError("input_invalid", "restaurant_name and menu_search_query are required.")

        target = open_swiggy_tab()
        log(f"opened new Swiggy tab: {target}")

        log(f"[1/6] searching restaurants for '{restaurant_name}'")
        rest_cards = search_restaurants(restaurant_name)
        log(f"      fetched {len(rest_cards)} restaurant card(s)")

        log("[2/6] selecting restaurant via gemini")
        restaurant = pick_restaurant(restaurant_name, rest_cards)
        result["restaurant"] = restaurant["text"][:90]
        log(f"      chosen: {restaurant['text'][:90]}")

        log("[3/6] opening restaurant page")
        open_restaurant(restaurant["href"])

        log(f"[4/6] searching dishes for '{menu_search_query}'")
        dish_cards = search_dishes(menu_search_query)
        log(f"      fetched {len(dish_cards)} dish card(s)")

        log("[5/6] selecting dish via gemini")
        dish = pick_dish(menu_search_query, dish_cards)
        result["dish"] = dish["text"][:80]
        log(f"      chosen: {dish['text'][:80]}")

        log("[6/6] adding to cart + selecting address")
        result["cart_count"] = add_item(dish)
        confirmed = open_cart_select_address(address_label)
        result["checkout_ready_confirmation"] = bool(confirmed)
        result["status"] = "success" if confirmed else "checkout_not_ready"
        if not confirmed:
            result["message"] = "Item added but delivery address could not be confirmed."

    except OrderError as e:
        result["status"] = e.status
        result["message"] = e.message
        log(f"FAILED -> {e.status}: {e.message}")
    except Exception as e:  # unexpected
        result["status"] = "error"
        result["message"] = f"{type(e).__name__}: {e}"
        log(f"UNEXPECTED ERROR -> {result['message']}")

    try:
        result["url"] = page_info()["url"]
    except Exception:
        pass

    if result["status"] == "success":
        log("DONE: checkout is ready for the user to pay.")
    return result
