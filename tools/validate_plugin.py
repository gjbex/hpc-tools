#!/usr/bin/env python3
"""Validate the Codex plugin manifest for this repository."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP_LEVEL = {
    "name": str,
    "version": str,
    "description": str,
    "author": dict,
    "skills": str,
    "interface": dict,
}

REQUIRED_INTERFACE = {
    "displayName": str,
    "shortDescription": str,
    "longDescription": str,
    "developerName": str,
    "category": str,
    "capabilities": list,
    "defaultPrompt": list,
    "brandColor": str,
}

ALLOWED_TOP_LEVEL = {
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "skills",
    "interface",
}


def fail(message: str) -> None:
    print(f"validate_plugin.py: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_type(mapping: dict[str, object], key: str, expected_type: type) -> None:
    if key not in mapping:
        fail(f"missing required key: {key}")
    if not isinstance(mapping[key], expected_type):
        fail(f"{key} must be {expected_type.__name__}")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    root = root.resolve()
    manifest_path = root / ".codex-plugin" / "plugin.json"
    if not manifest_path.is_file():
        fail(f"missing {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {manifest_path}: {exc}")

    if not isinstance(manifest, dict):
        fail("plugin manifest root must be an object")

    unsupported = sorted(set(manifest) - ALLOWED_TOP_LEVEL)
    if unsupported:
        fail(f"unsupported top-level keys: {', '.join(unsupported)}")

    for key, expected_type in REQUIRED_TOP_LEVEL.items():
        require_type(manifest, key, expected_type)

    if manifest["name"] != root.name:
        fail(f"manifest name {manifest['name']!r} must match repository directory {root.name!r}")

    author = manifest["author"]
    if not author.get("name"):
        fail("author.name is required")

    skills = manifest["skills"]
    if not skills.startswith("./"):
        fail("skills path must be repository-relative and start with ./")
    skills_path = (root / skills).resolve()
    if not skills_path.is_dir():
        fail(f"skills path does not exist: {skills}")
    if root not in skills_path.parents and skills_path != root:
        fail(f"skills path escapes repository: {skills}")

    interface = manifest["interface"]
    for key, expected_type in REQUIRED_INTERFACE.items():
        require_type(interface, key, expected_type)

    if not interface["capabilities"]:
        fail("interface.capabilities must not be empty")
    if not interface["defaultPrompt"]:
        fail("interface.defaultPrompt must not be empty")
    if not all(isinstance(item, str) and item for item in interface["defaultPrompt"]):
        fail("interface.defaultPrompt entries must be non-empty strings")

    keywords = manifest.get("keywords", [])
    if keywords and not all(isinstance(item, str) and item for item in keywords):
        fail("keywords entries must be non-empty strings")

    print(f"validated {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
