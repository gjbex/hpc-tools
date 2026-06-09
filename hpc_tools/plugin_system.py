from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib import import_module, metadata
from typing import Protocol

from hpc_tools import __version__
from hpc_tools.config import Profile


PLUGIN_ENTRY_POINT_GROUP = "hpc_tools.plugins"
BUILTIN_PLUGIN_FACTORIES = {
    "r": "hpc_tools.plugins.r_support:get_plugin",
}


class HpcPlugin(Protocol):
    name: str
    description: str

    def register(self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser], profile: Profile | None) -> None:
        ...

    def requires_profile(self, argv: list[str]) -> bool:
        ...


@dataclass(frozen=True)
class LoadedPlugin:
    name: str
    description: str
    source: str
    version: str
    plugin: HpcPlugin


def load_plugins() -> list[LoadedPlugin]:
    loaded: dict[str, LoadedPlugin] = {}

    for name, target in BUILTIN_PLUGIN_FACTORIES.items():
        plugin = _load_factory_target(target)
        loaded[name] = LoadedPlugin(
            name=plugin.name,
            description=plugin.description,
            source="builtin",
            version=__version__,
            plugin=plugin,
        )

    for entry_point in _iter_plugin_entry_points():
        plugin = entry_point.load()
        if callable(plugin) and not hasattr(plugin, "register"):
            plugin = plugin()
        name = getattr(plugin, "name", entry_point.name)
        if name in loaded:
            continue
        version = getattr(entry_point.dist, "version", "") or ""
        loaded[name] = LoadedPlugin(
            name=name,
            description=str(getattr(plugin, "description", "")),
            source=f"entry-point:{entry_point.dist.name}",
            version=version,
            plugin=plugin,
        )

    return [loaded[name] for name in sorted(loaded)]


def plugin_needs_profile(command: str, argv: list[str]) -> bool | None:
    for loaded in load_plugins():
        if loaded.name == command:
            return loaded.plugin.requires_profile(argv)
    return None


def register_plugin_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    profile: Profile | None,
) -> None:
    for loaded in load_plugins():
        loaded.plugin.register(subparsers, profile)


def format_plugins(plugins: list[LoadedPlugin]) -> str:
    if not plugins:
        return "No plugins."

    rows = [
        [plugin.name, plugin.version, plugin.source, plugin.description]
        for plugin in plugins
    ]
    headers = ["NAME", "VERSION", "SOURCE", "DESCRIPTION"]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [_format_row(headers, widths), _format_row(["-" * width for width in widths], widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def get_plugin(name: str) -> LoadedPlugin | None:
    for plugin in load_plugins():
        if plugin.name == name:
            return plugin
    return None


def _load_factory_target(target: str) -> HpcPlugin:
    module_name, _, attr_name = target.partition(":")
    if not module_name or not attr_name:
        raise ValueError(f"invalid plugin factory target: {target}")
    module = import_module(module_name)
    factory = getattr(module, attr_name)
    plugin = factory()
    return plugin


def _iter_plugin_entry_points() -> list[metadata.EntryPoint]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=PLUGIN_ENTRY_POINT_GROUP))
    return list(entry_points.get(PLUGIN_ENTRY_POINT_GROUP, []))


def _format_row(row: list[str], widths: list[int]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(row, widths))
