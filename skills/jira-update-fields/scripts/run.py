import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


STEP_ID = "update_issue_field"


def log_event(event_type, **kwargs):
    print(json.dumps({"event": event_type, **kwargs}, ensure_ascii=False),
          file=sys.stderr, flush=True)


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {label}: {e}", file=sys.stderr)
        sys.exit(1)


def fail(message, recoverable=False):
    log_event("step_failed", id=STEP_ID, error=message, recoverable=recoverable)
    sys.exit(1)


def normalize_domain(domain):
    return (domain or "").replace("https://", "").replace("http://", "").strip("/")


def description_to_adf(text):
    paragraphs = []
    lines = str(text).splitlines() or [""]
    for line in lines:
        paragraph = {"type": "paragraph"}
        if line:
            paragraph["content"] = [{"type": "text", "text": line}]
        paragraphs.append(paragraph)
    return {"type": "doc", "version": 1, "content": paragraphs}


def jira_field_value(field, value):
    if field == "description" and isinstance(value, str):
        return description_to_adf(value)
    return value


def basic_auth_header(email, api_token):
    token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def jira_request(domain, auth_header, path, method="GET", payload=None):
    url = f"https://{domain}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, (json.loads(body) if body else None)


def update_with_api_token(domain, email, api_token, ticket, field, value):
    auth_header = basic_auth_header(email, api_token)
    payload = {"fields": {field: jira_field_value(field, value)}}
    status, _ = jira_request(
        domain,
        auth_header,
        f"/rest/api/3/issue/{ticket}",
        method="PUT",
        payload=payload,
    )
    verify_status, verify_body = jira_request(
        domain,
        auth_header,
        f"/rest/api/3/issue/{ticket}?fields={field}",
        method="GET",
    )
    fields = verify_body.get("fields", {}) if isinstance(verify_body, dict) else {}
    return {
        "status": status,
        "verify_status": verify_status,
        "verified_field_present": field in fields,
        "auth_method": "api_token",
    }


def run_browser_fallback(domain, ticket, field, value):
    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness:
        raise RuntimeError("API-token auth failed and AI_MIME_BROWSER_HARNESS_BIN is not configured.")

    payload = {"fields": {field: jira_field_value(field, value)}}
    code_template = r'''
import json

new_tab(__ISSUE_URL__)
wait_for_load()

code = """
return (async () => {
  const ticket = __TICKET__;
  const field = __FIELD__;
  const payload = __PAYLOAD__;
  const updateResp = await fetch(`/rest/api/3/issue/${encodeURIComponent(ticket)}`, {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Atlassian-Token": "no-check"
    },
    body: JSON.stringify(payload)
  });
  const detail = await updateResp.text();
  let verifyStatus = null;
  let verifiedFieldPresent = false;
  if (updateResp.ok) {
    const verifyResp = await fetch(`/rest/api/3/issue/${encodeURIComponent(ticket)}?fields=${encodeURIComponent(field)}`, {
      credentials: "include",
      headers: {"Accept": "application/json"}
    });
    verifyStatus = verifyResp.status;
    const verifyBody = await verifyResp.json();
    verifiedFieldPresent = !!(verifyBody.fields && Object.prototype.hasOwnProperty.call(verifyBody.fields, field));
  }
  return {
    ok: updateResp.ok,
    status: updateResp.status,
    detail: detail.slice(0, 1000),
    verify_status: verifyStatus,
    verified_field_present: verifiedFieldPresent
  };
})()
"""
code = code.replace("__TICKET__", json.dumps(__TICKET_VALUE__))
code = code.replace("__FIELD__", json.dumps(__FIELD_VALUE__))
code = code.replace("__PAYLOAD__", json.dumps(__PAYLOAD_VALUE__))
result = js(code)
print(json.dumps(result, ensure_ascii=False))
'''
    code = (
        code_template
        .replace("__ISSUE_URL__", json.dumps(f"https://{domain}/browse/{ticket}"))
        .replace("__TICKET_VALUE__", json.dumps(ticket))
        .replace("__FIELD_VALUE__", json.dumps(field))
        .replace("__PAYLOAD_VALUE__", json.dumps(payload))
    )
    proc = subprocess.run(
        [harness, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Browser fallback failed: {proc.stderr.strip() or proc.stdout.strip()}")
    result = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
    if not isinstance(result, dict):
        raise RuntimeError(f"Browser fallback did not return JSON: {proc.stdout.strip()}")
    if not result.get("ok"):
        raise RuntimeError(f"Browser fallback Jira API error {result.get('status')}: {result.get('detail')}")
    return {
        "status": result.get("status"),
        "verify_status": result.get("verify_status"),
        "verified_field_present": result.get("verified_field_present"),
        "auth_method": "browser_session",
    }


def main():
    parser = argparse.ArgumentParser(description="Update a Jira issue field")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    inputs = load_json(args.inputs_json, "inputs")
    ticket = (inputs.get("ticket") or "").strip()
    field = (inputs.get("field") or "").strip()
    value = inputs.get("value")

    if not ticket:
        print("Missing required input: ticket", file=sys.stderr)
        sys.exit(1)
    if not field:
        print("Missing required input: field", file=sys.stderr)
        sys.exit(1)
    if value is None or (isinstance(value, str) and not value.strip()):
        print("Missing required input: value", file=sys.stderr)
        sys.exit(1)

    creds_path = os.environ.get("AI_MIME_CREDENTIALS_PATH")
    if not creds_path:
        fail("AI_MIME_CREDENTIALS_PATH not configured")
    creds = load_json(creds_path, "credentials")
    jira = creds.get("jira", {})
    email = jira.get("email")
    api_token = jira.get("api_token")
    domain = normalize_domain(jira.get("domain"))
    if not domain:
        fail("Missing Jira credential: domain")

    log_event("step_start", id=STEP_ID, title=f"Updating {field} on {ticket}")

    api_error = None
    result = None
    if email and api_token:
        try:
            result = update_with_api_token(domain, email, api_token, ticket, field, value)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            api_error = f"Jira API error {e.code}: {detail}"
        except urllib.error.URLError as e:
            api_error = f"Network error: {e.reason}"
    else:
        api_error = "Missing Jira credentials (email and api_token)"

    if result is None:
        try:
            result = run_browser_fallback(domain, ticket, field, value)
        except Exception as e:
            if api_error:
                fail(f"{api_error}; browser fallback also failed: {e}")
            fail(str(e))

    ticket_url = f"https://{domain}/browse/{ticket}"
    outputs = {
        "ticket": ticket,
        "field": field,
        "ticket_url": ticket_url,
        "updated": result.get("status") == 204,
        "verified": bool(result.get("verified_field_present")),
        "auth_method": result.get("auth_method"),
    }
    log_event(
        "step_done",
        id=STEP_ID,
        outputs=outputs,
        summary=f"Updated {field} on {ticket}",
    )
    log_event("workflow_done", outputs=outputs)
    print(f"Updated {field} on {ticket}: {ticket_url}")


if __name__ == "__main__":
    main()
