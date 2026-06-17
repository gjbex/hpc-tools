#!/usr/bin/env python3
"""Validate bundled Codex skill files without depending on a local Codex tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path


FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*(?P<value>\S+)\s*$", re.MULTILINE)
DESCRIPTION_RE = re.compile(r"^description:\s*(?P<value>.+)\s*$", re.MULTILINE)


def fail(message: str) -> None:
    print(f"validate_skills.py: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_skill(skill_file: Path, skills_dir: Path) -> None:
    text = skill_file.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        fail(f"{skill_file.relative_to(skills_dir.parent)} is missing YAML frontmatter")

    frontmatter = match.group("body")
    name_match = NAME_RE.search(frontmatter)
    description_match = DESCRIPTION_RE.search(frontmatter)
    if not name_match:
        fail(f"{skill_file.relative_to(skills_dir.parent)} is missing frontmatter name")
    if not description_match:
        fail(f"{skill_file.relative_to(skills_dir.parent)} is missing frontmatter description")

    expected_name = skill_file.parent.name
    actual_name = name_match.group("value")
    if actual_name != expected_name:
        fail(
            f"{skill_file.relative_to(skills_dir.parent)} name {actual_name!r} "
            f"does not match directory {expected_name!r}"
        )

    description = description_match.group("value").strip()
    if len(description) < 40:
        fail(f"{skill_file.relative_to(skills_dir.parent)} description is too short")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    root = root.resolve()
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        fail(f"missing skills directory: {skills_dir}")

    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        fail("no top-level skill SKILL.md files found")

    shared_files = sorted((skills_dir / "_shared").glob("*.md"))
    if not shared_files:
        fail("skills/_shared must contain shared reference Markdown files")

    for skill_file in skill_files:
        if skill_file.parent.name.startswith("_"):
            continue
        validate_skill(skill_file, skills_dir)

    print(f"validated {len(skill_files)} skills and {len(shared_files)} shared references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
