#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
DOCS = ROOT / "docs"
PACKAGES = DOCS / "packages"
MANIFEST = DOCS / "manifest.json"
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "agent", "runs", "outputs", ".agent"}
SKIP_FILES = {".DS_Store", "manifest.jsonl", "step_cards.json", "plan_creation.json", "finalized_plan.json"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def should_package(path: Path, workflow_dir: Path) -> bool:
    rel = path.relative_to(workflow_dir)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if rel.name in SKIP_FILES:
        return False
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.is_file()


def package_workflow(workflow_dir: Path) -> Path:
    package_path = PACKAGES / f"{workflow_dir.name}.zip"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(workflow_dir.rglob("*")):
            if should_package(path, workflow_dir):
                zf.write(path, path.relative_to(workflow_dir).as_posix())
    return package_path


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest.get("items") or []
    by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
    for stale in PACKAGES.glob("*.zip"):
        stale.unlink()
    for workflow_dir in sorted(p for p in WORKFLOWS.iterdir() if p.is_dir()):
        package = package_workflow(workflow_dir)
        item = by_id.get(workflow_dir.name)
        if not item:
            continue
        item["package_url"] = f"packages/{package.name}"
        item["sha256"] = sha256(package)
        item["size_bytes"] = package.stat().st_size
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
