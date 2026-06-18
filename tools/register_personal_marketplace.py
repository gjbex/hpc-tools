#!/usr/bin/env python3
"""Register this plugin checkout in the default personal Codex marketplace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_MARKETPLACE_PATH = Path.home() / ".agents" / "plugins" / "marketplace.json"
DEFAULT_MARKETPLACE_NAME = "personal"
DEFAULT_CATEGORY = "Productivity"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def read_plugin_name(plugin_root: Path) -> str:
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    payload = load_json(manifest_path)
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{manifest_path} must contain a non-empty string 'name'")
    return name


def default_marketplace() -> dict[str, Any]:
    return {
        "name": DEFAULT_MARKETPLACE_NAME,
        "interface": {
            "displayName": "Personal",
        },
        "plugins": [],
    }


def marketplace_entry(plugin_name: str, plugin_root: Path) -> dict[str, Any]:
    return {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": str(plugin_root),
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": DEFAULT_CATEGORY,
    }


def register_plugin(plugin_root: Path, marketplace_path: Path) -> bool:
    plugin_name = read_plugin_name(plugin_root)
    payload = load_json(marketplace_path) if marketplace_path.exists() else default_marketplace()

    marketplace_name = payload.get("name")
    if not isinstance(marketplace_name, str) or not marketplace_name:
        raise ValueError(f"{marketplace_path} must contain a non-empty string 'name'")

    plugins = payload.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise ValueError(f"{marketplace_path} field 'plugins' must be an array")

    entry = marketplace_entry(plugin_name, plugin_root)
    changed = False
    for index, existing in enumerate(plugins):
        if isinstance(existing, dict) and existing.get("name") == plugin_name:
            if existing != entry:
                plugins[index] = entry
                changed = True
            break
    else:
        plugins.append(entry)
        changed = True

    if changed:
        write_json(marketplace_path, payload)
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update the hpc-tools entry in the default personal "
            "Codex marketplace."
        )
    )
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default=".",
        help="Path to the hpc-tools plugin checkout, defaults to the current directory.",
    )
    parser.add_argument(
        "--marketplace-path",
        default=str(DEFAULT_MARKETPLACE_PATH),
        help="Path to marketplace.json, defaults to ~/.agents/plugins/marketplace.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin_root = Path(args.plugin_root).expanduser().resolve()
    marketplace_path = Path(args.marketplace_path).expanduser().resolve()
    changed = register_plugin(plugin_root, marketplace_path)
    status = "updated" if changed else "already registered"
    print(f"{status}: {read_plugin_name(plugin_root)} in {marketplace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
