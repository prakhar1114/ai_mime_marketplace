#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
DOCS = ROOT / "docs"
PACKAGES = DOCS / "packages"
MANIFEST = DOCS / "manifest.json"
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "agent", "runs", "outputs", ".agent"}
SKIP_FILES = {".DS_Store", "manifest.jsonl", "step_cards.json", "plan_creation.json", "finalized_plan.json", ".env"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def should_package(path: Path, skill_dir: Path) -> bool:
    rel = path.relative_to(skill_dir)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if rel.name in SKIP_FILES:
        return False
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.is_file()


def package_skill(skill_dir: Path) -> Path:
    package_path = PACKAGES / f"{skill_dir.name}.zip"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(skill_dir.rglob("*")):
            if should_package(path, skill_dir):
                zf.write(path, path.relative_to(skill_dir).as_posix())
    return package_path


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from add_to_marketplace import parse_frontmatter, description_from_skill

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest.get("items") or []
    by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
    for stale in PACKAGES.glob("*.zip"):
        stale.unlink()
    for skill_dir in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        package = package_skill(skill_dir)
        item = by_id.get(skill_dir.name)
        if not item:
            continue
        
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            fields, _ = parse_frontmatter(skill_md)
            desc = description_from_skill(skill_dir)
            if fields.get("name"):
                item["name"] = fields["name"]
            if desc:
                item["description"] = desc

        item["entrypoint"] = "run.sh"
        item["package_url"] = f"packages/{package.name}"
        item["sha256"] = sha256(package)
        item["size_bytes"] = package.stat().st_size
        item["github_folder_path"] = f"skills/{skill_dir.name}"
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
