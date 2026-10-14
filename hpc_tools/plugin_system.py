from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from importlib import import_module, metadata
from typing import Any, Protocol

from hpc_tools import __version__
from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.capabilities import CapabilityLevel
from hpc_tools.config import ConfigError, Profile
from hpc_tools.operation_registry import (
    OPERATION_REGISTRY,
    OperationDescriptor,
    OperationRegistry,
    OperationSurface,
)


PLUGIN_ENTRY_POINT_GROUP = "hpc_tools.plugins"
PLUGIN_CONTRACT_VERSION = 1
BUILTIN_PLUGIN_FACTORIES = {
    "benchmark": "hpc_tools.plugins.benchmark_support:get_plugin",
    "cxx": "hpc_tools.plugins.cxx_support:get_plugin",
    "python": "hpc_tools.plugins.python_support:get_plugin",
    "r": "hpc_tools.plugins.r_support:get_plugin",
}


class HpcPlugin(Protocol):
    name: str
    description: str
    contract_version: int
    operations: tuple[OperationDescriptor, ...]

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
    plugin: Any
    contract_version: int | None
    operations: tuple[OperationDescriptor, ...]
    contract_error: str | None = None

    @property
    def available(self) -> bool:
        return self.contract_error is None


_REGISTRATION_ERRORS: dict[str, str] = {}


def load_plugins() -> list[LoadedPlugin]:
    loaded: dict[str, LoadedPlugin] = {}

    for name, target in BUILTIN_PLUGIN_FACTORIES.items():
        plugin = _load_factory_target(target)
        loaded[name] = _loaded_plugin(
            plugin,
            fallback_name=name,
            source="builtin",
            version=__version__,
            builtin=True,
        )

    for entry_point in _iter_plugin_entry_points():
        plugin = entry_point.load()
        if callable(plugin) and not hasattr(plugin, "register"):
            plugin = plugin()
        name = str(getattr(plugin, "name", entry_point.name))
        if name in loaded:
            continue
        distribution = getattr(entry_point, "dist", None)
        distribution_name = getattr(distribution, "name", "unknown")
        version = getattr(distribution, "version", "") or ""
        loaded[name] = _loaded_plugin(
            plugin,
            fallback_name=entry_point.name,
            source=f"entry-point:{distribution_name}",
            version=version,
            builtin=False,
        )

    result = [loaded[name] for name in sorted(loaded)]
    return _reject_external_conflicts(result)


def plugin_needs_profile(command: str, argv: list[str]) -> bool | None:
    for loaded in load_plugins():
        if loaded.name == command:
            if not loaded.available:
                return False
            return loaded.plugin.requires_profile(argv)
    return None


def register_plugin_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    profile: Profile | None,
) -> None:
    for loaded in load_plugins():
        if not loaded.available:
            continue
        before = set(_subparser_choices(subparsers))
        try:
            loaded.plugin.register(subparsers, profile)
            _validate_registered_bindings(loaded, subparsers, before)
        except Exception as error:
            _remove_added_parsers(subparsers, before)
            _REGISTRATION_ERRORS[loaded.name] = (
                f"registration does not match declared operations: {error}"
            )


def format_plugins(plugins: list[LoadedPlugin]) -> str:
    if not plugins:
        return "No plugins."

    rows = [
        [
            plugin.name,
            plugin.version,
            plugin.source,
            _contract_label(plugin),
            plugin.description,
        ]
        for plugin in plugins
    ]
    headers = ["NAME", "VERSION", "SOURCE", "CONTRACT", "DESCRIPTION"]
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


def builtin_operations(*operation_ids: str) -> tuple[OperationDescriptor, ...]:
    """Return canonical descriptors for a bundled plugin contract."""
    return tuple(OPERATION_REGISTRY.require(operation_id) for operation_id in operation_ids)


def authorize_plugin_command(
    args: argparse.Namespace,
    profile: Profile | None,
) -> None:
    """Authorize one parsed plugin leaf before its handler can run."""
    command = getattr(args, "command", None)
    operation_id = getattr(args, "operation_id", None)
    if not isinstance(command, str) or not isinstance(operation_id, str):
        return
    loaded = next((item for item in load_plugins() if item.name == command), None)
    if loaded is None:
        return
    if not loaded.available:
        raise ConfigError(
            f"plugin '{loaded.name}' is unavailable: {loaded.contract_error}"
        )
    descriptor = next(
        (item for item in loaded.operations if item.id == operation_id),
        None,
    )
    if descriptor is None:
        raise ConfigError(
            f"plugin '{loaded.name}' command has no declared operation metadata: "
            f"{operation_id}"
        )
    if profile is None:
        if _is_profile_free(descriptor):
            return
        raise ConfigError(
            f"plugin operation '{operation_id}' requires a configured profile"
        )
    canonical = OPERATION_REGISTRY.get(operation_id)
    registry = (
        OPERATION_REGISTRY
        if canonical == descriptor
        else OperationRegistry(loaded.operations)
    )
    require_authorized(
        operation_id,
        profile,
        namespace_arguments(args),
        surface=OperationSurface.CLI,
        registry=registry,
    )


def _loaded_plugin(
    plugin: Any,
    *,
    fallback_name: str,
    source: str,
    version: str,
    builtin: bool,
) -> LoadedPlugin:
    name = str(getattr(plugin, "name", fallback_name))
    description = str(getattr(plugin, "description", ""))
    contract_version = getattr(plugin, "contract_version", None)
    raw_operations = getattr(plugin, "operations", None)
    error = _validate_contract(
        plugin,
        name=name,
        contract_version=contract_version,
        raw_operations=raw_operations,
        builtin=builtin,
    )
    operations = (
        raw_operations
        if isinstance(raw_operations, tuple)
        and all(isinstance(item, OperationDescriptor) for item in raw_operations)
        else ()
    )
    error = _REGISTRATION_ERRORS.get(name, error)
    return LoadedPlugin(
        name=name,
        description=description,
        source=source,
        version=version,
        plugin=plugin,
        contract_version=(
            contract_version
            if isinstance(contract_version, int) and not isinstance(contract_version, bool)
            else None
        ),
        operations=operations,
        contract_error=error,
    )


def _validate_contract(
    plugin: Any,
    *,
    name: str,
    contract_version: object,
    raw_operations: object,
    builtin: bool,
) -> str | None:
    if not name or name != name.strip() or any(character.isspace() for character in name):
        return "plugin name must be one non-empty command token"
    if contract_version != PLUGIN_CONTRACT_VERSION or isinstance(contract_version, bool):
        return (
            f"unsupported or missing contract_version; expected "
            f"{PLUGIN_CONTRACT_VERSION}"
        )
    if not callable(getattr(plugin, "register", None)):
        return "missing callable register(subparsers, profile)"
    if not callable(getattr(plugin, "requires_profile", None)):
        return "missing callable requires_profile(argv)"
    if not isinstance(raw_operations, tuple) or not raw_operations:
        return "operations must be a non-empty tuple of OperationDescriptor values"
    if not all(isinstance(item, OperationDescriptor) for item in raw_operations):
        return "operations must contain only OperationDescriptor values"
    operation_ids: set[str] = set()
    bindings: set[str] = set()
    for operation in raw_operations:
        if operation.id in operation_ids:
            return f"duplicate declared operation id: {operation.id}"
        operation_ids.add(operation.id)
        if not operation.cli or operation.mcp or operation.resources:
            return f"operation '{operation.id}' must declare CLI bindings only"
        if not builtin and operation.resolver != "default":
            return f"operation '{operation.id}' uses an unsupported custom resolver"
        for binding in operation.cli:
            if binding.split(maxsplit=1)[0] != name:
                return (
                    f"operation '{operation.id}' binding '{binding}' must start "
                    f"with plugin name '{name}'"
                )
            if binding in bindings:
                return f"duplicate declared CLI binding: {binding}"
            bindings.add(binding)
        canonical = OPERATION_REGISTRY.get(operation.id)
        if builtin and canonical != operation:
            return f"bundled operation '{operation.id}' is not the canonical descriptor"
        if not builtin and canonical is not None:
            return f"operation id '{operation.id}' collides with a core operation"
    return None


def _reject_external_conflicts(plugins: list[LoadedPlugin]) -> list[LoadedPlugin]:
    operation_owners: dict[str, str] = {}
    binding_owners: dict[str, str] = {}
    result: list[LoadedPlugin] = []
    for plugin in plugins:
        error = plugin.contract_error
        if error is None and plugin.source != "builtin":
            for operation in plugin.operations:
                owner = operation_owners.get(operation.id)
                if owner is not None:
                    error = f"operation id '{operation.id}' is already declared by '{owner}'"
                    break
                for binding in operation.cli:
                    owner = binding_owners.get(binding)
                    if owner is not None:
                        error = f"CLI binding '{binding}' is already declared by '{owner}'"
                        break
                if error is not None:
                    break
        updated = replace(plugin, contract_error=error)
        result.append(updated)
        if updated.available:
            for operation in updated.operations:
                operation_owners[operation.id] = updated.name
                for binding in operation.cli:
                    binding_owners[binding] = updated.name
    return result


def _contract_label(plugin: LoadedPlugin) -> str:
    if plugin.available:
        return f"v{plugin.contract_version}"
    return "rejected"


def _is_profile_free(operation: OperationDescriptor) -> bool:
    return (
        operation.minimum_level is CapabilityLevel.PROFILE_CONTEXT
        and not operation.scopes
        and not operation.profile_required
        and not operation.operator_only
        and not operation.site_features
        and not operation.path_bindings
        and set(operation.effects) <= {"local-read", "local-execute"}
    )


def _subparser_choices(subparsers: Any) -> dict[str, argparse.ArgumentParser]:
    actual = getattr(subparsers, "_subparsers", subparsers)
    return actual.choices


def _validate_registered_bindings(
    plugin: LoadedPlugin,
    subparsers: Any,
    before: set[str],
) -> None:
    choices = _subparser_choices(subparsers)
    added = set(choices) - before
    if added != {plugin.name}:
        raise ConfigError(
            f"expected top-level command '{plugin.name}', registered: "
            + (", ".join(sorted(added)) or "none")
        )
    actual = _leaf_operations(choices[plugin.name], (plugin.name,))
    declared = {
        binding: operation.id
        for operation in plugin.operations
        for binding in operation.cli
    }
    if actual != declared:
        missing = sorted(set(declared) - set(actual))
        undeclared = sorted(set(actual) - set(declared))
        mismatched = sorted(
            binding
            for binding in set(actual) & set(declared)
            if actual[binding] != declared[binding]
        )
        details = []
        if missing:
            details.append("missing bindings: " + ", ".join(missing))
        if undeclared:
            details.append("undeclared bindings: " + ", ".join(undeclared))
        if mismatched:
            details.append("operation-id mismatches: " + ", ".join(mismatched))
        raise ConfigError("; ".join(details) or "operation bindings do not match")


def _leaf_operations(
    parser: argparse.ArgumentParser,
    prefix: tuple[str, ...],
) -> dict[str, str]:
    subparser_actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if subparser_actions:
        result: dict[str, str] = {}
        for action in subparser_actions:
            for name, child in action.choices.items():
                result.update(_leaf_operations(child, (*prefix, name)))
        return result
    operation_id = parser._defaults.get("operation_id")
    handler = parser._defaults.get("handler")
    if not isinstance(operation_id, str) or not callable(handler):
        raise ConfigError(
            f"leaf command '{' '.join(prefix)}' must declare operation_id and handler"
        )
    return {" ".join(prefix): operation_id}


def _remove_added_parsers(subparsers: Any, before: set[str]) -> None:
    actual = getattr(subparsers, "_subparsers", subparsers)
    added = set(actual.choices) - before
    for name in added:
        actual.choices.pop(name, None)
    if hasattr(actual, "_choices_actions"):
        actual._choices_actions[:] = [
            action for action in actual._choices_actions if action.dest not in added
        ]
    for group in getattr(subparsers, "groups", []):
        group.commands[:] = [
            command for command in group.commands if command[0] not in added
        ]


def _iter_plugin_entry_points() -> list[metadata.EntryPoint]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=PLUGIN_ENTRY_POINT_GROUP))
    return list(entry_points.get(PLUGIN_ENTRY_POINT_GROUP, []))


def _format_row(row: list[str], widths: list[int]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(row, widths))
