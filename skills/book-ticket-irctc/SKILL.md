---
name: book-ticket-irctc
description: Book a train ticket on IRCTC by driving the existing browser-harness `irctc/booking_fsm.py` against an already-logged-in IRCTC tab. Pre-condition — the user must open https://www.irctc.co.in/nget/train-search and log in manually before running.
platform: macos
entrypoint: run.sh
inputs_template: inputs/inputs.template.json
inputs_example: inputs/inputs.example.json
---

# Book a train ticket on IRCTC

Thin wrapper around the domain skill at
`harness/browser-harness/agent-workspace/domain-skills/irctc/booking_fsm.py`.
The wrapper validates inputs, formats them into the FSM's CSV contract,
verifies that the user has an IRCTC tab open **and** is logged in, then
calls `book_ticket(csv)` inside the running browser-harness.

## Pre-condition — user must log in first

> **The script does NOT log in for you.** Before running:
>
> 1. Open Google Chrome (the same Chrome instance the browser-harness is
>    attached to).
> 2. Go to <https://www.irctc.co.in/nget/train-search>.
> 3. Log in manually with your IRCTC user-id + password + captcha.
> 4. Stay on the `/nget/train-search` page in **that same tab**. Do **not**
>    open IRCTC in a second tab — IRCTC binds auth to per-tab
>    `sessionStorage` and the FSM will refuse to proceed if it cannot find
>    a single tab whose body shows `Welcome <name>`.
>
> Only after that, run `./run.sh`.
>
> If a login modal pops mid-flow (after `Book Now`), the FSM prints a
> prompt and blocks on stdin — log in in the browser, return to the
> terminal, and press Enter.

### Re-running after a previous attempt

If a prior run got past the search step, your tab is now on
`/booking/train-list` (or further). **Do NOT just re-run** — the FSM will
issue a full reload back to `/nget/train-search`, which IRCTC treats as a
session eviction.

Instead, in that SAME tab, click the **"Train Search"** link in IRCTC's
top navigation bar (SPA navigation, preserves your session). The URL
should change to `/nget/train-search` while you still see
`Welcome <name>`. Then re-run.

The pre-flight in `run.py` detects this state and refuses to start with
exit code `3` and an actionable message — so a bad re-run won't actually
kick you out.

## Inputs

JSON object passed via `--inputs-json /path/to/inputs.json`. The wrapper
flattens it into the FSM's 8-field CSV
`from, to, date, name, sex, age, train, class`.

| Field        | Type            | Required | Notes                                                                                                       |
|--------------|-----------------|----------|-------------------------------------------------------------------------------------------------------------|
| `from`       | string          | yes      | Station code (2–5 letters, e.g. `NDLS`, `BPL`) **or** a known city name (`delhi`, `mumbai`, `bangalore`, …). |
| `to`         | string          | yes      | Same format as `from`.                                                                                      |
| `date`       | string          | yes      | `YYYY-MM-DD` or `DD/MM/YYYY`. Must be within IRCTC's ARP horizon (≤ ~120 days ahead).                       |
| `passengers` | array of object | yes      | 1–6 entries. IRCTC caps General-quota bookings at 6.                                                        |
| `train`      | string          | no       | Train number (preferred) or train-name substring. **Leave empty** to have Gemini ask the user via dialog.   |
| `class`      | string          | no       | One of `EA`, `1A`, `EC`, `2A`, `FC`, `3A`, `3E`, `CC`, `SL`, `2S`. **Leave empty** to ask the user.         |

Each passenger object:

| Field    | Type    | Required | Notes                                                  |
|----------|---------|----------|--------------------------------------------------------|
| `name`   | string  | yes      | Non-empty. Truncated to 16 chars by IRCTC's input.     |
| `sex`    | string  | yes      | `M` / `F` / `T` (or `male` / `female` / `trans`).      |
| `age`    | integer | yes      | 1–125.                                                 |

### City names vs station codes

The wrapper (`run.py`) pre-resolves common city names to IRCTC station
codes **before** calling the FSM. This is necessary because the FSM's
`_norm_station` checks the `[A-Z]{2,5}` "code" regex *first*, so 5-letter
city names like `delhi` (→ `DELHI`) and `pune` would be misclassified as
codes and fail the autocomplete with `no autocomplete row matched code 'DELHI'`.

Pre-resolved cities (matches `_CITY_DEFAULTS` upstream):

| Input (case-insensitive) | Resolved code |
|--------------------------|---------------|
| `bhopal`                 | `BPL`         |
| `delhi`, `new delhi`     | `NDLS`        |
| `mumbai`, `mumbai cst`, `mumbai vt` | `CSMT` |
| `mumbai central`         | `MMCT`        |
| `bangalore`, `bengaluru` | `SBC`         |
| `chennai`                | `MAS`         |
| `kolkata`                | `HWH`         |
| `hyderabad`              | `HYB`         |
| `pune`                   | `PUNE`        |
| `ahmedabad`              | `ADI`         |

Anything that doesn't match the table is passed through to the FSM
unchanged (so IRCTC station codes like `NDLS`, `BPL`, `CSMT` continue to
work, as do less-common station names which the FSM treats as freeform).

Constraints (enforced by `_parse_input` in `booking_fsm.py` — the wrapper
fails fast with the same messages):

- All of `from`, `to`, `date`, and every passenger's `name`/`sex`/`age`
  must be non-empty.
- `passengers` length must be 1–6.
- `class`, when provided, must be a valid IRCTC class code (upper-cased).
- Quota is hard-coded to `GENERAL`. Tatkal / Premium / Ladies are not
  supported by the underlying FSM.

- Template: [`inputs/inputs.template.json`](inputs/inputs.template.json)
- Example:  [`inputs/inputs.example.json`](inputs/inputs.example.json)

## Run

```bash
# default — uses inputs/inputs.example.json
./run.sh

# explicit inputs file
./run.sh /absolute/path/to/inputs.json
```

`run.sh` invokes `python3 scripts/run.py --inputs-json <file>`, which:

1. Parses and validates the JSON inputs (same rules as `_parse_input`).
2. Builds the 8-field CSV (pipe-joining `name` / `sex` / `age` across
   passengers).
3. Connects to the running browser-harness and executes
   `book_ticket(csv)` from
   `agent-workspace/domain-skills/irctc/booking_fsm.py`.
4. Streams progress to stderr, prints the FSM result JSON to stdout.

FSM behavior (summary — see `booking_fsm.py` for the full contract):

1. Scans existing tabs for `irctc.co.in`. **Fails** with
   `"No IRCTC tab open…"` if none, or `"Found IRCTC tab(s) but none are
   logged in…"` if no tab shows `Welcome <name>`.
2. Pins to that one logged-in tab. Never opens a new tab or switches
   away — IRCTC drops sessionStorage-bound auth on either.
3. On `/nget/train-search`, resets stale `origin` / `destination`, fills
   them via `p-autocomplete`, opens the calendar, picks the date.
4. Submits search → waits for `/booking/train-list` and the
   `app-train-avl-enq` cards.
5. If `train` is empty, calls `ask_llm` (with the parsed train list)
   which pops a native macOS dialog so the user can pick. Same for
   `class` once a train is chosen.
6. Clicks the class box, then the date cell, then `Book Now`.
7. Handles the post-Book-Now branches: terminal-mismatch confirm dialog
   is auto-accepted; a login modal blocks on stdin (`Press Enter when on
   the passenger page`).
8. On `/booking/psgninput`, fills each passenger row (name, age, gender),
   adding rows via `+ Add Passenger` as needed.

The FSM stops at **PASSENGER_FORM_FILLED** — it does **not** click
`Continue`, accept the IRCTC T&C, or drive the payment page. Final
review and payment are intentionally left to the human.

## Outputs

A single JSON line is printed to stdout — the verbatim return value of
`book_ticket()`:

```json
{
  "status": "success",
  "state": "PASSENGER_FORM_FILLED",
  "details": {
    "parsed": {
      "from": "NDLS", "from_kind": "code",
      "to": "BCT",  "to_kind": "code",
      "date": "2026-06-01",
      "passengers": [{"name": "Prakhar Jain", "sex": "M", "age": 28}],
      "train": "12951",
      "class": "3A"
    },
    "chosen_train": {"number": "12951", "name": "MUMBAI RAJDHANI", "index": 0}
  }
}
```

On failure:

```json
{"status": "failed", "state": "<FSM_STATE>", "error": "...", "details": {...}}
```

## Progress log format

Progress lines are emitted to stderr, each prefixed with the FSM state:

```
[PARSE]         from=NDLS to=BCT date=2026-06-01 passengers=1 train=12951 class=3A
[SEARCH_FORM]   pinned to logged-in tab tabId=...
[WAIT_RESULTS]  cards=12
[PICK_TRAIN]    chosen=12951 MUMBAI RAJDHANI
[PICK_CLASS]    class=3A
[CLICK_DATE]    cell=Mon, 1 Jun
[BOOK_NOW]      clicked
[LOGIN_CHECK]   outcome=psgn
[PASSENGER_FORM] filled 1/1
```

## Exit codes

| Code | Meaning                                                                          |
|------|----------------------------------------------------------------------------------|
| `0`  | FSM returned `status="success"` — passenger form is filled and on screen.        |
| `2`  | FSM returned `status="failed"` — see `error` + `state` in the JSON output.       |
| `3`  | Pre-flight failed — no IRCTC tab open, no tab logged in, OR the logged-in tab is not on `/nget/train-search` (restart-trap guard). See stderr for the action to take. |
| `4`  | Input validation failed (before touching the browser).                           |
| `5`  | Could not invoke browser-harness, or it returned malformed output.               |

## ask_llm decision points

Both come from `booking_fsm.py`, both pop a native macOS dialog:

- **Empty `train`** — Gemini is shown the parsed train list and asks the
  user which to book. Returns a `train_number` that must match a card.
- **Empty `class`** — Gemini is shown the class boxes on the chosen
  train and asks the user which to book.

To skip the dialogs entirely, supply both `train` and `class` in inputs.

## Recovery notes (lifted from `booking_fsm.py`)

- **Trap — login eviction:** IRCTC stores auth in per-tab
  `sessionStorage`. The FSM never opens a new tab and never `switch_tab`s
  off the chosen tab mid-flow. If the user opens IRCTC in another tab
  during a run, the original tab loses auth.
- **Trap — full reload drops auth:** if already on `/nget/train-search`,
  the FSM fills the existing form in place rather than calling
  `goto_url`. Do not "simplify" by always navigating.
- **Trap — Tatkal timing:** the FSM hard-codes `GENERAL` quota. Tatkal
  windows (10:00 / 11:00 IST) are not handled.
- **Trap — ARP horizon:** dates more than ~120 days out fail at the
  calendar step with `date {Month}{Year} beyond IRCTC ARP horizon`.
- **6-passenger cap:** the FSM raises if you ask for more than 6
  passengers, matching IRCTC's General-quota limit.
- **Post-Book-Now login modal:** if it pops, the FSM prints a prompt and
  blocks on `input()`. Log in in the browser, then press Enter on the
  passenger page.

## References

- [`references/booking_fsm.md`](references/booking_fsm.md) — short pointer
  to the upstream FSM with the CSV contract and FSM states.
- [`references/fallback_plan.md`](references/fallback_plan.md) — manual /
  UI-agent recovery path if `run.sh` exits non-zero.
- Upstream:
  `harness/browser-harness/agent-workspace/domain-skills/irctc/booking_fsm.py`
  (plus `search-form.md`, `train-list.md`, `passenger-form.md` in the
  same folder).
