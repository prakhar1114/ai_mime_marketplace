#!/usr/bin/env python3
"""Order grocery on Blinkit — add a comma-separated list of items to the cart.

Reads the user's recent orders to bias product/brand selection, searches each
item on blinkit.com, AI-picks the best match, and adds it to the cart. Stops at
the cart (no checkout / no payment). Items with no good match are skipped and
reported.

Invocation:
    python scripts/run.py --inputs-json /path/to/inputs.json
    ./run.sh /path/to/inputs.json

Inputs JSON (provide `items`, `query`, or both):
    {"items": "milk, bread, instant coffee", "max_orders": 10}
    {"query": "add dairy products to the cart"}

Requires the user's Chrome to be running and logged into Blinkit with a delivery
address set. All browser work is delegated to the browser-harness CDP session.
"""

import argparse
import json
import os
import subprocess
import sys


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False), file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Order grocery on Blinkit")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    try:
        with open(args.inputs_json, "r", encoding="utf-8") as f:
            inputs = json.load(f)
    except Exception as e:
        print(f"Error reading inputs: {e}", file=sys.stderr)
        sys.exit(1)

    items = inputs.get("items")
    if isinstance(items, list):
        items = ", ".join(str(x) for x in items)
    items = (items or "").strip()
    query = str(inputs.get("query") or "").strip()
    max_orders = int(inputs.get("max_orders", 10))

    if not items and not query:
        log_event("step_failed", id="validate_inputs",
                  error="Provide at least one of: 'items' (comma-separated list) or 'query' (natural language).",
                  recoverable=False)
        sys.exit(1)

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        log_event("step_failed", id="env", error="AI_MIME_BROWSER_HARNESS_BIN not configured", recoverable=False)
        sys.exit(1)

    flow_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blinkit_flow.py")

    # ---- Step 1: brand context + add to cart (single browser-harness session) ----
    log_event("step_start", id="add_to_cart", title="Reading brand history and adding items to Blinkit cart")

    env = dict(os.environ)
    env["BLINKIT_ITEMS"] = items
    env["BLINKIT_QUERY"] = query
    env["BLINKIT_MAX_ORDERS"] = str(max_orders)

    harness_code = f"exec(open({json.dumps(flow_path)}).read())"

    try:
        proc = subprocess.run(
            [harness_bin, "-c", harness_code],
            capture_output=True, text=True, env=env,
        )
    except Exception as e:
        log_event("step_failed", id="add_to_cart", error=f"Failed to launch browser harness: {e}", recoverable=False)
        sys.exit(1)

    # Surface harness logs for debugging
    if proc.stdout:
        for line in proc.stdout.splitlines():
            if not line.startswith("RESULT_JSON:"):
                print(line, file=sys.stderr)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            try:
                result = json.loads(line[len("RESULT_JSON:"):])
            except Exception as e:
                log_event("step_failed", id="add_to_cart", error=f"Could not parse result JSON: {e}", recoverable=False)
                sys.exit(1)
            break

    if result is None:
        log_event("step_failed", id="add_to_cart",
                  error=f"Browser flow did not return a result (exit {proc.returncode}). "
                        "Ensure Chrome is running and logged into Blinkit.",
                  recoverable=False)
        sys.exit(1)

    if result.get("error"):
        log_event("step_failed", id="add_to_cart", error=result["error"], recoverable=False)
        sys.exit(1)

    results = result.get("results", [])
    added = [r for r in results if r.get("status") == "added"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    failed = [r for r in results if r.get("status") == "failed"]

    log_event("step_done", id="add_to_cart",
              outputs={"added": len(added), "skipped": len(skipped), "failed": len(failed)},
              summary=f"{len(added)} added, {len(skipped)} skipped, {len(failed)} failed")

    # ---- Human-readable summary to stdout ----
    print("\n=== Blinkit cart summary ===")
    if result.get("query"):
        composed = result.get("composed_items") or []
        if composed:
            print(f"Request {result['query']!r} matched from your past orders: {', '.join(composed)}")
        else:
            print(f"Request {result['query']!r} did not match any products in your recent orders.")
    for r in results:
        tag = {"added": "ADDED  ", "skipped": "SKIPPED", "failed": "FAILED "}.get(r.get("status"), r.get("status"))
        prod = r.get("product") or "-"
        size = r.get("size") or ""
        price = r.get("price") or ""
        extra = f" ({size} {price})".rstrip().replace(" )", ")") if (size or price) else ""
        reason = f"  [{r.get('reason')}]" if r.get("reason") and r.get("status") != "added" else ""
        print(f"  {tag}  {r.get('item')} -> {prod}{extra}{reason}")
    if result.get("brands"):
        print(f"\nBrand preferences used: {', '.join(result['brands'][:10])}")
    print(f"\nReview & checkout your cart here: {result.get('cart_url')}")

    final_outputs = {
        "cart_url": result.get("cart_url"),
        "query": result.get("query"),
        "composed_items": result.get("composed_items", []),
        "added": added,
        "skipped": [{"item": r["item"], "reason": r.get("reason")} for r in skipped],
        "failed": [{"item": r["item"], "reason": r.get("reason")} for r in failed],
        "brands_used": result.get("brands", [])[:10],
    }

    if failed:
        # Items were searched but could not be added (transient/site issue) — non-zero exit.
        log_event("step_failed", id="add_to_cart",
                  error=f"{len(failed)} item(s) could not be added: " +
                        ", ".join(r["item"] for r in failed),
                  recoverable=True)
        log_event("workflow_done", outputs=final_outputs)
        sys.exit(1)

    log_event("workflow_done", outputs=final_outputs)


if __name__ == "__main__":
    main()
