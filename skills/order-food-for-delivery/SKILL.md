# order-food-for-delivery

Place a Swiggy delivery order end-to-end: **search restaurant → pick the right
restaurant (Gemini) → open menu → search dish → pick the right dish (Gemini) →
add to cart (handling customisation, preferring cheaper options) → open cart →
select saved address A2**. Stops at the ready-to-pay checkout — never pays.

The canonical implementation is **[`order_food.py`](./order_food.py)**. This
file documents how it works and the traps it avoids. Prefer running the script;
hand-driving the steps is a fallback.

## Run it

The script uses browser-harness helpers (`js`, `goto_url`, `ask_llm`,
`click_at_xy`, `type_text`, …) which are pre-imported by the harness runtime, so
run it through the harness:

```bash
browser-harness -c "$(cat order_food.py)"
```

Inputs come from `../../agent/confirmed_inputs.json`
(`restaurant_name`, `menu_search_query`), falling back to the script `DEFAULTS`.

### Output — always one structured line

The script **always** prints exactly one line, `RESULT: {<json>}`, carrying a
`status` field (plus `restaurant`, `dish`, `address`, `cart_count`, `url`,
`message`). It never crashes on the expected failure modes — it reports them:

| `status` | Meaning |
|----------|---------|
| `success` | Item in cart, address A2 set, ready to pay. |
| `not_logged_in` | User is not signed in to Swiggy (ask them to sign in — never type credentials). |
| `restaurant_not_found` | No restaurant matched the query (empty results, or Gemini found no genuine match). |
| `item_not_found` | No dish matched the query. |
| `item_unavailable` | Best dish match is in a closed pre-order window ("Next available at …"). |
| `menu_search_unavailable` | Couldn't open the in-restaurant dish search. |
| `add_to_cart_failed` | Clicked ADD but cart count never incremented. |
| `address_not_found` | Saved address A2 not present at checkout. |
| `checkout_not_ready` | Item added but address could not be confirmed. |

Internally these are raised as `OrderError(status, message)` and caught in
`main()`, which fills the result and prints it. On `success` it also prints
`DONE: checkout is ready for the user to pay.`

## Preconditions

- **User must be logged in to Swiggy.** The script asserts this via
  `document.cookie` containing `_is_logged_in=1` and the header not showing
  `Sign In`. If not logged in it stops and asks — **never type credentials.**
- A saved delivery address labelled **A2** must exist on the account.
- Chrome must be running and attached to the harness, with at least one real
  tab open.

## Pipeline (the requested breakdown)

| # | Phase | Function in `order_food.py` | How |
|---|-------|------------------------------|-----|
| 1 | Search restaurant + **fetch** | `search_restaurants()` | `goto_url("/search?query=<name>")`, scrape `a[href*=rest]` cards (name, rating, ETA, cuisines, locality, href). |
| 2 | **Select** restaurant | `pick_restaurant()` | `ask_llm` with a structured schema → best-match index (or null). |
| 3 | Open restaurant | `open_restaurant()` | `goto_url(href)` — same tab. |
| 4 | Search dish + **fetch** | `search_dishes()` | Click "Search for dishes" pill, type query, scrape dish cards (name, veg/non-veg, price, customisable, real ADD coords). |
| 5 | **Select** dish | `pick_dish()` | `ask_llm` → best-match index; rejects unavailable items. |
| 6 | Add to cart + address | `add_item()` → `customisation_wizard()` → `open_cart_select_address()` | Click the real ADD, drive the customisation modal (cheaper defaults), verify cart count, open cart, click `DELIVER HERE` for A2. |

### Tab reuse

`reuse_tab()` pins the whole flow to **one** tab: an already-open Swiggy tab if
present, else the current real tab. All navigation uses `goto_url()`
(in-place `Page.navigate`) so **no extra tab is ever created.**

### Restaurant/dish selection with `ask_llm`

Both selection steps feed the scraped, human-readable card text to
`ask_llm` with a forced JSON schema and branch deterministically on the
returned index:

```python
schema = {"type": "object",
          "properties": {"index": {"type": "integer", "nullable": True},
                         "reason": {"type": "string"}},
          "required": ["index", "reason"]}
pick = ask_llm(prompt_with_listed_cards, schema)
```

> Gemini's response schema rejects union types like `["integer","null"]`.
> Use `{"type":"integer","nullable":true}` instead.

> `js(expr, target_id=None)` — the second arg is a CDP target id, **not** a
> script argument, so `arguments[0]` does not work. Inline values into the JS
> string (e.g. via `json.dumps(label)`).

## Cart state — single source of truth

Read the header link, not visual state (`cart_count()`):

```js
const a = document.querySelector('a[href="/checkout"]');  // quote the "/"
return a ? a.innerText : null;     // "0\nCart", "1\nCart", ...
```

Note: there is **no** cart link on `/checkout`, so read the count on the menu
page *before* navigating to checkout (the script stores it in `items_in_cart`).

## The two-ADD trap (most important)

Each dish card renders **two `<button>ADD</button>`** stacked at nearly the same
x. The **upper** one sits under the product `<img>` overlay — a real click hits
the image and opens a **read-only item-detail modal** (its ancestor is
`aria-hidden="true"`; its buttons add nothing). The **lower** button is the real
control. The extractor pairs same-x buttons, keeps the lower one, and validates
the click point with `document.elementFromPoint(cx, cy) === btn`, nudging `cy`
down in 4px steps until it matches. `add_item()` retries once (Escape + nudge)
if the cart count didn't increment.

Dish **price** is in accessibility text — `"Costs: 250 rupees"`, not `₹` — so
the card extractor matches `/rupees|₹/`.

## Customisation wizard — OPTIONAL

The modal **may or may not appear** — it only opens for `Customisable` items
(e.g. pizzas with crust/size choices). A non-customisable item is added straight
to the cart with no modal. `add_item()` handles both: after clicking ADD,
`_click_add_and_settle()` waits for **either** the modal to appear **or** the
cart count to increment, and only drives `customisation_wizard()` if a modal
actually opened (detected via `modal_open()`).

When it does appear, the modal title is **`Customise as per your taste`**.
`customisation_wizard()` polls the footer button text (not the `Step N/M`
counter) and clicks `Continue` until it flips to `Add Item to cart`, then clicks
that:

- Cheapest required option is usually **pre-selected** — leave it.
- Add-on checkboxes are optional — **leave unchecked** for the cheapest order.
- The footer button's y-coordinate **changes between steps** — requery each
  iteration (the script does).

## Open cart + address selection

`open_cart_select_address()` navigates **directly** to
`https://www.swiggy.com/checkout` (the cart is server-side for logged-in users,
so the just-added item is there). This is deliberately preferred over clicking
the green **VIEW CART** bottom bar, which is an animated, viewport-wide overlay
whose click can fail to navigate — observed leaving the page on the restaurant
search route and breaking address selection.

`DELIVER HERE` is a `<div>`, not a `<button>` — a generic `button,a` selector
misses it. The function finds the `DELIVER HERE` element whose ancestor text
contains `A2` and clicks it. If the address is already confirmed (a `CHANGE`
link is present next to `A2`) it treats that as success.

**Success state:** the address card collapses to a confirmed strip with a
`CHANGE` link and a green `PROCEED TO PAY` appears. The script stops here —
handing off payment is the user's call.

## Direct entrypoints

| Goal | URL |
|------|-----|
| Global search | `https://www.swiggy.com/search?query=<name>` |
| Restaurant menu | `https://www.swiggy.com/city/<city>/<slug>-rest<id>` (from a result card's href) |
| Checkout | `https://www.swiggy.com/checkout` |

Don't load `/` — it can force a location modal even when an address exists;
`/search` renders immediately for logged-in users.

## Gotchas / Traps

- **`a[href=/checkout]` throws** — quote the slash: `a[href="/checkout"]`.
- **`ask_llm` schema**: use `nullable: true`, never `["type","null"]`.
- **`js()` takes no script args** — inline values with `json.dumps`.
- **Two ADD buttons per card** — always pick the lower one and validate with
  `elementFromPoint`.
- **Item-detail modal is read-only** (`aria-hidden="true"` ancestor) — close
  with Escape, don't retry inside it.
- **Price = "Costs: N rupees"** in a11y text, not `₹`.
- **`DELIVER HERE` is a non-`<button>`** `<div>`; disambiguate by walking up to
  the card whose text contains the address label (`A2`).
- **Don't rely on clicking `VIEW CART`** — it can fail to navigate. Go straight
  to `/checkout` instead (the cart is server-side).
- **No cart link on `/checkout`** — read cart count before navigating away.
- **`Continue` button moves between customisation steps** — requery every loop.
- **"Next available at HH:MM" items** have a ghost ADD that does nothing
  (pre-order window not open) — `pick_dish()` flags `unavailable` and stops.

## Not covered (stop and ask the user)

- Login (OTP / password).
- Adding a new delivery address.
- Coupon application, payment-method selection, placing/paying the order.
- Dineout flow (this skill uses the `Order Online` delivery path).
