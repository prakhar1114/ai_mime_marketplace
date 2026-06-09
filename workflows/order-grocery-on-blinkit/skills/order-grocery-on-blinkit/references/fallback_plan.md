# Fallback Plan — Order Grocery on Blinkit

If `run.sh` fails, a human or the UI agent can finish the task from this file
alone. The whole task runs in the user's logged-in Chrome on blinkit.com. There
are three subtasks: (1) gather brand context from order history, (2) search +
pick + add each item, (3) report results + cart URL.

Preconditions: Chrome running, logged into Blinkit, delivery address set. If
search returns no products, the address is not set — set one and retry. If the
page redirects to login, log in manually; never type credentials via automation.

All browser-side selectors/JS below are embedded in `scripts/blinkit_flow.py`
and field-tested against blinkit.com (2026). Source: browser-harness
`agent-workspace/domain-skills/blinkit/`.

---

## Subtask 1 — Brand context from order history

Intent: learn which brands/pack sizes the user usually buys so picks match habit.

- Navigate to `https://blinkit.com/account/orders`. Wait for load, then sleep
  ~1.5s (React `memoizedProps` is partial at `readyState=complete`).
- Extract recent order ids by walking the React fiber tree: find any element's
  `__reactFiber*` / `__reactInternalInstance*` key, recurse `child`+`sibling`,
  and at each `memoizedProps` look for `identity.id` matching
  `^order_(<orderId>)_(<merchantId>)$`. Dedupe; take the first `max_orders` (10).
- For each order, open `https://blinkit.com/account/orders/<merchantId>/<orderId>`.
  **Trap:** the URL is merchantId FIRST, orderId SECOND — the opposite order of
  the `order_<orderId>_<merchantId>` id string. Swap or you 404.
- On each detail page, fiber-walk for array items whose `widget_type` starts with
  `z_v3_image_text_snippet` and that have `data.{title,subtitle1,subtitle3}`.
  Product name = `data.title.text`. Collect all names.
- Derive brand tokens: take the leading capitalized words of each name (e.g.
  "Tata Sampann", "Mother's Recipe", "Amul", "Levista"), rank by frequency.

Notes: selector scraping does NOT work on account pages (Zomato widget framework
renders data only in fiber props, not DOM text). Reuse the same tab
(`goto_url`) once on blinkit.com; only open a new tab from another origin.

If this subtask fails, continue WITHOUT brand context — picks still work, just
less personalized.

## Subtask 2 — Search, pick, and add each item

Intent: add the best-matching product for each requested item to the cart.

For each item (comma-separated from `items`):

- Navigate directly to `https://blinkit.com/s/?q=<url-encoded item>`. The
  homepage triggers a location-picker modal; `/s/?q=` does not.
- Wait for hydration: poll for `[role="button"][id]` cards whose `id` is purely
  numeric and whose innerText contains `ADD` or `₹`. Cap ~15s. Zero after the
  wait = no delivery address set → stop and tell the user.
- Nudge lazy-load: `window.scrollTo(0,600)` then back to `0` with ~0.5s pauses.
- Parse cards: each `[role="button"]` with a numeric `id` (= Blinkit product id).
  Split innerText into lines; the `ADD` line splits the header. From the header:
  discount = line matching `%OFF`, eta = line matching `MINS`, prices = lines
  starting `₹` (first = price, second = struck MRP), name = first remaining line,
  size = second. Dedupe by id. Keep the first ~20.
- Pick: choose the single best candidate for the item. Prefer the user's frequent
  brands (subtask 1), a sensible default pack size, avoid combos/multipacks unless
  asked. If nothing is a reasonable match, SKIP the item and record the reason.
  (The script delegates this judgment to `ask_llm`; a human can just eyeball it.)
- Add to cart: `document.getElementById(<id>)`; if the card already shows a
  `− N +` stepper (`.icon-plus` present) it's already in cart — done. Otherwise
  click the element whose textContent is exactly `ADD`. Scroll the card into
  center, read `getBoundingClientRect()` at click time (never cache coords).
- Verify: re-check the card has `.icon-plus` (in-cart state). Retry up to 3×.

Notes / anti-bot:
- Blinkit watches CDP fingerprints. Use a "slow click": jitter the landing point
  ±5px, send a few `mouseMoved` events along a short curved path, pause 40–120ms
  before `mousePressed` and before `mouseReleased` (see `_slow_click`).
- Sleep `random 0.6–1.4s` between actions, `1.6–3.2s` after an add click, and
  ~1.5–2s after each page load before reading state.
- Reuse one tab (`goto_url`) for all Blinkit navigation; new tabs per action are
  a churn signal.
- The cart-panel stepper uses different classes (`AddToCart___StyledDiv*`) than
  search cards (`.icon-plus`) — don't mix them.

## Subtask 3 — Report results + cart URL

Intent: tell the user what's in the cart and where to review/pay.

- Output per item: ADDED (product, size, price), SKIPPED (reason), or FAILED
  (reason). Include the brand list used.
- Cart URL = `https://blinkit.com`. There is NO cart deep link — the cart is a
  popup panel opened from the green "N items / ₹X" pill in the page header. The
  cart persists server-side for the logged-in user, so opening blinkit.com and
  clicking that pill shows the items. STOP here — do not proceed to "Proceed To
  Pay" / checkout / payment.

## Clearing side effects before a re-run

The skill adds real items to the live cart (no order placed). To reset between
tests: open blinkit.com, click the cart pill, and remove items — a single click
on the minus glyph at qty 1 removes a row (no trash icon, no confirm). For
higher quantities, click minus repeatedly, re-reading the panel between clicks.
Re-running with the same items is safe: an already-in-cart item is detected via
its stepper and not duplicated.
