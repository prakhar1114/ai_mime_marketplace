# AI Mime Skills Marketplace

Static marketplace for AI Mime workflows and automations. The repo is designed
to be hosted directly on GitHub Pages: the webpage, manifest, icons, and zipped
workflow packages are all static files.

## Repository Layout

```text
docs/
  index.html              # Marketplace webpage
  manifest.json           # Machine-readable package catalog
  app.js                  # Static catalog UI
  styles.css              # Static catalog styling
  icons/                  # Listing icons
  packages/               # Installable workflow zips
workflows/
  <workflow-id>/          # Clean source copy for each package
scripts/
  add_to_marketplace.py   # Add a workflow or skill to the marketplace
  package_workflows.py    # Rebuild package zips and checksums
```

## Custom Domain Setup

Publish this repository with GitHub Pages using the `docs/` directory, configured with the custom domain `market.aimime.cc`. The public URLs will look like:

```text
https://market.aimime.cc/
https://market.aimime.cc/manifest.json
https://market.aimime.cc/packages/<workflow-id>.zip
```

The AI Mime app should read `manifest.json`, show the workflow metadata, download
the selected package, verify `sha256`, preview it through the import validator,
and then install it into the user's local `workflows/` directory.

## Adding A Workflow

Use `scripts/add_to_marketplace.py` with either a full AI Mime workflow directory
or a bare skill directory.

```bash
cd /Users/prakharjain/code/ai_mime_marketplace

scripts/add_to_marketplace.py /path/to/workflow \
  --tag google-drive \
  --requires-login \
  --side-effect "Uploads a local file to Google Drive."
```

Useful options:

```bash
--dry-run                         # Show detected values without writing
--replace                         # Replace an existing marketplace item
--id upload-to-google-drive        # Override marketplace id/workflow slug
--name "Upload to Google Drive"    # Override display name
--description "..."               # Override listing description
--empty-plan                      # Write optimized_plan.json as {}
--stops-before-payment yes        # Mark checkout/payment behavior
--tag docs --tag upload           # Add multiple tags
```

The add script:

- copies only marketplace-relevant files;
- removes generated state such as `agent/`, `runs/`, `outputs/`, `.venv/`,
  caches, logs, screenshots, and `.DS_Store`;
- ensures `metadata.json`, `schema.json`, and `optimized_plan.json` exist;
- ensures `run.sh` is executable;
- validates the required skill package files;
- writes `docs/packages/<workflow-id>.zip`;
- upserts the item in `docs/manifest.json`.

## Rebuilding Packages

After manually editing anything under `workflows/`, rebuild package zips and
refresh manifest checksums:

```bash
python3 scripts/package_workflows.py
```

This recreates `docs/packages/*.zip`, updates each item's `package_url`,
`sha256`, and `size_bytes`, and preserves the rest of the manifest metadata.

## Manifest Contract

Each item in `docs/manifest.json` describes one installable workflow package:

```json
{
  "id": "upload-to-google-drive",
  "name": "Upload to Google Drive",
  "description": "Upload a local file to Google Drive.",
  "type": "workflow",
  "version": "0.1.0",
  "author": "AI Mime",
  "tags": ["google-drive", "files", "upload"],
  "icon": "icons/ai-mime-icon.png",
  "package_url": "packages/upload-to-google-drive.zip",
  "sha256": "...",
  "size_bytes": 15177,
  "entrypoint": "skills/upload_to_google_drive/run.sh",
  "skill_name": "upload-to-google-drive",
  "requires_login": true,
  "side_effects": ["Uploads a local file to Google Drive."],
  "stops_before_payment": null,
  "safety_notes": [
    "Requires the user to already be logged in to the relevant service.",
    "Uploads a local file to Google Drive."
  ]
}
```

Use relative URLs for `icon` and `package_url` so the manifest works on GitHub
Pages, local static hosting, and forks.

## Package Contract

Each package zip contains a workflow directory's contents at the archive root:

```text
metadata.json
schema.json
optimized_plan.json
skills/<skill-name>/SKILL.md
skills/<skill-name>/run.sh
skills/<skill-name>/scripts/run.py
skills/<skill-name>/inputs/inputs.example.json
skills/<skill-name>/inputs/inputs.template.json
skills/<skill-name>/references/fallback_plan.md
```

Packages should not include runtime/generated state such as `agent/`, `runs/`,
`outputs/`, `.venv/`, cache folders, logs, screenshots, or local OS metadata.

## Local Preview

To preview the marketplace page locally:

```bash
cd /Users/prakharjain/code/ai_mime_marketplace/docs
python3 -m http.server 8897 --bind 127.0.0.1
```

Then open <http://127.0.0.1:8897/>.
