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
    "mcpServers",
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

    if "mcpServers" in manifest:
        validate_mcp_manifest(root, manifest["mcpServers"])

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


def validate_mcp_manifest(root: Path, manifest_value: object) -> None:
    if not isinstance(manifest_value, str):
        fail("mcpServers must be a string path")
    if manifest_value != "./.mcp.json":
        fail("mcpServers path must be ./.mcp.json")

    mcp_path = root / ".mcp.json"
    if not mcp_path.is_file():
        fail("mcpServers is configured but .mcp.json is missing")
    try:
        payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {mcp_path}: {exc}")
    if not isinstance(payload, dict):
        fail(".mcp.json root must be an object")
    if set(payload) != {"mcpServers"}:
        fail(".mcp.json must contain only mcpServers")

    servers = payload["mcpServers"]
    if not isinstance(servers, dict) or not servers:
        fail(".mcp.json mcpServers must be a non-empty object")
    for name, server in servers.items():
        if not isinstance(name, str) or not name:
            fail(".mcp.json server names must be non-empty strings")
        if not isinstance(server, dict):
            fail(f".mcp.json server {name!r} must be an object")
        command = server.get("command")
        if not isinstance(command, str) or not command:
            fail(f".mcp.json server {name!r} must define command")
        args = server.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            fail(f".mcp.json server {name!r} args must be a list of strings")
        env = server.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        ):
            fail(f".mcp.json server {name!r} env must be an object of strings")
        unsupported = sorted(set(server) - {"command", "args", "env"})
        if unsupported:
            fail(
                f".mcp.json server {name!r} has unsupported keys: "
                + ", ".join(unsupported)
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
