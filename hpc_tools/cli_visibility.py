from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from hpc_tools import plugin_system
from hpc_tools.capabilities import (
    AuthorizationContext,
    AuthorizationDecision,
    CapabilityDenial,
    CapabilityRequirement,
    DenialCode,
    evaluate_capability,
)
from hpc_tools.config import Profile
from hpc_tools.operation_registry import (
    OPERATION_REGISTRY,
    OperationDescriptor,
    OperationRegistry,
    OperationSurface,
    RequestContext,
)


@dataclass(frozen=True)
class CommandVisibility:
    allowed: bool
    reasons: tuple[str, ...] = ()
    note: str | None = None


def apply_cli_visibility(
    parser: argparse.ArgumentParser,
    profile: Profile | None,
    *,
    requested_level: str | None = None,
    show_disallowed: bool = False,
) -> None:
    """Filter one parser copy used for help/completion discovery.

    Execution must use an unfiltered parser and authorize the parsed operation.
    """
    descriptors = _operation_descriptors()
    _filter_parser(
        parser,
        profile,
        requested_level=requested_level,
        show_disallowed=show_disallowed,
        descriptors=descriptors,
    )
    _synchronize_grouped_help(parser)


def _filter_parser(
    parser: argparse.ArgumentParser,
    profile: Profile | None,
    *,
    requested_level: str | None,
    show_disallowed: bool,
    descriptors: dict[str, OperationDescriptor],
) -> CommandVisibility:
    subparser_actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparser_actions:
        result = _leaf_visibility(
            parser,
            profile,
            requested_level=requested_level,
            descriptors=descriptors,
        )
        _annotate_leaf(parser, result, show_disallowed=show_disallowed)
        return result

    child_results: list[CommandVisibility] = []
    for action in subparser_actions:
        for name, child in list(action.choices.items()):
            result = _filter_parser(
                child,
                profile,
                requested_level=requested_level,
                show_disallowed=show_disallowed,
                descriptors=descriptors,
            )
            child_results.append(result)
            if not result.allowed and not show_disallowed:
                _remove_choice(action, name)
                continue
            annotation = _annotation(result, show_disallowed=show_disallowed)
            if annotation:
                _append_choice_help(action, name, annotation)

    allowed = any(result.allowed for result in child_results)
    reasons = _unique(
        reason
        for result in child_results
        if not result.allowed
        for reason in result.reasons
    )
    return CommandVisibility(allowed=allowed, reasons=reasons)


def _leaf_visibility(
    parser: argparse.ArgumentParser,
    profile: Profile | None,
    *,
    requested_level: str | None,
    descriptors: dict[str, OperationDescriptor],
) -> CommandVisibility:
    operation_id = parser.get_default("operation_id")
    if not isinstance(operation_id, str):
        return CommandVisibility(False, ("operation metadata is unavailable",))
    descriptor = descriptors.get(operation_id)
    if descriptor is None:
        return CommandVisibility(False, ("operation metadata is unavailable",))

    arguments = _parser_defaults(parser)
    if profile is None:
        if plugin_system.is_profile_free_operation(descriptor):
            return CommandVisibility(True)
        if operation_id == "probe.write" and arguments.get("output", "-") == "-":
            return CommandVisibility(
                True,
                note="allowed form: write the hardware probe to standard output only",
            )
        return CommandVisibility(False, ("requires a configured profile",))

    if operation_id == "job.submit":
        regular = _evaluate(
            descriptor,
            profile,
            requested_level=requested_level,
            arguments={**arguments, "test_only": False},
        )
        test_only = _evaluate(
            descriptor,
            profile,
            requested_level=requested_level,
            arguments={**arguments, "test_only": True},
        )
        if regular.allowed:
            note = None
            if not test_only.allowed:
                note = "--test-only is unavailable: " + _decision_reason(test_only)
            return CommandVisibility(True, note=note)
        if test_only.allowed:
            return CommandVisibility(
                True,
                note=(
                    "allowed form: submit JOBSCRIPT --test-only; actual submission is "
                    "unavailable: " + _decision_reason(regular)
                ),
            )
        return CommandVisibility(
            False,
            _unique((*_decision_reasons(regular), *_decision_reasons(test_only))),
        )

    if operation_id == "probe.write":
        stdout = _evaluate(
            descriptor,
            profile,
            requested_level=requested_level,
            arguments={**arguments, "output": "-"},
        )
        file_write = _evaluate(
            descriptor,
            profile,
            requested_level=requested_level,
            arguments={**arguments, "output": "probe.slurm"},
        )
        if stdout.allowed and not file_write.allowed:
            return CommandVisibility(
                True,
                note=(
                    "allowed form: output '-' only; local file writes are unavailable: "
                    + _decision_reason(file_write)
                ),
            )

    decision = _evaluate(
        descriptor,
        profile,
        requested_level=requested_level,
        arguments=arguments,
    )
    return CommandVisibility(
        decision.allowed,
        () if decision.allowed else _decision_reasons(decision),
    )


def _evaluate(
    descriptor: OperationDescriptor,
    profile: Profile,
    *,
    requested_level: str | None,
    arguments: dict[str, Any],
) -> AuthorizationDecision:
    arguments = dict(arguments)
    for binding in descriptor.path_bindings:
        grants = getattr(profile.capabilities.remote_roots, binding.grant)
        if binding.argument and grants:
            arguments[binding.argument] = grants[0]

    registry = (
        OPERATION_REGISTRY
        if OPERATION_REGISTRY.get(descriptor.id) == descriptor
        else OperationRegistry((descriptor,))
    )
    resolved = registry.resolve(
        RequestContext(
            operation_id=descriptor.id,
            surface=OperationSurface.CLI,
            arguments=arguments,
            profile=profile,
        )
    )
    context = AuthorizationContext.from_profile(
        profile,
        requested_level=requested_level,
    )
    requirement = _with_display_paths(resolved.requirement, context)
    decisions = (
        evaluate_capability(requirement, context),
        *(
            evaluate_capability(_with_display_paths(item, context), context)
            for item in resolved.components
        ),
    )
    denials = tuple(denial for decision in decisions for denial in decision.denials)
    return AuthorizationDecision(
        operation_id=descriptor.id,
        profile_name=profile.name,
        denials=denials,
    )


def _with_display_paths(
    requirement: CapabilityRequirement,
    context: AuthorizationContext,
) -> CapabilityRequirement:
    """Use an available representative root when help has no concrete path yet."""
    paths = tuple(
        replace(path, path=getattr(context.policy.remote_roots, path.grant)[0])
        if getattr(context.policy.remote_roots, path.grant)
        else path
        for path in requirement.paths
    )
    return replace(requirement, paths=paths)


def _operation_descriptors() -> dict[str, OperationDescriptor]:
    descriptors = {item.id: item for item in OPERATION_REGISTRY.operations}
    for loaded in plugin_system.load_plugins():
        if loaded.available:
            for operation in loaded.operations:
                descriptors.setdefault(operation.id, operation)
    return descriptors


def _parser_defaults(parser: argparse.ArgumentParser) -> dict[str, Any]:
    values = {
        action.dest: action.default
        for action in parser._actions
        if action.dest != argparse.SUPPRESS and action.default != argparse.SUPPRESS
    }
    values.update(parser._defaults)
    return values


def _decision_reasons(decision: AuthorizationDecision) -> tuple[str, ...]:
    return _unique(_denial_reason(denial) for denial in decision.denials)


def _decision_reason(decision: AuthorizationDecision) -> str:
    return "; ".join(_decision_reasons(decision))


def _denial_reason(denial: CapabilityDenial) -> str:
    if denial.code is DenialCode.MISSING_SCOPE:
        return "missing scope " + ", ".join(denial.missing_scopes)
    if denial.code is DenialCode.MISSING_PATH_GRANT:
        return f"requires a remote {denial.path_grant} root grant"
    return denial.reason


def _annotation(result: CommandVisibility, *, show_disallowed: bool) -> str | None:
    if result.allowed:
        return result.note
    if not show_disallowed:
        return None
    reasons = "; ".join(result.reasons) or "not permitted"
    return "disallowed: " + reasons


def _annotate_leaf(
    parser: argparse.ArgumentParser,
    result: CommandVisibility,
    *,
    show_disallowed: bool,
) -> None:
    annotation = _annotation(result, show_disallowed=show_disallowed)
    if not annotation:
        return
    line = "Capability: " + annotation + "."
    parser.description = f"{parser.description}\n\n{line}" if parser.description else line


def _remove_choice(action: argparse._SubParsersAction[Any], name: str) -> None:
    action.choices.pop(name, None)
    action._choices_actions[:] = [
        choice for choice in action._choices_actions if choice.dest != name
    ]


def _append_choice_help(
    action: argparse._SubParsersAction[Any],
    name: str,
    annotation: str,
) -> None:
    for choice in action._choices_actions:
        if choice.dest == name:
            choice.help = f"{choice.help} [{annotation}]"
            return


def _synchronize_grouped_help(parser: argparse.ArgumentParser) -> None:
    groups = getattr(parser, "command_groups", None)
    if not groups:
        return
    actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not actions:
        return
    action = actions[0]
    helps = {choice.dest: choice.help for choice in action._choices_actions}
    for group in groups:
        group.commands[:] = [
            (name, helps[name])
            for name, _ in group.commands
            if name in action.choices
        ]


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
