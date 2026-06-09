#!/usr/bin/env python3
"""
Skill runner for: book a train ticket on IRCTC (macOS, via browser-harness).

Contract:
    python scripts/run.py --inputs-json /path/to/inputs.json

This script is a thin orchestrator around the domain skill at
    harness/browser-harness/agent-workspace/domain-skills/irctc/booking_fsm.py

It:
  1. Loads + validates the JSON inputs (mirrors `_parse_input` rules).
  2. Builds the 8-field CSV the FSM expects:
        "<from>, <to>, <YYYY-MM-DD>, <name|name|...>, <sex|sex|...>, <age|age|...>, <train>, <class>"
  3. Pre-flight: asks browser-harness whether an IRCTC tab is open AND
     logged in (`Welcome ` visible, `LOGIN/SIGN UP` not visible). If not,
     exits 3 with clear instructions to the user.
  4. Streams a verbose progress log to stderr (state-prefixed lines that
     match the FSM's internal states).
  5. Invokes `browser-harness -c` with a small driver snippet that
     `exec`s booking_fsm.py and calls `book_ticket(<csv>)`. The CSV is
     handed in via env var (`IRCTC_CSV`) so we never have to escape it
     through the shell.
  6. Parses the FSM's JSON return value, prints it on stdout (one line),
     and maps `status` -> exit code.

Pre-condition (per booking_fsm.py docstring): the user MUST have Chrome
open with https://www.irctc.co.in/nget/train-search loaded and be
logged in BEFORE running. IRCTC binds auth to per-tab sessionStorage,
so the FSM refuses to open new tabs or switch between IRCTC tabs.

Exit codes:
    0 — FSM returned status="success" (PASSENGER_FORM_FILLED).
    2 — FSM returned status="failed" (see `state` / `error` in stdout JSON).
    3 — Pre-flight failed: no IRCTC tab open, or no tab logged in.
    4 — Input validation failed (before touching the browser).
    5 — Could not invoke browser-harness, or it returned malformed output.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants — keep in sync with booking_fsm.py
# ---------------------------------------------------------------------------

# Absolute path to the upstream FSM. Resolved at import time so the script
# works no matter where the user runs it from.
HARNESS_ROOT = Path(
    "/Users/prakharjain/code/ai_mime/harness/browser-harness"
).resolve()
BOOKING_FSM_PATH = (
    HARNESS_ROOT / "agent-workspace" / "domain-skills" / "irctc" / "booking_fsm.py"
).resolve()

VALID_CLASS_CODES = {"EA", "1A", "EC", "2A", "FC", "3A", "3E", "CC", "SL", "2S"}
VALID_SEX = {"M", "F", "T", "male", "female", "trans", "transgender",
             "m", "f", "t"}

# Pre-normalize common city names to IRCTC station codes BEFORE handing to
# the FSM. Mirrors `_CITY_DEFAULTS` in booking_fsm.py. We do this in the
# wrapper because the FSM's `_norm_station` matches the [A-Z]{2,5} "code"
# regex first — so 5-letter city names like DELHI / PUNE get misclassified
# as codes and produce "no autocomplete row matched code \'DELHI\'".
CITY_TO_CODE = {
    "bhopal": "BPL",
    "delhi": "NDLS", "new delhi": "NDLS",
    "mumbai": "CSMT", "mumbai cst": "CSMT", "mumbai vt": "CSMT",
    "mumbai central": "MMCT",
    "bangalore": "SBC", "bengaluru": "SBC",
    "chennai": "MAS",
    "kolkata": "HWH",
    "hyderabad": "HYB",
    "pune": "PUNE",
    "ahmedabad": "ADI",
}


def _resolve_station(s: str) -> str:
    """Pre-resolve city name -> IRCTC code; otherwise return the input unchanged."""
    return CITY_TO_CODE.get(s.strip().lower(), s.strip())


SKILL_ID = "book-ticket-irctc"


# ---------------------------------------------------------------------------
# Logging — state-prefixed, stderr-only, line-buffered
# ---------------------------------------------------------------------------

def log(state: str, msg: str) -> None:
    print(f"[{state}] {msg}", file=sys.stderr, flush=True)


def banner(msg: str) -> None:
    bar = "=" * max(40, len(msg) + 4)
    print(f"\n{bar}\n  {msg}\n{bar}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Input loading + validation (mirrors booking_fsm._parse_input rules)
# ---------------------------------------------------------------------------

def _load_inputs(path_str: str) -> dict:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise SystemExit(f"inputs file does not exist: {path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"inputs file is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise SystemExit(
            f"inputs JSON must be an object, got {type(data).__name__}"
        )
    return data


def _validate_date(date_s: str) -> _dt.date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(date_s, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"date {date_s!r}: use YYYY-MM-DD or DD/MM/YYYY")


def _validate(inputs: dict) -> dict:
    """Validate user-facing inputs and return a normalized dict ready for CSV."""
    required = ["from", "to", "date", "passengers"]
    missing = [k for k in required if not inputs.get(k)]
    if missing:
        raise SystemExit(f"missing required input(s): {', '.join(missing)}")

    frm_raw = str(inputs["from"]).strip()
    to_raw = str(inputs["to"]).strip()
    if not frm_raw or not to_raw:
        raise SystemExit("`from` and `to` must be non-empty strings")
    frm = _resolve_station(frm_raw)
    to = _resolve_station(to_raw)
    if frm != frm_raw:
        print(f"[PARSE] resolved city {frm_raw!r} -> code {frm!r}", file=__import__("sys").stderr, flush=True)
    if to != to_raw:
        print(f"[PARSE] resolved city {to_raw!r} -> code {to!r}", file=__import__("sys").stderr, flush=True)

    d = _validate_date(str(inputs["date"]).strip())

    train = str(inputs.get("train") or "").strip()
    klass = str(inputs.get("class") or "").strip().upper()
    if klass and klass not in VALID_CLASS_CODES:
        raise SystemExit(
            f"class {klass!r}: expected one of {sorted(VALID_CLASS_CODES)} "
            f"(or empty to ask the user via dialog)"
        )

    passengers = inputs.get("passengers")
    if not isinstance(passengers, list) or not passengers:
        raise SystemExit("`passengers` must be a non-empty array")
    if len(passengers) > 6:
        raise SystemExit(
            f"too many passengers ({len(passengers)}): IRCTC General-quota cap is 6"
        )

    names, sexes, ages = [], [], []
    for i, p in enumerate(passengers, start=1):
        if not isinstance(p, dict):
            raise SystemExit(f"passenger #{i}: must be an object")
        nm = str(p.get("name") or "").strip()
        sx_raw = str(p.get("sex") or "").strip()
        ag_raw = p.get("age")
        if not nm:
            raise SystemExit(f"passenger #{i}: `name` is required")
        if sx_raw not in VALID_SEX:
            raise SystemExit(
                f"passenger #{i}: sex {sx_raw!r} — expected M/F/T (or male/female/trans)"
            )
        try:
            ag = int(ag_raw)
        except (TypeError, ValueError):
            raise SystemExit(f"passenger #{i}: age {ag_raw!r} is not an integer")
        if ag < 1 or ag > 125:
            raise SystemExit(f"passenger #{i}: age {ag} out of range (1-125)")
        # IRCTC's passengerName field is maxlength=16. Warn (don't fail) if longer —
        # the FSM truncates with [:16] anyway.
        if len(nm) > 16:
            log("PARSE", f"warning: passenger #{i} name {nm!r} > 16 chars; IRCTC will truncate")
        names.append(nm)
        sexes.append(sx_raw)
        ages.append(str(ag))

    return {
        "from": frm,
        "to": to,
        "date": d.isoformat(),
        "names": names,
        "sexes": sexes,
        "ages": ages,
        "train": train,
        "class": klass,
    }


def _build_csv(v: dict) -> str:
    # 8 fields: from, to, date, name(s), sex(es), age(s), train, class
    # Multi-passenger: pipe-join name / sex / age lists.
    return ", ".join([
        v["from"],
        v["to"],
        v["date"],
        "|".join(v["names"]),
        "|".join(v["sexes"]),
        "|".join(v["ages"]),
        v["train"],
        v["class"],
    ])


# ---------------------------------------------------------------------------
# browser-harness invocation
# ---------------------------------------------------------------------------

def _run_harness(code: str, *, timeout: float = 600.0,
                 extra_env: dict | None = None) -> tuple[int, str, str]:
    """Run a snippet inside `browser-harness -c` and return (rc, stdout, stderr).

    stderr is also tee'd live to *our* stderr so the user sees real-time
    progress (browser-harness logs daemon + cdp activity there).
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    harness_bin = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness_bin:
        raise SystemExit("AI_MIME_BROWSER_HARNESS_BIN not configured")
    proc = subprocess.Popen(
        [harness_bin, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Stream stderr live, buffer stdout.
    err_lines: list[str] = []
    out_chunks: list[str] = []

    # Read stderr in a thread so we don't deadlock on stdout pipe pressure.
    import threading

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_lines.append(line)
            sys.stderr.write(line)
            sys.stderr.flush()

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    try:
        out_text, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise SystemExit(
            f"browser-harness timed out after {timeout:.0f}s. "
            f"Re-run, and if it persists try `browser-harness --doctor`."
        )
    out_chunks.append(out_text or "")
    t.join(timeout=2.0)

    return proc.returncode, "".join(out_chunks), "".join(err_lines)


# Probe snippet — checks for an IRCTC tab that is logged in. Prints a
# single JSON line to stdout: {"ok": bool, "reason": str, "tabs": [...]}.
_PROBE_CODE = r"""
import json as _json
out = {"ok": False, "reason": "", "tabs": []}
try:
    tabs = list_tabs() or []
    irctc_tabs = [t for t in tabs if "irctc.co.in" in (t.get("url") or "")]
    out["tabs"] = [{"url": t.get("url",""), "title": t.get("title","")} for t in irctc_tabs]
    if not irctc_tabs:
        out["reason"] = "no_irctc_tab"
    else:
        logged_in = None
        for t in irctc_tabs:
            try:
                switch_tab(t["targetId"])
            except Exception as e:
                continue
            import time as _t; _t.sleep(0.3)
            li = js("return !!(document.body && /Welcome\\s+\\S/.test(document.body.innerText) "
                    "&& !/LOGIN\\/SIGN UP/i.test(document.body.innerText))")
            if li:
                logged_in = t
                break
        if logged_in:
            out["ok"] = True
            out["reason"] = "logged_in"
            out["pinned_tab"] = {"url": logged_in.get("url",""), "title": logged_in.get("title","")}
        else:
            out["reason"] = "irctc_tab_but_not_logged_in"
except Exception as e:
    out["reason"] = f"probe_error: {type(e).__name__}: {e}"
print("__PROBE_JSON__" + _json.dumps(out) + "__END__")
"""


def _preflight() -> dict:
    log("PREFLIGHT", "probing browser-harness for a logged-in IRCTC tab ...")
    rc, out, _ = _run_harness(_PROBE_CODE, timeout=60.0)
    m = re.search(r"__PROBE_JSON__(\{.*?\})__END__", out, re.DOTALL)
    if not m:
        log("PREFLIGHT", f"could not parse probe output (rc={rc})")
        if out.strip():
            log("PREFLIGHT", f"raw stdout: {out.strip()[:400]}")
        raise SystemExit(5)
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log("PREFLIGHT", f"probe JSON decode error: {e}")
        raise SystemExit(5)


# Driver snippet — loads booking_fsm.py via exec, reads the CSV from an
# env var (`IRCTC_CSV`), calls book_ticket(), and emits a sentinel JSON.
_DRIVER_CODE_TEMPLATE = r"""
import json as _json, os as _os
fsm_path = __FSM_PATH__
print("[DRIVER] loading FSM from " + fsm_path, flush=True)
with open(fsm_path) as _f:
    _src = _f.read()
exec(compile(_src, fsm_path, "exec"))
csv = _os.environ["IRCTC_CSV"]
print("[DRIVER] book_ticket(csv) — csv=" + repr(csv), flush=True)
try:
    _result = book_ticket(csv)
except Exception as _e:
    _result = {"status": "failed", "state": "DRIVER",
               "error": f"{type(_e).__name__}: {_e}", "details": {}}
print("__FSM_JSON__" + _json.dumps(_result) + "__END__", flush=True)
"""


def _run_fsm(csv: str) -> dict:
    driver = _DRIVER_CODE_TEMPLATE.replace("__FSM_PATH__", json.dumps(str(BOOKING_FSM_PATH)))
    log("FSM", f"invoking browser-harness; CSV passed via $IRCTC_CSV ({len(csv)} chars)")
    rc, out, _ = _run_harness(driver, timeout=900.0, extra_env={"IRCTC_CSV": csv})
    m = re.search(r"__FSM_JSON__(\{.*\})__END__", out, re.DOTALL)
    if not m:
        log("FSM", f"could not find result sentinel in harness output (rc={rc})")
        # Surface a snippet of stdout to help debugging.
        snippet = out.strip()[-800:]
        if snippet:
            log("FSM", f"tail of harness stdout:\n{snippet}")
        raise SystemExit(5)
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log("FSM", f"FSM JSON decode error: {e}")
        raise SystemExit(5)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=SKILL_ID,
        description="Book a train ticket on IRCTC via the browser-harness FSM."
    )
    parser.add_argument(
        "--inputs-json",
        required=True,
        help="Path to JSON inputs file (see SKILL.md for schema).",
    )
    args = parser.parse_args(argv)

    banner(f"{SKILL_ID} — IRCTC train ticket booking")
    log("INIT", f"inputs file: {args.inputs_json}")
    log("INIT", f"FSM path:    {BOOKING_FSM_PATH}")
    if not BOOKING_FSM_PATH.exists():
        log("INIT", f"ERROR: booking_fsm.py not found at {BOOKING_FSM_PATH}")
        return 5

    # ---- 1. Load + validate inputs ---------------------------------------
    try:
        inputs = _load_inputs(args.inputs_json)
        v = _validate(inputs)
    except SystemExit as e:
        log("PARSE", f"input validation failed: {e}")
        print(json.dumps({"status": "failed", "state": "PARSE",
                          "error": str(e), "details": {}}))
        return 4

    csv = _build_csv(v)
    log("PARSE",
        f"from={v['from']} to={v['to']} date={v['date']} "
        f"passengers={len(v['names'])} train={v['train'] or '<ask>'} "
        f"class={v['class'] or '<ask>'}")
    log("PARSE", f"csv=\"{csv}\"")

    # ---- 2. Pre-flight ---------------------------------------------------
    probe = _preflight()
    reason = probe.get("reason", "")
    tabs = probe.get("tabs") or []
    if not probe.get("ok"):
        if reason == "no_irctc_tab":
            log("PREFLIGHT", "FAIL: no IRCTC tab open.")
            log("PREFLIGHT",
                "ACTION: Open Chrome -> https://www.irctc.co.in/nget/train-search, "
                "log in, then re-run this script.")
        elif reason == "irctc_tab_but_not_logged_in":
            log("PREFLIGHT",
                "FAIL: found IRCTC tab(s) but none show `Welcome <name>` — not logged in.")
            for t in tabs:
                log("PREFLIGHT", f"  tab: {t.get('title','')!r} -> {t.get('url','')}")
            log("PREFLIGHT",
                "ACTION: Log in IN THAT SAME TAB. Do NOT open IRCTC in a second "
                "tab (IRCTC drops auth across tabs). Then re-run.")
        else:
            log("PREFLIGHT", f"FAIL: {reason}")
        print(json.dumps({"status": "failed", "state": "PREFLIGHT",
                          "error": reason or "preflight_failed",
                          "details": {"tabs": tabs}}))
        return 3
    pinned_url = (probe.get("pinned_tab") or {}).get("url", "") or ""
    log("PREFLIGHT", f"OK: pinned tab -> {pinned_url or '?'}")

    # Restart-trap detection: if the logged-in tab is anywhere downstream of
    # /train-search (e.g. left over on /booking/train-list or /booking/psgninput
    # from a previous run), the FSM will call `goto_url('/nget/train-search')`
    # which does a full Page.navigate -- IRCTC drops sessionStorage auth on
    # that full reload and the FSM bails with "Logged out after navigating to
    # /train-search". Refuse to run here with a clear actionable message so
    # we don't actually evict the user's session.
    if pinned_url and "/nget/train-search" not in pinned_url:
        log("PREFLIGHT",
            "FAIL: logged-in IRCTC tab is NOT on /nget/train-search.")
        log("PREFLIGHT", f"      current url: {pinned_url}")
        log("PREFLIGHT",
            "      Running now would force a full-page reload to "
            "/train-search, which IRCTC treats as a session eviction "
            "(sessionStorage-bound auth).")
        log("PREFLIGHT",
            "ACTION: In that SAME IRCTC tab, click the 'Train Search' link "
            "in IRCTC's top navigation bar (SPA navigation - preserves your "
            "session). The URL should change to /nget/train-search while you "
            "still see 'Welcome <name>'. Do NOT type the URL, hit reload, or "
            "open a new tab. Then re-run this script.")
        print(json.dumps({"status": "failed", "state": "PREFLIGHT",
                          "error": "logged_in_tab_not_on_train_search",
                          "details": {"pinned_tab_url": pinned_url,
                                      "tabs": tabs}}))
        return 3

    # ---- 3. Run FSM ------------------------------------------------------
    banner("Driving booking_fsm.book_ticket() inside browser-harness")
    log("FSM",
        "user-action note: a native dialog may pop if `train` or `class` is empty; "
        "and if the post-Book-Now login modal opens, the FSM blocks on stdin — "
        "log in in the browser, then press Enter in this terminal.")
    result = _run_fsm(csv)

    # ---- 4. Surface result ----------------------------------------------
    status = (result or {}).get("status", "failed")
    state = (result or {}).get("state", "?")
    err = (result or {}).get("error")
    if status == "success":
        log("DONE", f"SUCCESS — state={state}")
        details = result.get("details") or {}
        if "chosen_train" in details:
            ct = details["chosen_train"]
            log("DONE", f"booked train: {ct.get('number')} {ct.get('name')!r}")
        log("DONE",
            "FSM stopped at PASSENGER_FORM_FILLED — review & complete payment "
            "manually in the browser.")
    else:
        log("DONE", f"FAILED — state={state} error={err!r}")

    # Single-line JSON to stdout (verbatim FSM return).
    print(json.dumps(result))
    return 0 if status == "success" else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
