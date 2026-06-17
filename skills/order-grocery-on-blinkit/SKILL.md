---
name: order-grocery-on-blinkit
description: >-
  Add grocery items to the Blinkit (blinkit.com) cart using the user's
  already-logged-in Chrome. Accepts either an explicit comma-separated list of
  items or a natural-language request like "add dairy products" / "add
  vegetables to the cart" — for a natural-language request it reads the user's
  last 10 orders and composes the matching items from what they previously
  bought. Reads order history to bias product selection toward the brands and
  pack sizes the user usually buys, searches each item, AI-picks the best match,
  and adds it to the cart. Stops at the cart — never checks out or pays. Use
  whenever the user wants to order groceries on Blinkit, restock items, build a
  Blinkit cart, "add X, Y, Z to my Blinkit", or reorder a category of things
  they usually buy.
---

# Order Grocery on Blinkit

Builds a Blinkit cart from either an explicit shopping list or a natural-language
request. With a natural-language `query` (e.g. *"add dairy products"*) it reads
the user's recent orders and an LLM composes the matching items from products the
user previously bought. For each item it then searches blinkit.com, lets an LLM
choose the single best product (biased toward the brands the user buys most
often, inferred from order history), and adds it to the cart. It deliberately
stops at the cart — no checkout, no payment — and reports anything it could not
confidently match as **skipped**.

## Inputs

`inputs.json` — provide `items`, `query`, or both (at least one is required):

| Key | Required | Description |
|---|---|---|
| `items` | optional* | Comma-separated grocery items, e.g. `"milk, bread, instant coffee, ginger garlic paste"`. A JSON array of strings is also accepted. |
| `query` | optional* | Natural-language request, e.g. `"add dairy products"` or `"add vegetables to the cart"`. The last orders are read and the matching items are composed from the user's past purchases. |
| `max_orders` | no | How many recent orders to read for brand context and query matching. Default `10`. |

\* At least one of `items` / `query` must be present. If both are given, the
explicit items and the query-composed items are merged (deduped).

Example: `inputs/inputs.example.json`. Template: `inputs/inputs.template.json`.

**Preconditions:** the user's Chrome must be running and logged into Blinkit
with a delivery address set. If no address is set, search returns zero products
and every item fails with "no results".

## Run

```bash
./run.sh inputs/inputs.example.json
# or
"$AI_MIME_PYTHON_PATH" scripts/run.py --inputs-json inputs/inputs.example.json
```

`run.sh` picks the first available interpreter in this order: skill
`.venv/bin/python`, then workflow `../../.venv/bin/python`, then the required
`$AI_MIME_PYTHON_PATH`.

This skill uses only the Python standard library plus the browser-harness
binary (`$AI_MIME_BROWSER_HARNESS_BIN`), so no virtualenv is required. If you
ever add third-party packages to `requirements.txt`, build/repair the venv with:

```bash
"$AI_MIME_UV_PATH" venv .venv --python "$AI_MIME_PYTHON_PATH"
"$AI_MIME_UV_PATH" pip install -r requirements.txt --python .venv/bin/python
```

These install commands are for skill build or manual repair only — the runtime
never creates or repairs `.venv`.

All browser work runs in one `browser-harness -c` session that execs
`scripts/blinkit_flow.py`. That file is self-contained (the Blinkit DOM/JS
recipes are embedded), so it does not depend on `$AI_MIME_BROWSER_SKILL_PATH`
at runtime.

## Outputs

- A human-readable summary on stdout: one line per item tagged `ADDED` /
  `SKIPPED` / `FAILED`, with chosen product, size, price, and reason; the list
  of brand preferences used; and the cart review URL.
- Structured `workflow_done` outputs (on stderr) with:
  - `cart_url`: `https://blinkit.com` — Blinkit has **no shareable cart deep
    link**; the cart is a popup panel that persists for the logged-in user.
    Open this URL and click the green cart pill to review and pay.
  - `query`: the natural-language request, if one was given (else `null`).
  - `composed_items`: items derived from the query by matching past orders.
  - `added`: list of `{item, product, size, price, reason}`.
  - `skipped`: list of `{item, reason}` (no confident match).
  - `failed`: list of `{item, reason}` (searched but could not be added).
  - `brands_used`: top brand tokens inferred from order history.

Exit code is non-zero if any item ends in `failed` (transient/site issue);
skipped items do not cause a non-zero exit.

## Progress log format

Structured JSON events on stderr:

- `{"event":"step_start","id":"add_to_cart","title":"…"}`
- `{"event":"step_done","id":"add_to_cart","outputs":{"added":N,"skipped":N,"failed":N},"summary":"…"}`
- `{"event":"step_failed","id":"…","error":"…","recoverable":true|false}`
- `{"event":"workflow_done","outputs":{…}}`

Free-form harness logs (`[search] …`, `[added] …`, `[skip] …`) are interleaved
on stderr for debugging. The browser-harness subprocess may also print harmless
`async generator` teardown tracebacks from the LLM helper at shutdown — these do
not affect the result.

## Fallback

If `run.sh` fails, see `references/fallback_plan.md` for a manual / UI-agent
recipe to finish the task, including the exact Blinkit selectors, search URL
pattern, order-history fiber-walk, and anti-bot click technique.

Common failures:
- **All items "no results"** → no delivery address set on the account. Open
  blinkit.com, set an address, retry.
- **Redirected to login** → Chrome isn't logged into Blinkit. Log in manually,
  then retry. Never type credentials from automation.

## ask_llm decision points

When a `query` is given, one `ask_llm` call (`compose_items_from_query`) takes the
natural-language request plus the de-duplicated list of products from the user's
recent orders and returns `{"items": [...], "reason": str}` — the past-purchased
products that match the requested category. These become the items to add.

Then one `ask_llm` call per item (inside `scripts/blinkit_flow.py`, `_llm_pick`):
given the user's request, the user's frequent brands, and up to 20 parsed search
candidates, it returns `{"chosen_id": str, "reason": str}`. `chosen_id` is the
Blinkit product id to add, or the string `"none"` to skip the item when no
candidate is a reasonable match. The code adds exactly that product, or skips
when `none`/an unknown id is returned. The prompt instructs it to prefer the
user's usual brands, sensible pack sizes, and to avoid combos/multipacks unless
asked.

## References

- `references/fallback_plan.md` — manual fallback recipe with selectors, URLs,
  fiber-walk, and traps.
- `scripts/blinkit_flow.py` — the browser-side flow (brand context + search +
  pick + add).
- Upstream domain skill: `agent-workspace/domain-skills/blinkit/` in the
  browser-harness repo (`cart.md`, `orders.md`, `search-and-cart.md`).
