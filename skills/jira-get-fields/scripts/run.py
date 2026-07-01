import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


STEP_ID = "get_issue_fields"


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


def basic_auth_header(email, api_token):
    token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def jira_request(domain, auth_header, path):
    url = f"https://{domain}{path}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def issue_path(ticket):
    quoted_ticket = urllib.parse.quote(ticket, safe="")
    query = urllib.parse.urlencode({"fields": "*all", "expand": "names,schema"})
    return f"/rest/api/3/issue/{quoted_ticket}?{query}"


def fetch_with_api_token(domain, email, api_token, ticket):
    auth_header = basic_auth_header(email, api_token)
    issue = jira_request(domain, auth_header, issue_path(ticket))
    metadata = jira_request(domain, auth_header, "/rest/api/3/field")
    return issue, metadata, "api_token"


def run_browser_fallback(domain, ticket):
    harness = os.environ.get("AI_MIME_BROWSER_HARNESS_BIN")
    if not harness:
        raise RuntimeError("API-token auth failed and AI_MIME_BROWSER_HARNESS_BIN is not configured.")

    code_template = r'''
import json

new_tab(__ISSUE_URL__)
wait_for_load()

code = """
return (async () => {
  const ticket = __TICKET__;
  const issuePath = `/rest/api/3/issue/${encodeURIComponent(ticket)}?fields=*all&expand=names,schema`;
  const issueResp = await fetch(issuePath, {
    credentials: "include",
    headers: {"Accept": "application/json"}
  });
  const issueText = await issueResp.text();
  if (!issueResp.ok) {
    return {
      ok: false,
      status: issueResp.status,
      detail: issueText.slice(0, 1000)
    };
  }
  const fieldsResp = await fetch("/rest/api/3/field", {
    credentials: "include",
    headers: {"Accept": "application/json"}
  });
  const fieldsText = await fieldsResp.text();
  if (!fieldsResp.ok) {
    return {
      ok: false,
      status: fieldsResp.status,
      detail: fieldsText.slice(0, 1000)
    };
  }
  return {
    ok: true,
    issue: JSON.parse(issueText),
    metadata: JSON.parse(fieldsText)
  };
})()
"""
code = code.replace("__TICKET__", json.dumps(__TICKET_VALUE__))
result = js(code)
print(json.dumps(result, ensure_ascii=False))
'''
    code = (
        code_template
        .replace("__ISSUE_URL__", json.dumps(f"https://{domain}/browse/{ticket}"))
        .replace("__TICKET_VALUE__", json.dumps(ticket))
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
    return result.get("issue"), result.get("metadata"), "browser_session"


def field_metadata_map(metadata):
    if not isinstance(metadata, list):
        return {}
    return {
        item.get("id"): item
        for item in metadata
        if isinstance(item, dict) and item.get("id")
    }


def extract_adf_text(node):
    """Extract readable text from Atlassian Document Format."""
    parts = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        node_type = value.get("type")
        if node_type == "text":
            parts.append(value.get("text", ""))
            return
        if node_type == "hardBreak":
            parts.append("\n")
            return

        before = len(parts)
        walk(value.get("content", []))
        if node_type in {"paragraph", "heading", "listItem"} and len(parts) > before:
            parts.append("\n")

    walk(node)
    text = "".join(parts)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def clean_comment(comment):
    if not isinstance(comment, dict):
        return comment
    body = comment.get("body")
    return {
        "author": clean_value("author", comment.get("author")),
        "body": extract_adf_text(body) if is_adf_doc(body) else clean_value("body", body),
        "created": comment.get("created"),
    }


def clean_subtask(subtask):
    if not isinstance(subtask, dict):
        return subtask
    fields = subtask.get("fields") if isinstance(subtask.get("fields"), dict) else {}
    return {
        "key": subtask.get("key"),
        "summary": fields.get("summary"),
        "status": clean_value("status", fields.get("status")),
        "issuetype": clean_value("issuetype", fields.get("issuetype")),
    }


def is_adf_doc(value):
    return isinstance(value, dict) and value.get("type") == "doc"


def clean_list_value(field_id, value):
    if field_id == "subtasks":
        return [clean_subtask(item) for item in value]
    return [clean_value(field_id, item) for item in value]


def clean_dict_value(field_id, value):
    if field_id == "comment":
        return [clean_comment(item) for item in value.get("comments", [])]
    if is_adf_doc(value):
        return extract_adf_text(value)
    if "displayName" in value:
        return value.get("displayName")
    if "name" in value:
        return value.get("name")
    if "value" in value and len(value) <= 4:
        return value.get("value")

    drop_keys = {"self", "avatarUrls", "iconUrl"}
    return {
        key: clean_value(field_id, item)
        for key, item in value.items()
        if key not in drop_keys
    }


def clean_value(field_id, value):
    if value is None:
        return None
    if isinstance(value, list):
        return clean_list_value(field_id, value)
    if isinstance(value, dict):
        return clean_dict_value(field_id, value)
    return value


def clean_jira_payload(raw_outputs):
    cleaned = {
        "ticket": raw_outputs.get("ticket"),
        "ticket_id": raw_outputs.get("ticket_id"),
        "ticket_url": raw_outputs.get("ticket_url"),
        "field_count": raw_outputs.get("field_count"),
        "fields": {},
        "auth_method": raw_outputs.get("auth_method"),
    }

    for field in raw_outputs.get("fields", []):
        if not isinstance(field, dict) or not field.get("id"):
            continue
        field_id = field["id"]
        output_field_id = "comments" if field_id == "comment" else field_id
        cleaned["fields"][output_field_id] = clean_value(field_id, field.get("value"))

    return cleaned


def build_outputs(domain, requested_ticket, issue, metadata, auth_method):
    if not isinstance(issue, dict):
        raise RuntimeError("Jira issue response was not a JSON object.")

    fields = issue.get("fields")
    if not isinstance(fields, dict):
        raise RuntimeError("Jira issue response did not contain a fields object.")

    names = issue.get("names") if isinstance(issue.get("names"), dict) else {}
    schemas = issue.get("schema") if isinstance(issue.get("schema"), dict) else {}
    metadata_by_id = field_metadata_map(metadata)

    field_items = []
    fields_by_id = {}
    for field_id, value in fields.items():
        metadata_item = metadata_by_id.get(field_id, {})
        schema = schemas.get(field_id) or metadata_item.get("schema")
        item = {
            "id": field_id,
            "name": names.get(field_id) or metadata_item.get("name") or field_id,
            "schema": schema,
            "value": value,
        }
        field_items.append(item)
        fields_by_id[field_id] = item

    ticket = issue.get("key") or requested_ticket
    outputs = {
        "ticket": ticket,
        "ticket_id": issue.get("id"),
        "ticket_url": f"https://{domain}/browse/{ticket}",
        "field_count": len(field_items),
        "fields": field_items,
        "fields_by_id": fields_by_id,
        "auth_method": auth_method,
    }
    return outputs


def main():
    parser = argparse.ArgumentParser(description="Fetch all fields for a Jira issue")
    parser.add_argument("--inputs-json", required=True, help="Path to inputs JSON file")
    args = parser.parse_args()

    inputs = load_json(args.inputs_json, "inputs")
    ticket = (inputs.get("ticket") or "").strip()
    if not ticket:
        print("Missing required input: ticket", file=sys.stderr)
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

    log_event("step_start", id=STEP_ID, title=f"Fetching fields for {ticket}")

    api_error = None
    result = None
    if email and api_token:
        try:
            result = fetch_with_api_token(domain, email, api_token, ticket)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            api_error = f"Jira API error {e.code}: {detail}"
        except urllib.error.URLError as e:
            api_error = f"Network error: {e.reason}"
        except Exception as e:
            api_error = str(e)
    else:
        api_error = "Missing Jira credentials (email and api_token)"

    if result is None:
        try:
            result = run_browser_fallback(domain, ticket)
        except Exception as e:
            if api_error:
                fail(f"{api_error}; browser fallback also failed: {e}")
            fail(str(e))

    try:
        issue, metadata, auth_method = result
        outputs = clean_jira_payload(build_outputs(domain, ticket, issue, metadata, auth_method))
    except Exception as e:
        fail(str(e))

    log_event(
        "step_done",
        id=STEP_ID,
        outputs={
            "ticket": outputs["ticket"],
            "ticket_url": outputs["ticket_url"],
            "field_count": outputs["field_count"],
            "auth_method": outputs["auth_method"],
        },
        summary=f"Fetched {outputs['field_count']} fields for {outputs['ticket']}",
    )
    log_event("workflow_done", outputs=outputs)
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
