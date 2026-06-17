# Browser-harness flow: create a dated folder under a Google Drive parent and
# upload a local file into it, then verify. Executed via:
#   "$AI_MIME_BROWSER_HARNESS_BIN" -c "<contents of this file>"
# All harness helpers (js, click_at_xy, goto_url, cdp, upload_file, ...) are
# pre-injected into globals by the harness. Parameters arrive via env vars:
#   DRIVE_PARENT_ID   - target parent folder id
#   DRIVE_FILE_PATH   - absolute path of local file to upload
#   DRIVE_BASE_NAME   - base folder name (e.g. "v0 - 31 May"); collisions get " - N"
# Emits exactly one line "RESULT_JSON:{...}" to stdout.

import os, time, json

PARENT_ID = os.environ["DRIVE_PARENT_ID"]
FILE_PATH = os.environ["DRIVE_FILE_PATH"]
BASE_NAME = os.environ["DRIVE_BASE_NAME"]
PARENT_URL = "https://drive.google.com/drive/u/0/folders/" + PARENT_ID


def emit(obj):
    print("RESULT_JSON:" + json.dumps(obj, ensure_ascii=False))


def fail(msg):
    emit({"ok": False, "error": msg})
    raise SystemExit(0)


def jget(finder):
    """Run a JS finder that returns a JSON string; parse and return the value."""
    raw = js(finder)
    if raw is None:
        return None
    if isinstance(raw, (dict, list, bool, int, float)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def click_center(finder, what):
    o = jget(finder)
    if not o or not isinstance(o, dict):
        fail("could not locate " + what)
    click_at_xy(o["x"], o["y"])
    return True


# --- open the parent folder in a NEW tab (never clobber an existing tab) ---
TAB_ID = new_tab(PARENT_URL)


def activate():
    """Attach to and visibly foreground our tab before any UI interaction;
    Drive's coordinate clicks fail when the tab is not the active one."""
    try:
        switch_tab(TAB_ID)
    except Exception:
        pass
    try:
        cdp("Target.activateTarget", targetId=TAB_ID)
    except Exception:
        pass


activate()
wait_for_load()
time.sleep(3)
if PARENT_ID not in (page_info().get("url") or ""):
    fail("failed to open parent folder " + PARENT_ID)


# --- compute a collision-free folder name from the live listing ---
def folder_exists(nm):
    finder = (
        "(()=>{const n=" + json.dumps(nm) + ";let f=false;"
        "document.querySelectorAll('[aria-label]').forEach(e=>{"
        "const a=e.getAttribute('aria-label')||'';"
        "const base=a.replace(/\\s*Shared folder.*/i,'').replace(/\\s*folder\\b.*/i,'').trim();"
        "if(base===n) f=true;});return JSON.stringify(f?1:0);})()"
    )
    return jget(finder) == 1

name = BASE_NAME
n = 2
while folder_exists(name):
    name = BASE_NAME + " - " + str(n)
    n += 1


# --- open the New menu and create the folder ---
NEW_BTN = (
    "(()=>{const e=document.querySelector('[guidedhelpid=new_menu_button]');"
    "if(!e)return JSON.stringify(null);const r=e.getBoundingClientRect();"
    "return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"
)


def menuitem(prefix):
    return (
        "(()=>{const items=[...document.querySelectorAll('[role=menuitem]')];"
        "for(const e of items){const t=(e.textContent||'').replace(/\\s+/g,' ').trim();"
        "if(t.indexOf(" + json.dumps(prefix) + ")===0){const r=e.getBoundingClientRect();"
        "if(r.width>0)return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});}}"
        "return JSON.stringify(null);})()"
    )


def button(label):
    return (
        "(()=>{const bs=[...document.querySelectorAll('button,[role=button]')];"
        "for(const e of bs){const t=(e.textContent||'').trim();"
        "if(t===" + json.dumps(label) + "){const r=e.getBoundingClientRect();"
        "if(r.width>0)return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});}}"
        "return JSON.stringify(null);})()"
    )


DIALOG_INPUT = (
    "(()=>{const ins=[...document.querySelectorAll('input')];"
    "for(const e of ins){const r=e.getBoundingClientRect();"
    "if(r.width>120 && /Untitled folder/i.test(e.value||'')){"
    "return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});}}"
    "return JSON.stringify(null);})()"
)

click_center(NEW_BTN, "New button")
time.sleep(1.2)
click_center(menuitem("New folder"), "New folder menu item")
time.sleep(1.3)
click_center(DIALOG_INPUT, "New folder name field")
time.sleep(0.3)
press_key("a", modifiers=4)  # Cmd+A select existing text
time.sleep(0.2)
type_text(name)
time.sleep(0.3)
click_center(button("Create"), "Create button")
time.sleep(3)

# --- locate the new folder's id from the listing ---
NEWID = (
    "(()=>{const want=" + json.dumps(name) + ";let res=null;"
    "document.querySelectorAll('[aria-label]').forEach(e=>{"
    "const a=e.getAttribute('aria-label')||'';"
    "const base=a.replace(/\\s*Shared folder.*/i,'').replace(/\\s*folder\\b.*/i,'').trim();"
    "if(base===want){let nnn=e,id=null,d=0;while(nnn&&d<6){"
    "if(nnn.getAttribute&&nnn.getAttribute('data-id')){id=nnn.getAttribute('data-id');break;}"
    "nnn=nnn.parentElement;d++;}if(id)res=id;}});return JSON.stringify(res);})()"
)
new_folder_id = jget(NEWID)
if not new_folder_id:
    fail("created folder '" + name + "' but could not resolve its id")

# --- open the new folder directly (robust) ---
NEW_URL = "https://drive.google.com/drive/u/0/folders/" + new_folder_id
activate()
goto_url(NEW_URL)
wait_for_load()
time.sleep(3)
activate()
if new_folder_id not in (page_info().get("url") or ""):
    fail("could not open the new folder " + new_folder_id)

# --- upload the local file via CDP file-chooser interception ---
cdp("Page.enable")
cdp("Page.setInterceptFileChooserDialog", enabled=True)
drain_events()
click_center(NEW_BTN, "New button (upload)")
time.sleep(1.2)
click_center(menuitem("File upload"), "File upload menu item")
time.sleep(1.6)
methods = [e.get("method") for e in drain_events()]
if "Page.fileChooserOpened" not in methods:
    # input may still exist; continue but note it
    pass
# the dynamically created <input type=file> now exists
exists = jget("(()=>{return JSON.stringify(document.querySelectorAll('input[type=file]').length);})()")
if not exists:
    cdp("Page.setInterceptFileChooserDialog", enabled=False)
    fail("file input did not appear after clicking File upload")
upload_file("input[type=file]", FILE_PATH)
cdp("Page.setInterceptFileChooserDialog", enabled=False)
time.sleep(2)

# --- wait for the upload to complete ---
STATUS = (
    "(()=>{const t=document.body.innerText||'';"
    "let s='';if(/Uploading\\s+\\d+\\s+item/i.test(t))s='uploading';"
    "if(/upload[s]?\\s+complete/i.test(t)||/\\b1 upload complete\\b/i.test(t))s='complete';"
    "return JSON.stringify(s);})()"
)
deadline = time.time() + 420
status = ""
while time.time() < deadline:
    status = jget(STATUS) or ""
    if status == "complete":
        break
    time.sleep(5)

# --- verify the file resides in the new folder ---
activate()
goto_url(NEW_URL)
wait_for_load()
time.sleep(3)
fname = os.path.basename(FILE_PATH)
VERIFY = (
    "(()=>{const want=" + json.dumps(fname) + ";let res=null;"
    "document.querySelectorAll('[aria-label]').forEach(e=>{"
    "const a=e.getAttribute('aria-label')||'';"
    "if(a.indexOf(want)===0){let nnn=e,id=null,d=0;while(nnn&&d<6){"
    "if(nnn.getAttribute&&nnn.getAttribute('data-id')){id=nnn.getAttribute('data-id');break;}"
    "nnn=nnn.parentElement;d++;}res={id:id,label:a.slice(0,60)};}});"
    "return JSON.stringify(res);})()"
)
found = jget(VERIFY)

emit({
    "ok": bool(found),
    "folder_name": name,
    "new_folder_id": new_folder_id,
    "uploaded_file_id": (found or {}).get("id") if isinstance(found, dict) else None,
    "upload_status": status or ("present" if found else "unknown"),
    "verified": bool(found),
    "file_label": (found or {}).get("label") if isinstance(found, dict) else None,
})
