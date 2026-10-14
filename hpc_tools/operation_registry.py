from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from hpc_tools.capabilities import (
    CAPABILITY_SCOPES,
    AuthorizationContext,
    AuthorizationDecision,
    CapabilityLevel,
    CapabilityRequirement,
    PathRequirement,
    evaluate_capability,
    unknown_operation_decision,
)


class RegistryError(ValueError):
    """Raised when operation metadata is incomplete or contradictory."""


class OperationSurface(str, Enum):
    CLI = "cli"
    MCP_TOOL = "mcp-tool"
    MCP_RESOURCE = "mcp-resource"
    SERVICE = "service"


@dataclass(frozen=True)
class PathBinding:
    grant: str
    selector: str
    argument: str | None = None
    profile_field: str | None = None


@dataclass(frozen=True)
class OperationDescriptor:
    id: str
    minimum_level: CapabilityLevel
    scopes: tuple[str, ...]
    effects: tuple[str, ...]
    cli: tuple[str, ...] = ()
    mcp: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    selectors: tuple[str, ...] = ()
    profile_required: bool = False
    operator_only: bool = False
    site_features: tuple[str, ...] = ()
    path_bindings: tuple[PathBinding, ...] = ()
    safety_guards: tuple[str, ...] = ()
    resolver: str = "default"

    def __post_init__(self) -> None:
        if not self.id:
            raise RegistryError("operation id must not be empty")
        if not (self.cli or self.mcp or self.resources):
            raise RegistryError(f"operation '{self.id}' has no interface binding")
        unknown = sorted(set(self.scopes) - set(CAPABILITY_SCOPES))
        if unknown:
            raise RegistryError(
                f"operation '{self.id}' has unknown scope(s): {', '.join(unknown)}"
            )
        if len(self.scopes) != len(set(self.scopes)):
            raise RegistryError(f"operation '{self.id}' has duplicate scopes")


@dataclass(frozen=True)
class RequestContext:
    operation_id: str
    surface: OperationSurface
    arguments: Mapping[str, Any]
    profile: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.surface, OperationSurface):
            raise ValueError("request context surface must be an OperationSurface")
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(dict(self.arguments)),
        )

    @classmethod
    def from_namespace(
        cls,
        operation_id: str,
        surface: OperationSurface,
        namespace: argparse.Namespace,
        *,
        profile: Any | None = None,
    ) -> RequestContext:
        return cls(
            operation_id=operation_id,
            surface=surface,
            arguments=MappingProxyType(vars(namespace).copy()),
            profile=profile,
        )


@dataclass(frozen=True)
class ResolvedOperation:
    descriptor: OperationDescriptor
    requirement: CapabilityRequirement
    selectors: tuple[tuple[str, object], ...]
    effects: tuple[str, ...]
    safety_guards: tuple[str, ...]
    overwrite_requested: bool
    components: tuple[CapabilityRequirement, ...] = ()


Resolver = Callable[[OperationDescriptor, RequestContext], ResolvedOperation]


class OperationRegistry:
    def __init__(
        self,
        operations: Iterable[OperationDescriptor],
        *,
        resolvers: Mapping[str, Resolver] | None = None,
    ) -> None:
        by_id: dict[str, OperationDescriptor] = {}
        bindings: dict[OperationSurface, dict[str, OperationDescriptor]] = {
            surface: {} for surface in OperationSurface
        }
        for operation in operations:
            if operation.id in by_id:
                raise RegistryError(f"duplicate operation id: {operation.id}")
            by_id[operation.id] = operation
            for surface, names in (
                (OperationSurface.CLI, operation.cli),
                (OperationSurface.MCP_TOOL, operation.mcp),
                (OperationSurface.MCP_RESOURCE, operation.resources),
            ):
                for name in names:
                    if name in bindings[surface]:
                        other = bindings[surface][name]
                        raise RegistryError(
                            f"conflicting {surface.value} binding '{name}': "
                            f"{other.id} and {operation.id}"
                        )
                    bindings[surface][name] = operation

        self._by_id = MappingProxyType(by_id)
        self._bindings = MappingProxyType({
            surface: MappingProxyType(names)
            for surface, names in bindings.items()
        })
        self._resolvers = MappingProxyType(dict(resolvers or {}))
        unknown_resolvers = sorted(
            operation.resolver
            for operation in by_id.values()
            if operation.resolver != "default"
            and operation.resolver not in self._resolvers
        )
        if unknown_resolvers:
            raise RegistryError(
                "operation registry has unknown resolver(s): "
                + ", ".join(sorted(set(unknown_resolvers)))
            )

    @property
    def operations(self) -> tuple[OperationDescriptor, ...]:
        return tuple(self._by_id.values())

    def get(self, operation_id: str) -> OperationDescriptor | None:
        return self._by_id.get(operation_id)

    def require(self, operation_id: str) -> OperationDescriptor:
        operation = self.get(operation_id)
        if operation is None:
            raise RegistryError(f"unknown operation: {operation_id}")
        return operation

    def for_binding(
        self,
        surface: OperationSurface,
        name: str,
    ) -> OperationDescriptor | None:
        return self._bindings[surface].get(name)

    def bindings(self, surface: OperationSurface) -> Mapping[str, OperationDescriptor]:
        return self._bindings[surface]

    def resolve(self, request: RequestContext) -> ResolvedOperation:
        descriptor = self.require(request.operation_id)
        resolver = self._resolvers.get(descriptor.resolver, _resolve_default)
        return resolver(descriptor, request)

    def authorize(
        self,
        request: RequestContext,
        context: AuthorizationContext,
    ) -> AuthorizationDecision:
        descriptor = self.get(request.operation_id)
        if descriptor is None:
            return unknown_operation_decision(
                request.operation_id,
                profile_name=context.profile_name,
            )
        return evaluate_capability(self.resolve(request).requirement, context)


_LEVELS = {
    "C0": CapabilityLevel.PROFILE_CONTEXT,
    "C1": CapabilityLevel.CLUSTER_DISCOVERY,
    "C2": CapabilityLevel.JOB_INSPECTION,
    "C3": CapabilityLevel.JOB_LIFECYCLE,
    "operator": CapabilityLevel.JOB_LIFECYCLE,
}


def _op(
    operation_id: str,
    level: str,
    scopes: list[str],
    effects: list[str],
    *,
    cli: list[str],
    mcp: list[str],
    resources: list[str],
    selectors: list[str],
) -> OperationDescriptor:
    profile_required = any(
        effect.startswith("remote-") or effect == "scheduler-write"
        for effect in effects
    ) or "profile" in selectors or "bound profile" in selectors
    return OperationDescriptor(
        id=operation_id,
        minimum_level=_LEVELS[level],
        scopes=tuple(scopes),
        effects=tuple(effects),
        cli=tuple(cli),
        mcp=tuple(mcp),
        resources=tuple(resources),
        selectors=tuple(selectors),
        profile_required=profile_required,
        operator_only=level == "operator",
    )


_OPERATIONS = (
    _op("capabilities.show", "C0", [], ["local-read"], cli=["capabilities"], mcp=[], resources=[], selectors=["profile", "config"]),
    _op("paths.show", "C0", [], ["local-read"], cli=["paths"], mcp=["hpc_paths"], resources=["hpc://paths"], selectors=[]),
    _op("plugins.list", "C0", [], ["local-read", "local-execute"], cli=["plugins list"], mcp=["hpc_plugins_list"], resources=[], selectors=[]),
    _op("plugins.info", "C0", [], ["local-read", "local-execute"], cli=["plugins info"], mcp=[], resources=[], selectors=["name"]),
    _op("profiles.list", "C0", [], ["local-read"], cli=[], mcp=["hpc_profiles_list"], resources=[], selectors=["config"]),
    _op("profiles.show", "C0", ["config.read.raw"], ["local-read"], cli=[], mcp=["hpc_profile_show"], resources=["hpc://profile"], selectors=["profile", "config"]),
    _op("config.read", "C0", ["config.read.raw"], ["local-read"], cli=[], mcp=[], resources=["hpc://config"], selectors=["active config"]),
    _op("references.list", "C0", [], ["local-read"], cli=["references list"], mcp=["hpc_references_list"], resources=[], selectors=[]),
    _op("references.show", "C0", [], ["local-read"], cli=["references show"], mcp=["hpc_references_show"], resources=["hpc://reference-set"], selectors=["name"]),
    _op("references.validate", "C0", [], ["local-read"], cli=["references validate"], mcp=[], resources=[], selectors=["name"]),
    _op("references.create", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["references create"], mcp=["hpc_references_create"], resources=[], selectors=["profile", "config", "name", "reference files"]),
    _op("references.export", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["references export"], mcp=[], resources=[], selectors=["profile", "config", "name", "output"]),
    _op("references.import", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["references import"], mcp=["hpc_references_import"], resources=[], selectors=["profile", "config", "archive", "reference-set destination"]),
    _op("references.attach", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["references attach"], mcp=["hpc_references_attach"], resources=[], selectors=["profile", "config", "name"]),
    _op("references.detach", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["references detach"], mcp=[], resources=[], selectors=["profile", "config"]),
    _op("agent.audit", "C2", ["delegation-ledger.read"], ["local-read"], cli=["agent audit"], mcp=[], resources=[], selectors=["profile", "config", "ledger", "database", "delegation-id"]),
    _op("agent.export", "C2", ["delegation-ledger.read", "local-state.write"], ["local-read", "local-write"], cli=["agent export"], mcp=[], resources=[], selectors=["profile", "config", "ledger", "database", "delegation-id", "output"]),
    _op("cluster.doctor", "C1", [], ["remote-read"], cli=["doctor"], mcp=[], resources=[], selectors=["profile", "config"]),
    _op("cluster.status", "C1", [], ["web-read"], cli=["status"], mcp=["hpc_status"], resources=[], selectors=["profile", "config", "status_url"]),
    _op("cluster.site-env", "C1", [], ["remote-read"], cli=["site-env"], mcp=["hpc_site_env"], resources=[], selectors=["profile", "config"]),
    _op("references.context", "C0", [], ["local-read"], cli=["hardware"], mcp=["hpc_hardware_context"], resources=["hpc://cluster/hardware", "hpc://cluster/slurm", "hpc://cluster/storage"], selectors=["profile", "config", "reference files"]),
    _op("references.sources", "C0", [], ["local-read"], cli=[], mcp=["hpc_hardware_sources"], resources=[], selectors=["profile", "config", "reference_set"]),
    _op("filesystem.inspect", "C1", ["remote-filesystem.list"], ["remote-read"], cli=["storage inspect"], mcp=["hpc_storage_inspect"], resources=[], selectors=["profile", "config", "path"]),
    _op("filesystem.list", "C1", ["remote-filesystem.list"], ["remote-read"], cli=["files list"], mcp=["hpc_files_list"], resources=[], selectors=["profile", "config", "path", "max_entries"]),
    _op("filesystem.read", "C1", ["remote-filesystem.read"], ["remote-read"], cli=["files read"], mcp=["hpc_files_read"], resources=[], selectors=["profile", "config", "path", "encoding", "max_bytes"]),
    _op("filesystem.download", "C1", ["remote-filesystem.read", "local-state.write"], ["remote-read", "local-write"], cli=["files download"], mcp=["hpc_files_download"], resources=[], selectors=["profile", "config", "source", "output", "force", "max_bytes"]),
    _op("filesystem.upload", "C1", ["remote-workspace.write"], ["local-read", "remote-write"], cli=["files upload"], mcp=["hpc_files_upload"], resources=[], selectors=["profile", "config", "source", "destination", "force", "max_bytes"]),
    _op("filesystem.copy", "C1", ["remote-filesystem.read", "remote-workspace.write"], ["remote-read", "remote-write"], cli=["files copy"], mcp=["hpc_files_copy"], resources=[], selectors=["profile", "config", "source", "destination", "force", "max_bytes"]),
    _op("filesystem.mkdir", "C1", ["remote-workspace.write"], ["remote-write"], cli=["files mkdir"], mcp=["hpc_files_mkdir"], resources=[], selectors=["profile", "config", "path"]),
    _op("filesystem.remove", "C1", ["remote-workspace.delete"], ["remote-write"], cli=["files remove"], mcp=["hpc_files_remove"], resources=[], selectors=["profile", "config", "path"]),
    _op("cluster.quota", "C1", [], ["remote-read"], cli=["quota"], mcp=[], resources=[], selectors=["profile", "config", "quota_command"]),
    _op("cluster.modules", "C1", [], ["remote-read"], cli=["module-spider"], mcp=["hpc_module_spider"], resources=[], selectors=["profile", "config", "name"]),
    _op("cluster.limits", "C1", [], ["remote-read"], cli=["slurm-limits"], mcp=["hpc_slurm_limits"], resources=[], selectors=["profile", "config", "cluster", "partition", "qos"]),
    _op("filesystem.projects", "C1", ["remote-filesystem.list"], ["remote-read"], cli=["projects"], mcp=[], resources=[], selectors=["profile", "config", "projects_dir"]),
    _op("repository.status", "C1", ["remote-filesystem.list", "remote-filesystem.read"], ["remote-read"], cli=["repo status"], mcp=[], resources=[], selectors=["profile", "config", "directory"]),
    _op("repository.clone", "C1", ["remote-workspace.write"], ["remote-read", "remote-write", "network-read"], cli=["clone"], mcp=["hpc_repo_clone"], resources=[], selectors=["profile", "config", "url", "directory", "name", "branch"]),
    _op("remote.shell", "operator", ["remote-shell.execute"], ["remote-execute"], cli=["run"], mcp=[], resources=[], selectors=["profile", "config", "remote_command"]),
    _op("probe.write", "C0", [], ["local-read", "local-write"], cli=["write-probe", "write-hardware-probe"], mcp=["hpc_write_probe"], resources=[], selectors=["profile", "config", "kind", "output", "force"]),
    _op("probe.install", "C1", ["remote-install.write"], ["local-read", "remote-write"], cli=["install-probe", "install-hardware-probe"], mcp=["hpc_install_probe"], resources=[], selectors=["profile", "config", "kind", "directory", "name", "force"]),
    _op("container.write", "C0", ["local-state.write"], ["local-read", "local-write"], cli=["write-container"], mcp=["hpc_write_container"], resources=[], selectors=["profile", "config", "kind", "output", "force"]),
    _op("container.install", "C1", ["remote-install.write"], ["local-read", "remote-write"], cli=["install-container"], mcp=["hpc_install_container"], resources=[], selectors=["profile", "config", "kind", "directory", "force"]),
    _op("job.quote", "C2", ["job.validate", "accounting.read"], ["remote-read", "local-read", "local-write"], cli=["quote"], mcp=["hpc_quote_job"], resources=[], selectors=["profile", "config", "account", "jobscript", "directory", "resource shape", "container", "idempotency_key"]),
    _op("account.balance", "C1", ["accounting.read"], ["remote-read"], cli=["balance"], mcp=[], resources=[], selectors=["profile", "config", "sam_balance_command"]),
    _op("account.statement", "C1", ["accounting.read"], ["remote-read"], cli=["statement"], mcp=[], resources=[], selectors=["profile", "config", "account", "start", "end"]),
    _op("job.submit", "C3", [], ["remote-execute", "scheduler-write", "local-read", "local-write"], cli=["submit"], mcp=["hpc_submit_job"], resources=[], selectors=["profile", "config", "jobscript", "directory", "resource shape", "database", "quote_evidence", "validation_evidence"]),
    _op("job.validate", "C2", ["job.validate"], ["remote-read", "local-read", "local-write"], cli=[], mcp=["hpc_validate_job"], resources=[], selectors=["profile", "config", "jobscript", "directory", "resource shape", "container", "idempotency_key"]),
    _op("job.list", "C2", [], ["remote-read", "local-read", "local-write"], cli=["jobs"], mcp=["hpc_jobs"], resources=[], selectors=["profile", "config", "cluster", "delegation ledger"]),
    _op("job.show", "C2", [], ["remote-read", "local-read"], cli=["job"], mcp=["hpc_job"], resources=[], selectors=["profile", "config", "jobid", "cluster", "delegation ledger"]),
    _op("job.cancel", "C3", [], ["scheduler-write", "local-read", "local-write"], cli=["cancel"], mcp=["hpc_cancel_job"], resources=[], selectors=["profile", "config", "jobid", "cluster", "database", "reason", "idempotency_key"]),
    _op("job.queue", "C2", [], ["remote-read"], cli=["queue"], mcp=[], resources=[], selectors=["profile", "config", "queue_command"]),
    _op("job.accounting", "C2", [], ["remote-read", "local-read", "local-write"], cli=["sacct"], mcp=["hpc_job_accounting"], resources=[], selectors=["profile", "config", "jobid", "cluster", "delegation ledger"]),
    _op("submissions.list", "C2", [], ["local-read"], cli=["submissions list"], mcp=["hpc_submissions_list"], resources=["hpc://submissions/active", "hpc://submissions/all"], selectors=["profile", "config", "database", "all"]),
    _op("submissions.observe", "C2", ["submission-record.write"], ["local-read", "remote-read", "local-write"], cli=["submissions observe"], mcp=[], resources=[], selectors=["profile", "config", "database", "run_id"]),
    _op("submissions.mark-collected", "C2", ["submission-record.write"], ["local-read", "local-write"], cli=["submissions mark-collected"], mcp=["hpc_submissions_mark_collected"], resources=[], selectors=["profile", "config", "database", "run_id", "path"]),
    _op("submissions.mark-analysed", "C2", ["submission-record.write"], ["local-read", "local-write"], cli=["submissions mark-analysed"], mcp=["hpc_submissions_mark_analysed"], resources=[], selectors=["profile", "config", "database", "run_id", "path"]),
    _op("submissions.close", "C2", ["submission-record.write"], ["local-read", "local-write"], cli=["submissions close"], mcp=["hpc_submissions_close"], resources=[], selectors=["profile", "config", "database", "run_id", "reason"]),
    _op("benchmark.summarize", "C0", [], ["local-read"], cli=["benchmark summarize"], mcp=[], resources=[], selectors=["targets"]),
    _op("benchmark.compare", "C0", [], ["local-read"], cli=["benchmark compare"], mcp=[], resources=[], selectors=["baseline", "candidate", "candidate_threads"]),
    _op("cxx.scan", "C0", [], ["local-read"], cli=["cxx scan"], mcp=[], resources=[], selectors=["target"]),
    _op("cxx.fetchcontent", "C0", [], ["local-read"], cli=["cxx fetchcontent"], mcp=[], resources=[], selectors=["package"]),
    _op("python.scan", "C0", [], ["local-read"], cli=["python scan"], mcp=[], resources=[], selectors=["target"]),
    _op("python.inspect-deps", "C0", [], ["local-read"], cli=["python inspect-deps"], mcp=[], resources=[], selectors=["target"]),
    _op("python.check", "C1", [], ["local-read", "remote-execute"], cli=["python check"], mcp=[], resources=[], selectors=["profile", "config", "target", "packages", "modules"]),
    _op("python.plan-install", "C1", ["local-state.write"], ["local-read", "remote-execute", "local-write"], cli=["python plan-install"], mcp=[], resources=[], selectors=["profile", "config", "target", "packages", "modules", "output", "venv/library root"]),
    _op("python.submit-install", "C3", ["remote-workspace.write", "job.validate", "accounting.read"], ["local-read", "remote-write", "remote-read", "scheduler-write", "local-write"], cli=["python submit-install"], mcp=[], resources=[], selectors=["profile", "config", "jobscript", "directory", "remote_name", "force", "account", "resource shape"]),
    _op("python.verify-install", "C1", ["remote-filesystem.read"], ["remote-read"], cli=["python verify-install"], mcp=[], resources=[], selectors=["profile", "config", "job_output", "packages"]),
    _op("r.scan", "C0", [], ["local-read"], cli=["r scan"], mcp=[], resources=[], selectors=["target"]),
    _op("r.check", "C1", [], ["local-read", "remote-execute"], cli=["r check"], mcp=[], resources=[], selectors=["profile", "config", "target", "packages", "modules"]),
    _op("r.plan-install", "C1", ["local-state.write"], ["local-read", "remote-execute", "local-write"], cli=["r plan-install"], mcp=[], resources=[], selectors=["profile", "config", "target", "packages", "modules", "output", "venv/library root"]),
    _op("r.submit-install", "C3", ["remote-workspace.write", "job.validate", "accounting.read"], ["local-read", "remote-write", "remote-read", "scheduler-write", "local-write"], cli=["r submit-install"], mcp=[], resources=[], selectors=["profile", "config", "jobscript", "directory", "remote_name", "force", "account", "resource shape"]),
    _op("r.verify-install", "C1", ["remote-filesystem.read"], ["remote-read"], cli=["r verify-install"], mcp=[], resources=[], selectors=["profile", "config", "job_output", "packages"]),
    _op("delegation.runtime", "C0", [], ["local-read", "local-write"], cli=[], mcp=[], resources=["hpc://runtime"], selectors=["bound profile", "delegation manifest", "ledger"]),
)


_DESCRIPTOR_OVERRIDES: dict[str, dict[str, object]] = {
    "references.context": {"site_features": ("hardware-context",)},
    "cluster.status": {
        "site_features": ("status-page",),
    },
    "cluster.quota": {"site_features": ("quota",)},
    "filesystem.inspect": {
        "path_bindings": (
            PathBinding("list", "path", argument="path", profile_field="projects_dir"),
        ),
    },
    "filesystem.list": {
        "path_bindings": (PathBinding("list", "path", argument="path"),),
    },
    "filesystem.read": {
        "path_bindings": (PathBinding("read", "path", argument="path"),),
    },
    "filesystem.download": {
        "path_bindings": (PathBinding("read", "source", argument="source"),),
        "resolver": "mcp-confirm",
    },
    "filesystem.upload": {
        "path_bindings": (PathBinding("write", "destination", argument="destination"),),
        "resolver": "mcp-confirm",
    },
    "filesystem.copy": {
        "path_bindings": (
            PathBinding("read", "source", argument="source"),
            PathBinding("write", "destination", argument="destination"),
        ),
        "resolver": "mcp-confirm",
    },
    "filesystem.mkdir": {
        "path_bindings": (PathBinding("write", "path", argument="path"),),
        "resolver": "mcp-confirm",
    },
    "filesystem.remove": {
        "path_bindings": (PathBinding("delete", "path", argument="path"),),
        "resolver": "mcp-confirm",
    },
    "filesystem.projects": {
        "site_features": ("projects-directory",),
        "path_bindings": (PathBinding("list", "projects_dir", profile_field="projects_dir"),),
    },
    "repository.status": {
        "path_bindings": (
            PathBinding("list", "directory", argument="directory"),
            PathBinding("read", "directory", argument="directory"),
        ),
    },
    "repository.clone": {
        "path_bindings": (
            PathBinding("write", "directory", argument="directory", profile_field="projects_dir"),
        ),
        "resolver": "clone",
    },
    "probe.write": {"resolver": "probe-write"},
    "probe.install": {
        "path_bindings": (PathBinding("install", "directory", argument="directory"),),
    },
    "container.install": {
        "path_bindings": (PathBinding("install", "directory", argument="directory"),),
    },
    "job.quote": {"site_features": ("job-quote",)},
    "account.balance": {"site_features": ("account-balance",)},
    "account.statement": {"site_features": ("account-statement",)},
    "job.submit": {"resolver": "job-submit"},
    "job.cancel": {"resolver": "mcp-confirm-or-delegation"},
    "job.queue": {"site_features": ("queue",)},
    "python.submit-install": {
        "path_bindings": (PathBinding("write", "directory", argument="directory"),),
        "resolver": "install-submit",
    },
    "python.verify-install": {
        "path_bindings": (PathBinding("read", "job_output", argument="job_output"),),
    },
    "r.submit-install": {
        "path_bindings": (PathBinding("write", "directory", argument="directory"),),
        "resolver": "install-submit",
    },
    "r.verify-install": {
        "path_bindings": (PathBinding("read", "job_output", argument="job_output"),),
    },
}


def _apply_overrides(operation: OperationDescriptor) -> OperationDescriptor:
    updates = _DESCRIPTOR_OVERRIDES.get(operation.id)
    return replace(operation, **updates) if updates else operation


def _resolved(
    descriptor: OperationDescriptor,
    request: RequestContext,
    *,
    requirement: CapabilityRequirement | None = None,
    effects: tuple[str, ...] | None = None,
    safety_guards: tuple[str, ...] | None = None,
) -> ResolvedOperation:
    arguments = request.arguments
    paths = tuple(
        PathRequirement(
            grant=binding.grant,
            selector=binding.selector,
            path=_path_value(binding, request),
        )
        for binding in descriptor.path_bindings
    )
    base_requirement = CapabilityRequirement(
        operation_id=descriptor.id,
        minimum_level=descriptor.minimum_level,
        scopes=descriptor.scopes,
        paths=paths,
        site_features=descriptor.site_features,
        operator_only=descriptor.operator_only,
    )
    selectors = tuple(
        (selector, arguments[key])
        for selector in descriptor.selectors
        for key in (_selector_key(selector),)
        if key in arguments and arguments[key] is not None
    )
    return ResolvedOperation(
        descriptor=descriptor,
        requirement=requirement or base_requirement,
        selectors=selectors,
        effects=effects or descriptor.effects,
        safety_guards=safety_guards if safety_guards is not None else descriptor.safety_guards,
        overwrite_requested=bool(arguments.get("force", False)),
    )


def _resolve_default(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    return _resolved(descriptor, request)


def _resolve_probe_write(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    preview = (
        request.surface is OperationSurface.MCP_TOOL
        and not bool(request.arguments.get("confirm", False))
    )
    stdout_only = request.arguments.get("output", "-") == "-"
    scopes = () if preview or stdout_only else ("local-state.write",)
    effects = ("local-read",) if preview or stdout_only else descriptor.effects
    requirement = CapabilityRequirement(
        operation_id=descriptor.id,
        minimum_level=descriptor.minimum_level,
        scopes=scopes,
    )
    guards = () if preview or stdout_only else ("confirmation",)
    return _resolved(
        descriptor,
        request,
        requirement=requirement,
        effects=effects,
        safety_guards=guards,
    )


def _resolve_job_submit(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    arguments = request.arguments
    if request.surface is OperationSurface.MCP_TOOL:
        level = CapabilityLevel.JOB_LIFECYCLE
        scopes = ("accounting.read", "job.validate")
        guards = (
            "confirmation-or-delegation",
            "quote-evidence",
            "validation-evidence",
        )
    elif bool(arguments.get("test_only", False)):
        level = CapabilityLevel.JOB_INSPECTION
        scopes = ("job.validate",)
        guards = ()
    else:
        level = CapabilityLevel.JOB_LIFECYCLE
        scopes = ("job.validate",) if arguments.get("validate_first", False) else ()
        guards = ()
    requirement = CapabilityRequirement(
        operation_id=descriptor.id,
        minimum_level=level,
        scopes=scopes,
        site_features=("job-quote",) if request.surface is OperationSurface.MCP_TOOL else (),
    )
    return _resolved(
        descriptor,
        request,
        requirement=requirement,
        safety_guards=guards,
    )


def _resolve_install_submit(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    scopes = {"remote-workspace.write", "job.validate", "accounting.read"}
    quote_unavailable = (
        request.profile is not None
        and not getattr(request.profile, "sam_quote_command", None)
    )
    if request.arguments.get("skip_quote", False) or quote_unavailable:
        scopes.discard("accounting.read")
    if request.arguments.get("no_validate_first", False):
        scopes.discard("job.validate")
    base = _resolved(descriptor, request)
    requirement = replace(base.requirement, scopes=tuple(sorted(scopes)))
    return replace(base, requirement=requirement)


def _resolve_clone(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    base = _resolved(
        descriptor,
        request,
        safety_guards=("confirmation",)
        if request.surface is OperationSurface.MCP_TOOL
        else (),
    )
    if request.arguments.get("directory") is not None:
        return base
    return replace(
        base,
        requirement=replace(
            base.requirement,
            site_features=tuple(sorted({
                *base.requirement.site_features,
                "projects-directory",
            })),
        ),
    )


def _resolve_mcp_confirm_or_delegation(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    guards = (
        ("confirmation-or-delegation",)
        if request.surface is OperationSurface.MCP_TOOL
        else ()
    )
    return _resolved(descriptor, request, safety_guards=guards)


def _resolve_mcp_confirm(
    descriptor: OperationDescriptor,
    request: RequestContext,
) -> ResolvedOperation:
    guards = ("confirmation",) if request.surface is OperationSurface.MCP_TOOL else ()
    return _resolved(descriptor, request, safety_guards=guards)


def _path_value(binding: PathBinding, request: RequestContext) -> str | None:
    value = request.arguments.get(binding.argument) if binding.argument else None
    if value == "." and binding.profile_field:
        value = None
    if value is None and binding.profile_field and request.profile is not None:
        value = getattr(request.profile, binding.profile_field, None)
    return str(value) if value is not None else None


def _selector_key(selector: str) -> str:
    return selector.replace("-", "_").replace(" ", "_").replace("/", "_")


OPERATION_REGISTRY = OperationRegistry(
    (_apply_overrides(operation) for operation in _OPERATIONS),
    resolvers={
        "clone": _resolve_clone,
        "install-submit": _resolve_install_submit,
        "job-submit": _resolve_job_submit,
        "mcp-confirm": _resolve_mcp_confirm,
        "mcp-confirm-or-delegation": _resolve_mcp_confirm_or_delegation,
        "probe-write": _resolve_probe_write,
    },
)


def operation_for_cli(command: str) -> OperationDescriptor | None:
    return OPERATION_REGISTRY.for_binding(OperationSurface.CLI, command)


def operation_for_mcp(tool: str) -> OperationDescriptor | None:
    return OPERATION_REGISTRY.for_binding(OperationSurface.MCP_TOOL, tool)


def operation_for_resource(uri: str) -> OperationDescriptor | None:
    return OPERATION_REGISTRY.for_binding(OperationSurface.MCP_RESOURCE, uri)
