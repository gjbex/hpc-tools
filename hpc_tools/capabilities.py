from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


POLICY_VERSION = 1


class CapabilityPolicyError(ValueError):
    """Raised when capability policy is malformed or unsupported."""


class CapabilityLevel(str, Enum):
    PROFILE_CONTEXT = "profile-context"
    CLUSTER_DISCOVERY = "cluster-discovery"
    JOB_INSPECTION = "job-inspection"
    JOB_LIFECYCLE = "job-lifecycle"


CAPABILITY_LEVELS = tuple(CapabilityLevel)
_LEVEL_RANK = {level: rank for rank, level in enumerate(CAPABILITY_LEVELS)}

CAPABILITY_SCOPES = (
    "accounting.read",
    "config.read.raw",
    "delegation-ledger.read",
    "job.validate",
    "local-state.write",
    "remote-filesystem.list",
    "remote-filesystem.read",
    "remote-install.write",
    "remote-shell.execute",
    "remote-workspace.delete",
    "remote-workspace.write",
    "submission-record.write",
)
_CAPABILITY_SCOPE_SET = frozenset(CAPABILITY_SCOPES)

REMOTE_ROOT_KINDS = ("list", "read", "write", "delete", "install")
_ENV_ROOT = re.compile(
    r"^\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})(?:/|$)"
)
_FORBIDDEN_ROOT_CHARACTERS = frozenset("*?[]`'\";&|<>()\\")


@dataclass(frozen=True)
class RemoteRootGrants:
    list: tuple[str, ...] = ()
    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    delete: tuple[str, ...] = ()
    install: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for kind in REMOTE_ROOT_KINDS:
            roots = getattr(self, kind)
            if not isinstance(roots, tuple) or not all(
                isinstance(root, str) for root in roots
            ):
                raise CapabilityPolicyError(
                    f"remote root grant '{kind}' must be a tuple of strings"
                )
            if len(roots) != len(set(roots)):
                raise CapabilityPolicyError(
                    f"remote root grant '{kind}' must not contain duplicates"
                )
            for root in roots:
                _validate_root(root, context=f"remote root grant '{kind}'")

    def public_summary(self) -> dict[str, list[str]]:
        return {
            kind: list(getattr(self, kind))
            for kind in REMOTE_ROOT_KINDS
        }


@dataclass(frozen=True)
class CapabilityPolicy:
    version: int
    max_level: CapabilityLevel
    scopes: tuple[str, ...]
    remote_roots: RemoteRootGrants

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != POLICY_VERSION:
            raise CapabilityPolicyError(
                f"capability policy version must be the integer {POLICY_VERSION}"
            )
        if not isinstance(self.max_level, CapabilityLevel):
            raise CapabilityPolicyError(
                "capability policy max_level must be a CapabilityLevel"
            )
        if not isinstance(self.scopes, tuple) or not all(
            isinstance(scope, str) for scope in self.scopes
        ):
            raise CapabilityPolicyError(
                "capability policy scopes must be a tuple of strings"
            )
        if len(self.scopes) != len(set(self.scopes)):
            raise CapabilityPolicyError(
                "capability policy scopes must not contain duplicates"
            )
        unknown = sorted(set(self.scopes) - _CAPABILITY_SCOPE_SET)
        if unknown:
            raise CapabilityPolicyError(
                f"capability policy contains unknown scope(s): {', '.join(unknown)}"
            )
        if not isinstance(self.remote_roots, RemoteRootGrants):
            raise CapabilityPolicyError(
                "capability policy remote_roots must be RemoteRootGrants"
            )

    def public_summary(self) -> dict[str, object]:
        return {
            "version": self.version,
            "max_level": self.max_level.value,
            "scopes": list(self.scopes),
            "remote_roots": self.remote_roots.public_summary(),
        }


def parse_capability_level(
    value: object,
    *,
    field: str = "max_level",
) -> CapabilityLevel:
    if not isinstance(value, str):
        raise CapabilityPolicyError(f"capability {field} must be a string")
    try:
        return CapabilityLevel(value)
    except ValueError as error:
        choices = ", ".join(level.value for level in CAPABILITY_LEVELS)
        raise CapabilityPolicyError(
            f"unknown capability {field} '{value}'; expected one of: {choices}"
        ) from error


def parse_capability_policy(raw: Any, *, profile: str) -> CapabilityPolicy:
    prefix = f"profile '{profile}' capabilities"
    if not isinstance(raw, dict):
        raise CapabilityPolicyError(f"{prefix} must be a table")

    allowed_keys = {"version", "max_level", "scopes", "remote_roots"}
    _reject_unknown_keys(raw, allowed_keys, context=prefix)

    if "version" not in raw:
        raise CapabilityPolicyError(f"{prefix} must define version = {POLICY_VERSION}")
    version = raw["version"]
    if type(version) is not int or version != POLICY_VERSION:
        raise CapabilityPolicyError(
            f"{prefix} version must be the integer {POLICY_VERSION}"
        )

    if "max_level" not in raw:
        raise CapabilityPolicyError(f"{prefix} must define max_level")
    try:
        max_level = parse_capability_level(raw["max_level"])
    except CapabilityPolicyError as error:
        raise CapabilityPolicyError(f"{prefix}: {error}") from error

    scopes = _parse_scopes(raw.get("scopes", []), profile=profile)
    remote_roots = _parse_remote_roots(raw.get("remote_roots", {}), profile=profile)
    return CapabilityPolicy(
        version=version,
        max_level=max_level,
        scopes=scopes,
        remote_roots=remote_roots,
    )


def narrow_policy(
    policy: CapabilityPolicy,
    requested_level: CapabilityLevel | str | None,
) -> CapabilityPolicy:
    """Return policy narrowed by a requested ceiling; never raise authority."""
    if requested_level is None:
        return policy
    requested = (
        requested_level
        if isinstance(requested_level, CapabilityLevel)
        else parse_capability_level(requested_level, field="requested level")
    )
    effective = min((policy.max_level, requested), key=_LEVEL_RANK.__getitem__)
    if effective is policy.max_level:
        return policy
    return CapabilityPolicy(
        version=policy.version,
        max_level=effective,
        scopes=policy.scopes,
        remote_roots=policy.remote_roots,
    )


def intersect_policies(*policies: CapabilityPolicy) -> CapabilityPolicy:
    """Intersect independent grants without combining authority by union."""
    if not policies:
        raise ValueError("at least one capability policy is required")
    versions = {policy.version for policy in policies}
    if versions != {POLICY_VERSION}:
        raise ValueError("capability policies must use the supported version")

    max_level = min(
        (policy.max_level for policy in policies),
        key=_LEVEL_RANK.__getitem__,
    )
    scopes = tuple(sorted(set.intersection(*(
        set(policy.scopes) for policy in policies
    ))))
    # At the configuration layer only identical declarations intersect.
    # Ancestor/descendant and remote realpath semantics belong to WP4, where
    # roots can be resolved on the target host without unsafe local guessing.
    roots = RemoteRootGrants(**{
        kind: tuple(sorted(set.intersection(*(
            set(getattr(policy.remote_roots, kind))
            for policy in policies
        ))))
        for kind in REMOTE_ROOT_KINDS
    })
    return CapabilityPolicy(
        version=POLICY_VERSION,
        max_level=max_level,
        scopes=scopes,
        remote_roots=roots,
    )


def _parse_scopes(value: Any, *, profile: str) -> tuple[str, ...]:
    context = f"profile '{profile}' capabilities.scopes"
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CapabilityPolicyError(f"{context} must be a list of strings")
    if len(value) != len(set(value)):
        raise CapabilityPolicyError(f"{context} must not contain duplicates")
    unknown = sorted(set(value) - _CAPABILITY_SCOPE_SET)
    if unknown:
        raise CapabilityPolicyError(
            f"{context} contains unknown scope(s): {', '.join(unknown)}"
        )
    return tuple(sorted(value))


def _parse_remote_roots(value: Any, *, profile: str) -> RemoteRootGrants:
    context = f"profile '{profile}' capabilities.remote_roots"
    if not isinstance(value, dict):
        raise CapabilityPolicyError(f"{context} must be a table")
    _reject_unknown_keys(value, set(REMOTE_ROOT_KINDS), context=context)

    parsed: dict[str, tuple[str, ...]] = {}
    for kind in REMOTE_ROOT_KINDS:
        roots = value.get(kind, [])
        if not isinstance(roots, list) or not all(
            isinstance(root, str) for root in roots
        ):
            raise CapabilityPolicyError(f"{context}.{kind} must be a list of strings")
        if len(roots) != len(set(roots)):
            raise CapabilityPolicyError(f"{context}.{kind} must not contain duplicates")
        for root in roots:
            _validate_root(root, context=f"{context}.{kind}")
        parsed[kind] = tuple(sorted(roots))
    return RemoteRootGrants(**parsed)


def _validate_root(root: str, *, context: str) -> None:
    if not root or root != root.strip():
        raise CapabilityPolicyError(
            f"{context} contains an invalid empty or padded root"
        )
    if any(character in root for character in ("\0", "\n", "\r")):
        raise CapabilityPolicyError(
            f"{context} root contains a control character: {root!r}"
        )
    if any(character in _FORBIDDEN_ROOT_CHARACTERS for character in root):
        raise CapabilityPolicyError(
            f"{context} root contains shell or glob syntax: {root!r}"
        )

    if root == "~":
        suffix = ""
    elif root.startswith("~/"):
        suffix = root[2:]
    elif root.startswith("/"):
        suffix = root[1:]
    else:
        match = _ENV_ROOT.match(root)
        if match is None:
            raise CapabilityPolicyError(
                f"{context} root must be absolute or start with ~ or $NAME: {root!r}"
            )
        suffix = root[match.end():]

    if "$" in suffix or "~" in suffix:
        raise CapabilityPolicyError(
            f"{context} root contains expansion syntax outside its prefix: {root!r}"
        )
    invalid_segment = suffix and any(
        part in {"", ".", ".."} for part in suffix.split("/")
    )
    if root == "/" or invalid_segment:
        raise CapabilityPolicyError(
            f"{context} root must not be / or contain empty, . or .. segments: {root!r}"
        )
    if root.endswith("/"):
        raise CapabilityPolicyError(f"{context} root must not end with '/': {root!r}")


def _reject_unknown_keys(
    value: dict[str, Any],
    allowed: set[str],
    *,
    context: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CapabilityPolicyError(
            f"{context} contains unknown key(s): {', '.join(unknown)}"
        )
