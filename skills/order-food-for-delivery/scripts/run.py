#!/usr/bin/env python3
"""
One-shot orchestrator for the order-food-for-delivery skill.

Plain CPython entrypoint (NOT browser-harness). It:
  1. Reads + validates the inputs JSON (--inputs-json).
  2. Shells out to `browser-harness -c <driver>`, where the driver execs
     scripts/order_food.py inside the harness runtime (so the browser helpers
     `js`, `goto_url`, `ask_llm`, ... are available) and calls run(inputs).
  3. Streams the skill's "[order]" progress logs to STDERR.
  4. Prints exactly one structured JSON result line to STDOUT.
  5. Maps the result status to an exit code:
        0  success
        2  logical failure (restaurant/item not found, unavailable, add failed,
           address not found, checkout not ready)
        3  preflight / not logged in
        4  input invalid
        5  harness invocation error (browser-harness missing / crashed / no
           parseable result)

Usage:
    python3 scripts/run.py --inputs-json <path/to/inputs.json>
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER_FOOD = os.path.join(HERE, "order_food.py")
RESULT_MARKER = "__ORDER_RESULT__"

EXIT_CODES_HARNESS = 5

# status -> process exit code
EXIT_CODES = {
    "success": 0,
    # logical failures
    "restaurant_not_found": 2,
    "item_not_found": 2,
    "item_unavailable": 2,
    "menu_search_unavailable": 2,
    "add_to_cart_failed": 2,
    "address_not_found": 2,
    "checkout_not_ready": 2,
    "error": 2,
    # preflight
    "not_logged_in": 3,
    # bad input
    "input_invalid": 4,
}

# The code handed to `browser-harness -c`. It runs INSIDE the harness runtime,
# where the browser helpers are pre-imported as globals. It execs the domain
# module into its own global namespace (so order_food's functions resolve those
# helpers), reads inputs from an env var, runs the flow, and prints the result
# on a single marker-prefixed line.
DRIVER = r"""
import json, os
__src_path = os.environ["ORDER_FOOD_SRC"]
with open(__src_path) as __f:
    __code = __f.read()
exec(compile(__code, __src_path, "exec"), globals())
__inputs = json.loads(os.environ["ORDER_FOOD_INPUTS"])
__result = run(__inputs)
print("%s " + json.dumps(__result))
""" % RESULT_MARKER


def load_inputs(path):
    if not os.path.isfile(path):
        return None, f"inputs file not found: {path}"
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"inputs file is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, "inputs JSON must be an object."
    return data, None


def emit(result, exit_code):
    """Print the single JSON result line to stdout and exit."""
    print(json.dumps(result), flush=True)
    sys.exit(exit_code)


def main():
    ap = argparse.ArgumentParser(description="Place a Swiggy delivery order up to ready-to-pay checkout.")
    ap.add_argument("--inputs-json", required=True, help="Path to inputs JSON file.")
    args = ap.parse_args()

    inputs, err = load_inputs(args.inputs_json)
    if err:
        result = {"status": "input_invalid", "message": err}
        print(f"[orchestrator] {err}", file=sys.stderr, flush=True)
        emit(result, EXIT_CODES["input_invalid"])

    # Light validation up front (the module re-checks too).
    if not (inputs.get("restaurant_name") or "").strip() or not (inputs.get("menu_search_query") or "").strip():
        msg = "inputs require non-empty 'restaurant_name' and 'menu_search_query'."
        print(f"[orchestrator] {msg}", file=sys.stderr, flush=True)
        emit({"status": "input_invalid", "message": msg}, EXIT_CODES["input_invalid"])

    print(f"[orchestrator] launching browser-harness for "
          f"'{inputs.get('restaurant_name')}' / '{inputs.get('menu_search_query')}'",
          file=sys.stderr, flush=True)

    env = dict(os.environ)
    env["ORDER_FOOD_SRC"] = ORDER_FOOD
    env["ORDER_FOOD_INPUTS"] = json.dumps(inputs)

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN") or "browser-harness"

    try:
        proc = subprocess.run(
            [harness_bin, "-c", DRIVER],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        msg = "browser-harness CLI not found on PATH."
        print(f"[orchestrator] {msg}", file=sys.stderr, flush=True)
        emit({"status": "error", "message": msg}, EXIT_CODES_HARNESS)

    # Forward harness stderr (helper diagnostics) verbatim.
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()

    # Parse stdout: forward "[order]" progress to stderr, capture the marker line.
    result = None
    for line in proc.stdout.splitlines():
        if line.startswith(RESULT_MARKER):
            payload = line[len(RESULT_MARKER):].strip()
            try:
                result = json.loads(payload)
            except json.JSONDecodeError:
                result = None
        else:
            # progress logs ("[order] ...") + anything else -> stderr
            print(line, file=sys.stderr, flush=True)

    if result is None:
        msg = (f"could not parse a result from browser-harness "
               f"(exit {proc.returncode}).")
        print(f"[orchestrator] {msg}", file=sys.stderr, flush=True)
        emit({"status": "error", "message": msg}, EXIT_CODES_HARNESS)

    status = result.get("status")
    code = EXIT_CODES.get(status, EXIT_CODES_HARNESS)
    emit(result, code)


if __name__ == "__main__":
    main()
