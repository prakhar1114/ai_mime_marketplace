#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
DOCS = ROOT / "docs"
PACKAGES = DOCS / "packages"
MANIFEST = DOCS / "manifest.json"
DEFAULT_ICON = "icons/ai-mime-icon.png"

REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "run.sh",
    "scripts/run.py",
    "inputs/inputs.example.json",
    "inputs/inputs.template.json",
    "references/fallback_plan.md",
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".agent",
    "agent",
    "runs",
    "outputs",
    "screenshots",
}
SKIP_FILES = {
    ".DS_Store",
    "manifest.jsonl",
    "step_cards.json",
    "plan_creation.json",
    "finalized_plan.json",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp"}
WORKFLOW_SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def slugify(value: str, fallback: str = "workflow") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frontmatter(skill_md: Path) -> tuple[dict[str, str], str]:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text

    fields: dict[str, str] = {}
    lines = match.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line[:1].isspace() or ":" not in line:
            i += 1
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip().strip('"\'')
        if value in {">", ">-", "|", "|-"}:
            block: list[str] = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1].isspace()):
                block.append(lines[i].strip())
                i += 1
            fields[key] = " ".join(part for part in block if part).strip()
            continue
        fields[key] = value
        i += 1
    return fields, text[match.end():]


def frontmatter_text(fields: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key, value in fields.items():
        clean = str(value or "").replace("\n", " ").strip()
        lines.append(f"{key}: {clean}")
    lines.append("---")
    lines.append("")
    lines.append(body.lstrip())
    return "\n".join(lines)


def description_from_skill(skill_dir: Path) -> str:
    fields, body = parse_frontmatter(skill_dir / "SKILL.md")
    description = fields.get("description", "").strip()
    if description:
        return re.sub(r"\s+", " ", description)

    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if lines:
                break
            continue
        if line.startswith("```") or line.startswith("|"):
            continue
        lines.append(line.strip("*"))
        if len(" ".join(lines)) > 220:
            break
    return re.sub(r"\s+", " ", " ".join(lines)).strip() or "Installable AI Mime workflow."


def is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "SKILL.md").is_file() and (path / "run.sh").is_file()


def required_skill_complete(path: Path) -> bool:
    return all((path / rel).is_file() for rel in REQUIRED_SKILL_FILES)


def runnable_skill_dirs(workflow_dir: Path) -> list[Path]:
    skills_root = workflow_dir / "skills"
    if not skills_root.is_dir():
        return []
    return sorted(p for p in skills_root.iterdir() if is_skill_dir(p))


def choose_skill_dir(source: Path, explicit_skill: str | None) -> Path:
    if not (source / "SKILL.md").is_file():
        raise SystemExit(
            f"Invalid source: {source}\n"
            "Only valid skill folders containing SKILL.md in their root are allowed."
        )
    if not (source / "run.sh").is_file():
        raise SystemExit(
            f"Invalid skill folder: {source}\n"
            "Skill folder must contain run.sh."
        )
    return source


def should_skip(path: Path, rel: Path) -> bool:
    if path.is_symlink():
        return True
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if rel.name in SKIP_FILES:
        return True
    if rel.name == ".env" or rel.name.startswith("."):
        return True
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def copy_tree_clean(src: Path, dst: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if should_skip(path, rel):
            removed.append(rel.as_posix())
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return sorted(set(removed))


def ensure_skill_frontmatter(skill_dir: Path, *, name: str, description: str) -> None:
    skill_md = skill_dir / "SKILL.md"
    fields, body = parse_frontmatter(skill_md)
    changed = False
    if not fields.get("name"):
        fields["name"] = name
        changed = True
    if not fields.get("description"):
        fields["description"] = description
        changed = True
    if changed:
        ordered = {"name": fields["name"], "description": fields["description"]}
        for key, value in fields.items():
            if key not in ordered:
                ordered[key] = value
        skill_md.write_text(frontmatter_text(ordered, body), encoding="utf-8")


def chmod_run_sh(skill_dir: Path) -> None:
    run_sh = skill_dir / "run.sh"
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def validate_skill(skill_dir: Path) -> None:
    missing = [rel for rel in REQUIRED_SKILL_FILES if not (skill_dir / rel).is_file()]
    if missing:
        raise SystemExit("Skill package missing required file(s): " + ", ".join(missing))
    fields, _ = parse_frontmatter(skill_dir / "SKILL.md")
    if not fields.get("name") or not fields.get("description"):
        raise SystemExit("SKILL.md frontmatter must include non-empty name and description")
    if not os.access(skill_dir / "run.sh", os.X_OK):
        raise SystemExit("run.sh is not executable")


def package_skill(skill_dir: Path) -> Path:
    PACKAGES.mkdir(parents=True, exist_ok=True)
    package = PACKAGES / f"{skill_dir.name}.zip"
    if package.exists():
        package.unlink()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(skill_dir.rglob("*")):
            rel = path.relative_to(skill_dir)
            if path.is_file() and not should_skip(path, rel):
                zf.write(path, rel.as_posix())
    return package


def build_safety_notes(requires_login: bool, side_effects: list[str], stops_before_payment: bool | None) -> list[str]:
    notes: list[str] = []
    if requires_login:
        notes.append("Requires the user to already be logged in to the relevant service.")
    notes.extend(side_effects)
    if stops_before_payment is True:
        notes.append("Stops before payment or final purchase confirmation.")
    elif stops_before_payment is False:
        notes.append("May complete the requested action without an additional payment checkpoint.")
    return notes


def load_manifest() -> dict[str, Any]:
    if MANIFEST.exists():
        manifest = read_json(MANIFEST)
    else:
        manifest = {}
    manifest.setdefault("version", 1)
    manifest.setdefault("name", "AI Mime Skills Marketplace")
    manifest.setdefault("homepage", "https://aimime.cc/")
    manifest.setdefault("items", [])
    if not isinstance(manifest["items"], list):
        raise SystemExit("manifest.json has invalid items field")
    return manifest


def upsert_manifest_item(item: dict[str, Any], *, replace: bool) -> None:
    manifest = load_manifest()
    items = [entry for entry in manifest["items"] if isinstance(entry, dict)]
    existing_index = next((i for i, entry in enumerate(items) if entry.get("id") == item["id"]), None)
    if existing_index is not None and not replace:
        raise SystemExit(f"Manifest already has item {item['id']!r}. Use --replace to update it.")
    if existing_index is None:
        items.append(item)
    else:
        items[existing_index] = item
    manifest["items"] = sorted(items, key=lambda entry: str(entry.get("name") or entry.get("id") or "").lower())
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_json(MANIFEST, manifest)


def migrate(args: argparse.Namespace) -> None:
    source = Path(args.path).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise SystemExit(f"Source path is not a directory: {source}")

    source_skill = choose_skill_dir(source, args.skill)
    source_fields, _ = parse_frontmatter(source_skill / "SKILL.md")
    default_name = source_fields.get("name") or source_skill.name
    display_name = (args.name or str(default_name)).strip()
    description = (args.description or description_from_skill(source_skill)).strip()
    skill_id = args.id or slugify(display_name, fallback=source_skill.name)
    skill_id = slugify(skill_id, fallback=source_skill.name)

    skill_dst = SKILLS / skill_id
    if args.dry_run:
        print(f"source_skill={source_skill}")
        print(f"skill_id={skill_id}")
        print(f"display_name={display_name}")
        print(f"description={description}")
        return

    if skill_dst.exists():
        if not args.replace:
            raise SystemExit(f"Destination already exists: {skill_dst}. Use --replace to update it.")
        shutil.rmtree(skill_dst)
    skill_dst.mkdir(parents=True, exist_ok=True)

    removed = copy_tree_clean(source_skill, skill_dst)

    ensure_skill_frontmatter(skill_dst, name=source_fields.get("name") or skill_dst.name, description=description)
    chmod_run_sh(skill_dst)
    validate_skill(skill_dst)

    package = package_skill(skill_dst)
    side_effects = [s.strip() for s in (args.side_effect or []) if s.strip()]
    stops_before_payment = None if args.stops_before_payment == "unknown" else args.stops_before_payment == "yes"
    tags = [slugify(tag, fallback="tag") for tag in (args.tag or [])]
    item = {
        "id": skill_id,
        "name": display_name,
        "description": description,
        "type": "skill",
        "version": args.version,
        "author": args.author,
        "tags": tags,
        "icon": DEFAULT_ICON,
        "package_url": f"packages/{package.name}",
        "sha256": sha256(package),
        "size_bytes": package.stat().st_size,
        "github_folder_path": f"skills/{skill_id}",
        "entrypoint": "run.sh",
        "requires_login": bool(args.requires_login),
        "side_effects": side_effects,
        "stops_before_payment": stops_before_payment,
        "safety_notes": build_safety_notes(bool(args.requires_login), side_effects, stops_before_payment),
    }
    upsert_manifest_item(item, replace=args.replace)
    print(f"Added marketplace item: {skill_id}")
    print(f"Skill directory: {skill_dst}")
    print(f"Package: {package}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add an AI Mime workflow or bare skill directory to the static marketplace.",
    )
    parser.add_argument("path", help="Path to a workflow directory or bare skill directory")
    parser.add_argument("--id", help="Marketplace/workflow id slug. Defaults to a slug from the name.")
    parser.add_argument("--skill", help="Skill folder name under workflow/skills when a workflow has multiple skills")
    parser.add_argument("--name", help="Display name. Defaults to workflow metadata or SKILL.md frontmatter.")
    parser.add_argument("--description", help="Listing description. Defaults to metadata/SKILL.md/first markdown paragraph.")
    parser.add_argument("--version", default="0.1.0", help="Marketplace item version")
    parser.add_argument("--author", default="AI Mime", help="Marketplace item author")
    parser.add_argument("--tag", action="append", default=[], help="Listing tag. Repeat for multiple tags.")
    parser.add_argument("--requires-login", action="store_true", help="Mark the workflow as requiring a pre-existing logged-in session")
    parser.add_argument("--side-effect", action="append", default=[], help="Side effect/safety note. Repeat for multiple notes.")
    parser.add_argument(
        "--stops-before-payment",
        choices=("yes", "no", "unknown"),
        default="unknown",
        help="Whether the workflow explicitly stops before payment/final purchase confirmation",
    )
    parser.add_argument("--empty-plan", action="store_true", help="Write optimized_plan.json as {} in the marketplace copy")
    parser.add_argument("--replace", action="store_true", help="Replace an existing marketplace item/workflow with the same id")
    parser.add_argument("--dry-run", action="store_true", help="Show detected values without copying or writing")
    return parser.parse_args()


if __name__ == "__main__":
    migrate(parse_args())
