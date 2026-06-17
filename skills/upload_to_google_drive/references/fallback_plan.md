# Fallback plan — manually upload the file into a new dated Drive folder

Use this if `run.sh` fails. Everything is a constant; there are no user inputs.

Constants:
- Parent Drive folder: **ai mime - binary**
  https://drive.google.com/drive/u/0/folders/1M1E4LNjEXLvaH7j5JY1Un3XRx6M6mtvV
- Local file: `/Users/prakharjain/code/ai_mime/dist/AI Mime.dmg`
- New folder name: `v0 - <today's date>` formatted as `v0 - <day-no-leading-zero> <FullMonth>`
  (e.g. `v0 - 31 May`). If that folder already exists under the parent, append ` - 2`,
  then ` - 3`, etc., until the name is free.

## Subtask 0 — Open the target Google Drive folder
Intent: Get the "ai mime - binary" folder open in the signed-in Chrome.
- Open Chrome (the user is already signed into Google Drive).
- Go to the parent folder URL above.
- Confirm the breadcrumb reads `My Drive › ai mime - binary` and the existing
  `v0 - …` folders are listed.
Notes: The automation re-attaches to any open `drive.google.com` tab and navigates it
to the parent URL; the AI Mime app sometimes steals the active Chrome tab, so always
re-navigate by URL and verify the URL contains the parent id before acting.

## Subtask 1 — Create the new dated folder and open it
Intent: Create `v0 - <today>` (collision-suffixed) under the parent and open it.
- Click **New** (top-left; `[guidedhelpid=new_menu_button]`).
- Click **New folder** in the menu (role=menuitem starting with "New folder").
- In the dialog, the name field is pre-filled "Untitled folder" and pre-selected —
  select-all (Cmd+A) and type the computed name.
- Click **Create**.
- The new folder appears selected; its id is on the nearest `[data-id]` ancestor of the
  element whose `aria-label` equals the folder name. Open it (double-click, or navigate to
  `https://drive.google.com/drive/u/0/folders/<NEW_ID>`).
Notes: VERIFY you are inside the parent before clicking Create — a drifted "My Drive"
context creates the folder in the wrong place. Drive folder shortcut "c then f" also opens
the New-folder dialog, but menu clicks were the validated path. Folder aria-labels look like
"v0 - 31 May Shared folder" — strip the trailing " Shared folder"/" folder" to get the name.

## Subtask 2 — Upload the file into the new folder
Intent: Upload `AI Mime.dmg` into the new folder and confirm it lands.
- Inside the new folder, click **New › File upload** (role=menuitem starting with
  "File upload"). This opens the macOS file picker.
- In the picker, select `/Users/prakharjain/code/ai_mime/dist/AI Mime.dmg` and click **Open**.
- Wait for the upload toast to read "upload complete" (the file is ~246.6 MB, allow a
  couple of minutes).
- Verify: reload the new folder; a row labelled `AI Mime.dmg` with a non-zero size
  (~246.6 MB) must be present.
Notes (automation specifics): the script suppresses the native picker via CDP
`Page.setInterceptFileChooserDialog`, then sets the file programmatically with
`DOM.setFileInputFiles` on the dynamically-created `input[type=file]` (helper
`upload_file("input[type=file]", path)`). A `Page.fileChooserOpened` event confirms the
upload trigger fired. For a manual run you simply use the real file picker instead.
