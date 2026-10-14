from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from hpc_tools.capabilities import (
    AuthorizationContext,
    AuthorizationDecision,
    CapabilityPolicy,
    evaluate_capability,
)
from hpc_tools.config import ConfigError, Profile
from hpc_tools.operation_registry import (
    OPERATION_REGISTRY,
    OperationSurface,
    RequestContext,
    ResolvedOperation,
)


class CapabilityAuthorizationError(ConfigError):
    """Raised before effects when an operation exceeds profile authority."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        reasons = "; ".join(denial.reason for denial in decision.denials)
        super().__init__(
            f"operation '{decision.operation_id}' is not allowed for profile "
            f"'{decision.profile_name}': {reasons}"
        )


def require_authorized(
    operation_id: str,
    profile: Profile,
    arguments: Mapping[str, Any] | None = None,
    *,
    surface: OperationSurface = OperationSurface.SERVICE,
    restrictions: Iterable[CapabilityPolicy] = (),
) -> ResolvedOperation:
    """Resolve and authorize one operation before any external effect."""
    request = RequestContext(
        operation_id=operation_id,
        surface=surface,
        arguments=arguments or {},
        profile=profile,
    )
    resolved = OPERATION_REGISTRY.resolve(request)
    context = AuthorizationContext.from_profile(profile, restrictions=restrictions)
    decisions = (
        evaluate_capability(resolved.requirement, context),
        *(evaluate_capability(component, context) for component in resolved.components),
    )
    denials = tuple(
        denial
        for decision in decisions
        for denial in decision.denials
    )
    if denials:
        raise CapabilityAuthorizationError(AuthorizationDecision(
            operation_id=operation_id,
            profile_name=profile.name,
            denials=denials,
        ))
    return resolved


def namespace_arguments(namespace: Any) -> dict[str, Any]:
    """Copy public argparse values without retaining the mutable namespace."""
    return {
        name: value
        for name, value in vars(namespace).items()
        if not name.startswith("_") and name not in {"handler"}
    }
