from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from hpc_tools.capabilities import (
    AuthorizationContext,
    CapabilityLevel,
    CapabilityPolicy,
    CapabilityRequirement,
    evaluate_capability,
    parse_capability_policy,
)
from hpc_tools.config import ConfigError, default_config_dir
from hpc_tools.credit_quotes import (
    CREDIT_UNIT_PATTERN,
    MAX_CREDIT_SCALE,
    MAX_CREDIT_VALUE,
    STRUCTURED_QUOTE_FORMAT_V1,
    CreditAmount,
    CreditQuoteError,
    parse_credit_amount,
)

MANIFEST_VERSION = 4
LEDGER_SCHEMA_VERSION = 5
DELEGATION_ENV_VAR = "HPC_TOOLS_MCP_DELEGATION"
LEDGER_ENV_VAR = "HPC_TOOLS_MCP_LEDGER"
PARENT_JOB_ENV_VAR = "HPC_TOOLS_PARENT_JOB_ID"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
CONTROLLER_RESTART_ENV_VAR = "SLURM_RESTART_COUNT"
CLEANUP_CANCEL_ATTEMPTS = 3


class DelegationError(ConfigError):
    """Raised when delegation authorization or accounting fails."""


class SubmissionDenialCode(StrEnum):
    """Stable public reasons for rejecting a delegated submission."""

    QUOTE_FORMAT = "quote.format"
    QUOTE_FAILED = "quote.failed"
    QUOTE_EXPIRED = "quote.expired"
    VALIDATION_FAILED = "validation.failed"
    PER_JOB_CREDIT = "budget.per_job_credit"
    TOTAL_CREDITS = "budget.total_credits"
    SUBMISSION_COUNT = "budget.submission_count"
    ACTIVE_JOBS = "budget.active_jobs"
    RESOURCES = "budget.resources"


class SubmissionDenied(DelegationError):
    """A delegated submission denial safe to summarize to the harness."""

    def __init__(
        self,
        code: SubmissionDenialCode,
        message: str,
        *,
        resource: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.resource = resource

    def public_summary(self) -> dict[str, str]:
        result = {"code": self.code.value, "reason": str(self)}
        if self.resource is not None:
            result["resource"] = self.resource
        return result


class AgentNetworkMode(StrEnum):
    """Operator-selected network policy for the unattended agent harness."""

    MODEL_ONLY = "model-only"
    MODEL_INDEXED_SEARCH = "model-indexed-search"
    MODEL_LIVE_SEARCH = "model-live-search"


@dataclass(frozen=True)
class AgentNetworkPolicy:
    """Public network contract selected by the protected manifest."""

    mode: AgentNetworkMode

    @property
    def web_search_mode(self) -> str:
        return {
            AgentNetworkMode.MODEL_ONLY: "disabled",
            AgentNetworkMode.MODEL_INDEXED_SEARCH: "indexed",
            AgentNetworkMode.MODEL_LIVE_SEARCH: "live",
        }[self.mode]

    def public_summary(self) -> dict[str, str | bool]:
        return {
            "mode": self.mode.value,
            "web_search": self.web_search_mode,
            "command_network_access": False,
        }


@dataclass(frozen=True)
class FilesystemPolicy:
    """Host-selected paths used to isolate an unattended agent and its jobs."""

    state_root: Path
    work_root: Path
    output_root: Path
    input_roots: tuple[Path, ...]
    apptainer_path: Path
    max_file_blocks: int | None = None
    max_open_files: int | None = None

    def public_summary(self) -> dict[str, Any]:
        # state_root and apptainer_path are deliberately host-private details.
        return {
            "configured": True,
            "work_root": str(self.work_root),
            "output_root": str(self.output_root),
            "input_roots": [str(path) for path in self.input_roots],
            "max_file_blocks": self.max_file_blocks,
            "max_open_files": self.max_open_files,
        }


@dataclass(frozen=True)
class LifecyclePolicy:
    """Issuer-selected treatment of delegated jobs when the parent ends."""

    on_cancel: str = "cancel"
    on_timeout: str = "requeue-or-cancel"
    on_failure: str = "cancel"
    on_normal_exit_with_active_jobs: str = "cancel"
    max_requeues: int = 3
    warning_seconds: int = 600

    def public_summary(self) -> dict[str, Any]:
        return {
            "on_cancel": self.on_cancel,
            "on_timeout": self.on_timeout,
            "on_failure": self.on_failure,
            "on_normal_exit_with_active_jobs": self.on_normal_exit_with_active_jobs,
            "max_requeues": self.max_requeues,
            "warning_seconds": self.warning_seconds,
        }


@dataclass(frozen=True)
class CreditBudget:
    """Issuer-selected fixed-point quoted-credit limits."""

    unit: str
    scale: int
    maximum_total: int
    maximum_per_job: int | None
    quote_ttl_seconds: int

    def public_summary(self) -> dict[str, int | str | None]:
        return {
            "unit": self.unit,
            "scale": self.scale,
            "maximum_total": self.maximum_total,
            "maximum_per_job": self.maximum_per_job,
            "quote_ttl_seconds": self.quote_ttl_seconds,
        }


@dataclass(frozen=True)
class QuotedCreditReservation:
    """Validated quote authority consumed by one ledger reservation."""

    cost: CreditAmount
    evidence_token: str
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "quoted_cost": self.cost.to_dict(),
            "quote_evidence_token": self.evidence_token,
            "quote_expires_at": _canonical_time(self.expires_at),
        }


@dataclass(frozen=True)
class DelegationManifest:
    identifier: str
    issuer: str
    profile: str
    parent_job_id: str
    issued_at: str
    expires_at: str
    allowed: dict[str, tuple[str, ...]]
    per_job_limits: dict[str, int]
    budget: dict[str, int]
    credit_budget: CreditBudget | None
    network: AgentNetworkPolicy
    filesystem: FilesystemPolicy | None
    lifecycle: LifecyclePolicy
    source_path: Path
    digest: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "configured": True,
            "identifier": self.identifier,
            "issuer": self.issuer,
            "profile": self.profile,
            "parent_job_id": self.parent_job_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "allowed": {key: list(value) for key, value in self.allowed.items()},
            "per_job_limits": self.per_job_limits,
            "budget": self.budget,
            "network": self.network.public_summary(),
            "credit_budget": (
                self.credit_budget.public_summary()
                if self.credit_budget is not None
                else {"configured": False}
            ),
            "lifecycle": self.lifecycle.public_summary(),
            "filesystem": (
                self.filesystem.public_summary()
                if self.filesystem is not None
                else {"configured": False}
            ),
        }


@dataclass(frozen=True)
class DelegationRuntime:
    manifest: DelegationManifest
    ledger_path: Path
    controller_authority: ControllerAuthority
    controller_generation: int


@dataclass(frozen=True)
class ControllerAuthority:
    """Immutable profile-policy ceiling captured for one delegation."""

    policy: CapabilityPolicy
    policy_sha256: str
    config_path: str
    config_sha256: str
    credit_budget: CreditBudget | None
    quote_format: str | None
    captured_at: str

    def public_summary(self, *, include_config_path: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "policy": self.policy.public_summary(),
            "policy_sha256": self.policy_sha256,
            "config_sha256": self.config_sha256,
            "credit_budget": (
                self.credit_budget.public_summary()
                if self.credit_budget is not None
                else {"configured": False}
            ),
            "quote_format": self.quote_format,
            "captured_at": self.captured_at,
        }
        if include_config_path:
            summary["config_path"] = self.config_path
        return summary


_CURRENT: ContextVar[DelegationRuntime | None] = ContextVar(
    "hpc_tools_delegation",
    default=None,
)


def default_ledger_path() -> Path:
    return default_config_dir() / "delegations.sqlite3"


def load_runtime(
    manifest_path: str | Path,
    *,
    profile: str,
    ledger_path: str | Path | None = None,
    parent_job_id: str | None = None,
    profile_policy: CapabilityPolicy,
    config_path: str | Path,
    config_sha256: str,
    sam_quote_command: str | None = None,
    sam_quote_format: str | None = None,
) -> DelegationRuntime:
    manifest = load_manifest(
        Path(manifest_path),
        expected_profile=profile,
        expected_parent_job_id=parent_job_id,
    )
    require_credit_configuration(
        manifest,
        sam_quote_command=sam_quote_command,
        sam_quote_format=sam_quote_format,
    )
    selected = Path(
        ledger_path or os.environ.get(LEDGER_ENV_VAR) or default_ledger_path()
    ).expanduser()
    ledger = DelegationLedger(selected)
    ledger.register(manifest)
    authority = ledger.controller_authority_or_none(manifest)
    if authority is None:
        require_controller_authority(profile_policy, operation="agent.controller.start")
        authority = ledger.capture_controller_authority(
            manifest,
            policy=profile_policy,
            config_path=config_path,
            config_sha256=config_sha256,
            quote_format=sam_quote_format,
        )
    else:
        require_controller_authority(
            authority.policy,
            operation="agent.controller.continue",
        )
    controller = ledger.begin_controller(
        manifest,
        restart_count=_controller_restart_count(),
    )
    return DelegationRuntime(
        manifest,
        selected,
        authority,
        int(controller["generation"]),
    )


def require_credit_configuration(
    manifest: DelegationManifest,
    *,
    sam_quote_command: str | None,
    sam_quote_format: str | None,
) -> None:
    """Fail before controller startup when credit enforcement cannot quote."""
    if manifest.credit_budget is None:
        return
    if not sam_quote_command:
        raise DelegationError(
            "delegation credit_budget requires profile sam_quote_command"
        )
    if sam_quote_format != STRUCTURED_QUOTE_FORMAT_V1:
        raise DelegationError(
            "delegation credit_budget requires profile sam_quote_format "
            f"{STRUCTURED_QUOTE_FORMAT_V1!r}"
        )


def require_controller_authority(
    policy: CapabilityPolicy,
    *,
    operation: str,
) -> None:
    """Require captured C3 authority for controller-owned scheduler effects."""
    decision = evaluate_capability(
        CapabilityRequirement(
            operation_id=operation,
            minimum_level=CapabilityLevel.JOB_LIFECYCLE,
        ),
        AuthorizationContext(profile_name="controller", policy=policy),
    )
    if not decision.allowed:
        reasons = "; ".join(denial.reason for denial in decision.denials)
        raise DelegationError(f"{operation} is not authorized: {reasons}")


@contextmanager
def delegation_scope(runtime: DelegationRuntime | None) -> Iterator[None]:
    token = _CURRENT.set(runtime)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_runtime() -> DelegationRuntime | None:
    return _CURRENT.get()


def load_manifest(
    path: Path,
    *,
    expected_profile: str,
    expected_parent_job_id: str | None = None,
    now: datetime | None = None,
    allow_expired: bool = False,
) -> DelegationManifest:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DelegationError(f"delegation manifest is not a regular file: {path}")
    if os.name == "posix":
        stat = path.stat()
        if stat.st_uid != os.geteuid():
            raise DelegationError(f"delegation manifest is not owned by the server user: {path}")
        if stat.st_mode & 0o022:
            raise DelegationError(
                f"delegation manifest must not be group- or world-writable: {path}"
            )
    payload = path.read_bytes()
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DelegationError(f"invalid delegation manifest {path}: {error}") from error
    _reject_unknown_keys(
        raw,
        {
            "format_version", "id", "issuer", "profile", "parent_job_id",
            "issued_at", "expires_at", "allowed", "per_job_limits", "budget",
            "credit_budget", "network", "filesystem", "lifecycle",
        },
        "delegation manifest",
    )
    if raw.get("format_version") != MANIFEST_VERSION:
        raise DelegationError(
            f"unsupported delegation manifest version {raw.get('format_version')!r}; "
            f"expected {MANIFEST_VERSION}"
        )
    network = _network_policy(raw.get("network"))
    identifier = _string(raw, "id")
    profile = _string(raw, "profile")
    parent = _string(raw, "parent_job_id")
    issued = _timestamp_field(raw, "issued_at")
    expires = _timestamp_field(raw, "expires_at")
    instant = now or datetime.now(timezone.utc)
    if profile != expected_profile:
        raise DelegationError("delegation profile does not match the selected profile")
    if expected_parent_job_id and parent != expected_parent_job_id:
        raise DelegationError("delegation parent job does not match the server context")
    if not allow_expired and _parse_time(expires) <= instant:
        raise DelegationError(f"delegation {identifier!r} is expired")
    if _parse_time(issued) > instant:
        raise DelegationError(f"delegation {identifier!r} has a future issue time")

    allowed_table = _table(raw, "allowed")
    keys = (
        "accounts", "clusters", "partitions", "qos", "reservations",
        "containers", "script_sha256", "roots",
    )
    _reject_unknown_keys(allowed_table, set(keys), "allowed")
    allowed = {key: _strings(allowed_table, key) for key in keys}
    if not allowed["accounts"] or not allowed["clusters"]:
        raise DelegationError("allowed accounts and clusters must not be empty")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in allowed["script_sha256"]):
        raise DelegationError("script_sha256 values must be lowercase SHA-256 hashes")
    for value in allowed["roots"]:
        root = Path(value)
        if not root.is_absolute() or ".." in root.parts:
            raise DelegationError("allowed roots must be absolute normalized paths")
    filesystem = _filesystem_policy(raw.get("filesystem"))
    if filesystem is not None:
        if not allowed["containers"]:
            raise DelegationError(
                "a filesystem policy requires at least one allowed container"
            )
        if not _under_roots(str(filesystem.work_root), allowed["roots"]):
            raise DelegationError(
                "filesystem.work_root must be authorized by allowed.roots"
            )

    per_job_limits = _positive_ints(
        raw.get("per_job_limits", {}),
        "per_job_limits",
        allowed_keys={
            "nodes", "tasks", "cpus_per_task", "gpus", "gpus_per_node",
            "gpus_per_task", "array_tasks", "array_concurrency", "wall_seconds",
            "memory_mib", "memory_per_cpu_mib",
        },
    )
    budget = _positive_ints(
        raw.get("budget", {}),
        "budget",
        allowed_keys={
            "max_submissions", "max_active_jobs", "max_total_nodes",
            "max_total_tasks", "max_total_cpus_per_task", "max_total_gpus",
            "max_total_gpus_per_node", "max_total_gpus_per_task",
            "max_total_array_tasks", "max_total_array_concurrency",
            "max_total_wall_seconds", "max_total_memory_mib",
            "max_total_memory_per_cpu_mib",
        },
    )
    credit_budget = _credit_budget(raw.get("credit_budget"))
    lifecycle = _lifecycle_policy(raw.get("lifecycle"))

    return DelegationManifest(
        identifier=identifier,
        issuer=_string(raw, "issuer"),
        profile=profile,
        parent_job_id=parent,
        issued_at=issued,
        expires_at=expires,
        allowed=allowed,
        per_job_limits=per_job_limits,
        budget=budget,
        credit_budget=credit_budget,
        network=network,
        filesystem=filesystem,
        lifecycle=lifecycle,
        source_path=path,
        digest=hashlib.sha256(payload).hexdigest(),
    )


def authorize_shape(manifest: DelegationManifest, shape: dict[str, Any]) -> None:
    if shape.get("profile") != manifest.profile:
        raise DelegationError("submission profile is outside the delegation")
    overrides = shape.get("overrides")
    if not isinstance(overrides, dict):
        raise DelegationError("submission shape has no overrides")
    _allow("account", overrides.get("account"), manifest.allowed["accounts"], required=True)
    _allow("cluster", overrides.get("cluster"), manifest.allowed["clusters"], required=True)
    _allow("partition", overrides.get("partition"), manifest.allowed["partitions"])
    _allow("qos", overrides.get("qos"), manifest.allowed["qos"])
    _allow("reservation", overrides.get("reservation"), manifest.allowed["reservations"])
    roots = manifest.allowed["roots"]
    if roots and not _under_roots(shape.get("directory"), roots):
        raise DelegationError("submission directory is outside allowed roots")
    boundary = shape.get("boundary")
    if boundary is not None:
        if not isinstance(boundary, dict):
            raise DelegationError("submission boundary must be an object")
        _allow(
            "container",
            boundary.get("container"),
            manifest.allowed["containers"],
            required=True,
        )
        script_digest = boundary.get("script_sha256")
        if not isinstance(script_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", script_digest
        ):
            raise DelegationError("submission boundary has no valid script SHA-256")
        approved_scripts = manifest.allowed["script_sha256"]
        if approved_scripts and script_digest not in approved_scripts:
            raise DelegationError("script_sha256 is outside the delegation")
    resources = shape_resources(overrides)
    for key, limit in manifest.per_job_limits.items():
        if resources.get(key, 0) > limit:
            raise SubmissionDenied(
                SubmissionDenialCode.RESOURCES,
                f"requested {key}={resources[key]} exceeds delegation limit {limit}",
                resource=key,
            )


def shape_resources(overrides: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for source, target in (
        ("nodes", "nodes"), ("ntasks", "tasks"),
        ("cpus_per_task", "cpus_per_task"), ("gpus", "gpus"),
        ("gpus_per_node", "gpus_per_node"), ("gpus_per_task", "gpus_per_task"),
    ):
        value = overrides.get(source)
        if value is not None:
            if not isinstance(value, str) or not value.isdigit() or int(value) < 1:
                raise DelegationError(f"delegation requires numeric {source}")
            result[target] = int(value)
    if overrides.get("array") is not None:
        array_tasks, array_concurrency = _array_shape(overrides["array"])
        result["array_tasks"] = array_tasks
        result["array_concurrency"] = array_concurrency
    if overrides.get("time") is not None:
        result["wall_seconds"] = _time_seconds(overrides["time"])
    if overrides.get("mem") is not None:
        result["memory_mib"] = _memory_mib(overrides["mem"])
    if overrides.get("mem_per_cpu") is not None:
        result["memory_per_cpu_mib"] = _memory_mib(overrides["mem_per_cpu"])
    return result


def budget_resources(overrides: dict[str, Any]) -> dict[str, int]:
    """Return cumulative requested resources, including every array element."""
    per_element = shape_resources(overrides)
    multiplier = per_element.get("array_tasks", 1)
    cumulative = dict(per_element)
    cumulative["nodes"] = per_element.get("nodes", 1) * multiplier
    cumulative["tasks"] = per_element.get("tasks", 1) * multiplier
    for key in (
        "cpus_per_task", "gpus", "gpus_per_node", "gpus_per_task",
        "wall_seconds", "memory_mib", "memory_per_cpu_mib",
    ):
        if key in per_element:
            cumulative[key] = per_element[key] * multiplier
    return cumulative


class DelegationLedger:
    """Server-owned authorization, ownership, budget, and audit database."""

    def __init__(self, path: Path):
        self.path = path.expanduser()

    def register(self, manifest: DelegationManifest) -> None:
        with self._transaction() as db:
            row = db.execute(
                """SELECT manifest_sha256,revoked_at,network_mode
                   FROM delegations WHERE delegation_id=?""",
                (manifest.identifier,),
            ).fetchone()
            if row and row[0] != manifest.digest:
                raise DelegationError("delegation id is registered with different contents")
            if row and row[1]:
                raise DelegationError("delegation is revoked")
            if row and row[2] != manifest.network.mode.value:
                raise DelegationError("delegation network mode does not match the ledger")
            if not row:
                db.execute(
                    """INSERT INTO delegations
                       (delegation_id,manifest_sha256,issuer,profile,parent_job_id,
                        issued_at,expires_at,network_mode,manifest_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        manifest.identifier, manifest.digest, manifest.issuer,
                        manifest.profile, manifest.parent_job_id, manifest.issued_at,
                        manifest.expires_at, manifest.network.mode.value,
                        json.dumps(manifest.public_summary(), sort_keys=True),
                    ),
                )
                self._audit(
                    db,
                    manifest.identifier,
                    "register",
                    "accepted",
                    {"network": manifest.network.public_summary()},
                )
            attempt = db.execute(
                """SELECT 1 FROM controller_attempts
                   WHERE delegation_id=? LIMIT 1""",
                (manifest.identifier,),
            ).fetchone()
            if not attempt:
                now = _now()
                db.execute(
                    """INSERT INTO controller_attempts
                       (delegation_id,generation,parent_job_id,restart_count,state,
                        reconciliation_required,started_at,updated_at)
                       VALUES (?,1,?,0,'running',0,?,?)""",
                    (manifest.identifier, manifest.parent_job_id, now, now),
                )
                self._audit(
                    db,
                    manifest.identifier,
                    "controller_start",
                    "accepted",
                    {"generation": 1, "restart_count": 0},
                )

    def capture_controller_authority(
        self,
        manifest: DelegationManifest,
        *,
        policy: CapabilityPolicy,
        config_path: str | Path,
        config_sha256: str,
        quote_format: str | None = None,
    ) -> ControllerAuthority:
        """Capture the first authorized profile policy; never widen it later."""
        require_controller_authority(policy, operation="agent.controller.start")
        policy_value = policy.public_summary()
        policy_json = json.dumps(
            policy_value,
            sort_keys=True,
            separators=(",", ":"),
        )
        policy_sha256 = hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", config_sha256):
            raise DelegationError(
                "controller config digest must be lowercase SHA-256"
            )
        detail = {
            "policy": policy_value,
            "policy_sha256": policy_sha256,
            "config_path": str(Path(config_path).expanduser()),
            "config_sha256": config_sha256,
            "credit_budget": (
                manifest.credit_budget.public_summary()
                if manifest.credit_budget is not None
                else None
            ),
            "quote_format": quote_format,
            "network": manifest.network.public_summary(),
        }
        with self._transaction() as db:
            self._registered(db, manifest)
            existing = self._controller_authority_row(db, manifest.identifier)
            if existing is None:
                captured_at = _now()
                db.execute(
                    """INSERT INTO delegation_audit
                       (delegation_id,occurred_at,operation,decision,detail_json)
                       VALUES (?,?,?,?,?)""",
                    (
                        manifest.identifier,
                        captured_at,
                        "controller_authority",
                        "accepted",
                        json.dumps(detail, sort_keys=True, separators=(",", ":")),
                    ),
                )
                return _controller_authority(detail, captured_at, manifest)
            return _controller_authority(
                json.loads(existing[1]),
                existing[0],
                manifest,
            )

    def controller_authority_or_none(
        self,
        manifest: DelegationManifest,
    ) -> ControllerAuthority | None:
        with self._connection() as db:
            self._registered(db, manifest)
            row = self._controller_authority_row(db, manifest.identifier)
        if row is None:
            return None
        try:
            detail = json.loads(row[1])
        except (TypeError, json.JSONDecodeError) as error:
            raise DelegationError("captured controller authority is malformed") from error
        return _controller_authority(detail, row[0], manifest)

    def controller_authority(
        self,
        manifest: DelegationManifest,
    ) -> ControllerAuthority:
        authority = self.controller_authority_or_none(manifest)
        if authority is None:
            raise DelegationError("delegation has no captured controller authority")
        return authority

    @staticmethod
    def _controller_authority_row(
        db: sqlite3.Connection,
        delegation_id: str,
    ) -> tuple[str, str] | None:
        return db.execute(
            """SELECT occurred_at,detail_json FROM delegation_audit
               WHERE delegation_id=? AND operation='controller_authority'
                 AND decision='accepted'
               ORDER BY sequence LIMIT 1""",
            (delegation_id,),
        ).fetchone()

    def begin_controller(
        self,
        manifest: DelegationManifest,
        *,
        restart_count: int,
    ) -> dict[str, Any]:
        """Attach to the current attempt or begin a verified requeue attempt."""
        if restart_count < 0:
            raise DelegationError("controller restart count cannot be negative")
        with self._transaction() as db:
            self._active(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None:
                raise DelegationError("delegation has no controller state")
            if restart_count == row[1]:
                return self._controller_dict(row)
            if restart_count < row[1]:
                raise DelegationError("controller restart count moved backwards")
            if restart_count != row[1] + 1:
                raise DelegationError("controller restart count skipped a generation")
            if row[2] not in {"continuation-pending", "requeue-requested"}:
                raise DelegationError(
                    f"controller cannot restart from state {row[2]!r}"
                )
            if restart_count > manifest.lifecycle.max_requeues:
                raise DelegationError("controller requeue limit is exhausted")
            now = _now()
            generation = row[0] + 1
            db.execute(
                """INSERT INTO controller_attempts
                   (delegation_id,generation,parent_job_id,restart_count,state,
                    reconciliation_required,started_at,updated_at)
                   VALUES (?,?,?,?, 'reconciling',1,?,?)""",
                (
                    manifest.identifier,
                    generation,
                    manifest.parent_job_id,
                    restart_count,
                    now,
                    now,
                ),
            )
            self._audit(
                db,
                manifest.identifier,
                "controller_restart",
                "accepted",
                {"generation": generation, "restart_count": restart_count},
            )
            return self._controller_dict(
                (generation, restart_count, "reconciling", 1, None, now, now)
            )

    def controller_summary(self, manifest: DelegationManifest) -> dict[str, Any]:
        with self._connection() as db:
            self._active(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None:
                raise DelegationError("delegation has no controller state")
            result = self._controller_dict(row)
            cleanup = db.execute(
                """SELECT job_id,status,last_error,updated_at
                   FROM controller_cleanup WHERE delegation_id=?""",
                (manifest.identifier,),
            ).fetchone()
        result["cleanup"] = (
            {
                "job_id": cleanup[0],
                "status": cleanup[1],
                "last_error": cleanup[2],
                "updated_at": cleanup[3],
            }
            if cleanup
            else {"job_id": None, "status": "unconfigured", "last_error": None}
        )
        return result

    def controller_summary_for_cleanup(
        self, manifest: DelegationManifest
    ) -> dict[str, Any]:
        """Return controller state without requiring an unexpired delegation."""
        with self._connection() as db:
            self._registered(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
        if row is None:
            raise DelegationError("delegation has no controller state")
        return self._controller_dict(row)

    def record_controller_artifacts(
        self,
        manifest: DelegationManifest,
        *,
        generation: int,
        artifact_directory: str,
        provenance_path: str,
        event_log: str,
        diagnostic_log: str,
    ) -> None:
        """Record protected provenance and log paths for one controller attempt."""
        with self._transaction() as db:
            self._registered(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None or row[0] != generation:
                current = None if row is None else row[0]
                raise DelegationError(
                    f"controller artifact generation {generation} does not match {current}"
                )
            self._audit(
                db,
                manifest.identifier,
                "controller_artifacts",
                "accepted",
                {
                    "generation": generation,
                    "artifact_directory": artifact_directory,
                    "provenance_path": provenance_path,
                    "event_log": event_log,
                    "diagnostic_log": diagnostic_log,
                },
            )

    def begin_draining(self, manifest: DelegationManifest, *, reason: str) -> dict[str, Any]:
        with self._transaction() as db:
            self._active(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None or row[2] not in {"running", "reconciling", "draining"}:
                state = None if row is None else row[2]
                raise DelegationError(f"controller cannot drain from state {state!r}")
            if row[2] != "draining":
                db.execute(
                    """UPDATE controller_attempts SET state='draining',reason=?,updated_at=?
                       WHERE delegation_id=? AND generation=?""",
                    (reason, _now(), manifest.identifier, row[0]),
                )
                self._audit(
                    db,
                    manifest.identifier,
                    "controller_drain",
                    "accepted",
                    {"generation": row[0], "reason": reason},
                )
            return self._controller_dict(
                (row[0], row[1], "draining", row[3], reason, row[5], _now())
            )

    def request_requeue(self, manifest: DelegationManifest) -> dict[str, Any]:
        with self._transaction() as db:
            self._active(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None or row[2] not in {"draining", "requeue-requested"}:
                state = None if row is None else row[2]
                raise DelegationError(f"controller cannot requeue from state {state!r}")
            if row[1] >= manifest.lifecycle.max_requeues:
                raise DelegationError("controller requeue limit is exhausted")
            if row[2] != "requeue-requested":
                db.execute(
                    """UPDATE controller_attempts
                       SET state='requeue-requested',updated_at=?
                       WHERE delegation_id=? AND generation=?""",
                    (_now(), manifest.identifier, row[0]),
                )
                self._audit(
                    db,
                    manifest.identifier,
                    "controller_requeue",
                    "requested",
                    {"generation": row[0], "restart_count": row[1]},
                )
            return {"generation": row[0], "restart_count": row[1]}

    def record_requeue_result(
        self,
        manifest: DelegationManifest,
        *,
        accepted: bool,
        detail: str = "",
    ) -> None:
        state = "continuation-pending" if accepted else "final"
        with self._transaction() as db:
            self._registered(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None or row[2] not in {"requeue-requested", state}:
                current = None if row is None else row[2]
                raise DelegationError(
                    f"controller cannot record requeue result from state {current!r}"
                )
            db.execute(
                """UPDATE controller_attempts SET state=?,reason=?,updated_at=?
                   WHERE delegation_id=? AND generation=?""",
                (state, detail or None, _now(), manifest.identifier, row[0]),
            )
            self._audit(
                db,
                manifest.identifier,
                "controller_requeue",
                "accepted" if accepted else "failed",
                {"generation": row[0], "detail": detail},
            )

    def complete_reconciliation(self, manifest: DelegationManifest) -> None:
        with self._transaction() as db:
            self._active(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None or row[2] not in {"reconciling", "running"}:
                state = None if row is None else row[2]
                raise DelegationError(
                    f"controller cannot reconcile from state {state!r}"
                )
            db.execute(
                """UPDATE controller_attempts
                   SET state='running',reconciliation_required=0,updated_at=?
                   WHERE delegation_id=? AND generation=?""",
                (_now(), manifest.identifier, row[0]),
            )
            self._audit(
                db,
                manifest.identifier,
                "controller_reconcile",
                "accepted",
                {"generation": row[0]},
            )

    def finalize_controller(
        self,
        manifest: DelegationManifest,
        *,
        reason: str,
    ) -> None:
        with self._transaction() as db:
            self._registered(db, manifest)
            row = self._latest_controller(db, manifest.identifier)
            if row is None:
                raise DelegationError("delegation has no controller state")
            db.execute(
                """UPDATE controller_attempts SET state='final',reason=?,updated_at=?
                   WHERE delegation_id=? AND generation=?""",
                (reason, _now(), manifest.identifier, row[0]),
            )
            self._audit(
                db,
                manifest.identifier,
                "controller_finalize",
                "accepted",
                {"generation": row[0], "reason": reason},
            )

    def record_cleanup_job(self, manifest: DelegationManifest, *, job_id: str) -> None:
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            self._active(db, manifest)
            row = db.execute(
                "SELECT job_id FROM controller_cleanup WHERE delegation_id=?",
                (manifest.identifier,),
            ).fetchone()
            if row and row[0] != job_id:
                raise DelegationError("delegation already has a different cleanup job")
            db.execute(
                """INSERT INTO controller_cleanup
                   (delegation_id,job_id,status,updated_at)
                   VALUES (?,?,'pending',?)
                   ON CONFLICT(delegation_id) DO UPDATE SET updated_at=excluded.updated_at""",
                (manifest.identifier, job_id, _now()),
            )
            self._audit(
                db,
                manifest.identifier,
                "cleanup_register",
                "accepted",
                {"job_id": job_id},
            )

    def cleanup_job_id(self, manifest: DelegationManifest) -> str | None:
        with self._connection() as db:
            self._registered(db, manifest)
            row = db.execute(
                "SELECT job_id FROM controller_cleanup WHERE delegation_id=?",
                (manifest.identifier,),
            ).fetchone()
        return row[0] if row else None

    def record_cleanup_status(
        self,
        manifest: DelegationManifest,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        if status not in {"pending", "running", "succeeded", "failed", "preserved"}:
            raise DelegationError(f"unsupported cleanup status {status!r}")
        with self._transaction() as db:
            self._registered(db, manifest)
            changed = db.execute(
                """UPDATE controller_cleanup SET status=?,last_error=?,updated_at=?
                   WHERE delegation_id=?""",
                (status, error, _now(), manifest.identifier),
            ).rowcount
            if changed != 1:
                raise DelegationError("delegation has no registered cleanup job")
            self._audit(
                db,
                manifest.identifier,
                "cleanup_result",
                status,
                {"error": error},
            )

    def owned_jobs_for_cleanup(self, manifest: DelegationManifest) -> list[dict[str, str]]:
        """Return active owned jobs even after delegation expiry or revocation."""
        with self._connection() as db:
            self._registered(db, manifest)
            rows = db.execute(
                """SELECT ownership.job_id,ownership.cluster,operations.status
                   FROM job_ownership AS ownership
                   JOIN submission_operations AS operations
                     ON operations.delegation_id=ownership.delegation_id
                    AND operations.idempotency_key=ownership.idempotency_key
                   WHERE ownership.delegation_id=? AND operations.status != 'terminal'
                   ORDER BY ownership.created_at,ownership.job_id""",
                (manifest.identifier,),
            ).fetchall()
        return [
            {"job_id": row[0], "cluster": row[1], "status": row[2]}
            for row in rows
        ]

    def inflight_submission_count(self, manifest: DelegationManifest) -> int:
        """Return scheduler submissions reserved before a controller drain."""
        with self._connection() as db:
            self._registered(db, manifest)
            row = db.execute(
                """SELECT COUNT(*) FROM submission_operations
                   WHERE delegation_id=? AND status='reserved'""",
                (manifest.identifier,),
            ).fetchone()
        return int(row[0])

    def reserve_cleanup_cancellation(
        self,
        manifest: DelegationManifest,
        *,
        job_id: str,
        cluster: str | None,
    ) -> tuple[str, dict[str, Any]]:
        base_job_id = normalize_job_id(job_id)
        identity = f"{manifest.identifier}\0{base_job_id}\0{cluster or ''}"
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        key_prefix = f"parent-cleanup:{digest}:"
        with self._transaction() as db:
            self._registered(db, manifest)
            owned = db.execute(
                """SELECT 1 FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, base_job_id, cluster or ""),
            ).fetchone()
            if not owned:
                raise DelegationError("cleanup cannot cancel a job outside the delegation")
            rows = db.execute(
                """SELECT idempotency_key,status,result_json
                   FROM lifecycle_operations
                   WHERE delegation_id=? AND idempotency_key LIKE ?
                   ORDER BY created_at,idempotency_key""",
                (manifest.identifier, f"{key_prefix}%"),
            ).fetchall()
            if rows and (
                rows[-1][1] != "failed" or len(rows) >= CLEANUP_CANCEL_ATTEMPTS
            ):
                return rows[-1][0], {
                    "idempotent_replay": True,
                    "status": rows[-1][1],
                    "result": json.loads(rows[-1][2]) if rows[-1][2] else None,
                }
            attempt = len(rows) + 1
            key = f"{key_prefix}{attempt}"
            validate_idempotency_key(key)
            now = _now()
            db.execute(
                """INSERT INTO lifecycle_operations
                   (delegation_id,idempotency_key,operation,job_id,cluster,status,
                    created_at,updated_at)
                   VALUES (?,?,?,?,?,'reserved',?,?)""",
                (
                    manifest.identifier,
                    key,
                    "cancel",
                    base_job_id,
                    cluster or "",
                    now,
                    now,
                ),
            )
            self._audit(
                db,
                manifest.identifier,
                "parent_cleanup_cancel",
                "accepted",
                {"job_id": base_job_id, "cluster": cluster, "attempt": attempt},
            )
            return key, {
                "idempotent_replay": False,
                "status": "reserved",
                "result": None,
            }

    def reserve_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        shape: dict[str, Any],
        quoted_credit: QuotedCreditReservation | None = None,
    ) -> dict[str, Any]:
        try:
            return self._reserve_submission(
                manifest,
                idempotency_key=idempotency_key,
                shape=shape,
                quoted_credit=quoted_credit,
            )
        except DelegationError as error:
            self.record_rejection(
                manifest,
                operation="reserve_submission",
                detail={"idempotency_key": idempotency_key, "reason": str(error)},
            )
            raise

    def _reserve_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        shape: dict[str, Any],
        quoted_credit: QuotedCreditReservation | None,
    ) -> dict[str, Any]:
        validate_idempotency_key(idempotency_key)
        authorize_shape(manifest, shape)
        credit = _reservation_credit(manifest, quoted_credit)
        request = {"shape": shape}
        if credit is not None:
            request["quoted_credit"] = credit
        request_hash = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        requested = budget_resources(shape["overrides"])
        with self._transaction() as db:
            self._active(db, manifest)
            self._require_submission_allowed(db, manifest)
            row = db.execute(
                """SELECT request_sha256,status,job_id,cluster FROM submission_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if row:
                if row[0] != request_hash:
                    raise DelegationError("idempotency key was used for a different request")
                self._audit(
                    db,
                    manifest.identifier,
                    "reserve_submission",
                    "accepted",
                    {"idempotency_key": idempotency_key, "idempotent_replay": True},
                )
                return {
                    "idempotent_replay": True,
                    "status": row[1],
                    "job_id": row[2],
                    "cluster": row[3],
                }
            if credit is not None:
                identity_row = db.execute(
                    """SELECT idempotency_key FROM submission_operations
                       WHERE delegation_id=? AND quote_evidence_token=?""",
                    (
                        manifest.identifier,
                        credit["quote_evidence_token"],
                    ),
                ).fetchone()
                if identity_row is not None:
                    raise DelegationError(
                        "quoted-credit evidence identity was already reserved"
                    )
            if credit is not None and _parse_time(
                str(credit["quote_expires_at"])
            ) <= _utc_now():
                raise SubmissionDenied(
                    SubmissionDenialCode.QUOTE_EXPIRED,
                    "quoted-credit reservation has expired; quote and validate again",
                )
            used, active, totals, quoted_total = self._usage(
                db,
                manifest,
            )
            self._check_budget(
                manifest,
                used,
                active,
                totals,
                requested,
                quoted_cost=(
                    int(credit["quoted_cost"]["value"])
                    if credit is not None
                    else None
                ),
                quoted_total=quoted_total,
            )
            now = _now()
            db.execute(
                """INSERT INTO submission_operations
                   (delegation_id,idempotency_key,request_sha256,status,
                    resource_json,quoted_cost_value,quoted_cost_scale,
                    quoted_cost_unit,quote_evidence_token,quote_expires_at,
                    created_at,updated_at)
                   VALUES (?,?,?,'reserved',?,?,?,?,?,?,?,?)""",
                (
                    manifest.identifier, idempotency_key, request_hash,
                    json.dumps(requested, sort_keys=True),
                    credit["quoted_cost"]["value"] if credit is not None else None,
                    credit["quoted_cost"]["scale"] if credit is not None else None,
                    credit["quoted_cost"]["unit"] if credit is not None else None,
                    credit["quote_evidence_token"] if credit is not None else None,
                    credit["quote_expires_at"] if credit is not None else None,
                    now,
                    now,
                ),
            )
            audit_detail: dict[str, Any] = {
                "idempotency_key": idempotency_key,
                "resources": requested,
            }
            if credit is not None:
                audit_detail["quoted_credit"] = credit
            self._audit(
                db,
                manifest.identifier,
                "reserve_submission",
                "accepted",
                audit_detail,
            )
            return {
                "idempotent_replay": False,
                "status": "reserved",
                "job_id": None,
                "cluster": None,
            }

    def record_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        job_id: str,
        cluster: str | None,
        output_directory: str | None = None,
    ) -> None:
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            self._active(db, manifest)
            row = db.execute(
                """SELECT status,job_id FROM submission_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if not row:
                raise DelegationError("submission has no ledger reservation")
            if row[0] == "submitted" and row[1] == job_id:
                return
            if row[0] != "reserved":
                raise DelegationError(f"cannot submit operation in state {row[0]!r}")
            db.execute(
                """UPDATE submission_operations
                   SET status='submitted',job_id=?,cluster=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?""",
                (job_id, cluster, _now(), manifest.identifier, idempotency_key),
            )
            db.execute(
                """INSERT INTO job_ownership
                   (delegation_id,job_id,cluster,idempotency_key,created_at)
                   VALUES (?,?,?,?,?)""",
                (manifest.identifier, job_id, cluster or "", idempotency_key, _now()),
            )
            self._audit(
                db, manifest.identifier, "record_submission", "accepted",
                {
                    "idempotency_key": idempotency_key,
                    "job_id": job_id,
                    "cluster": cluster,
                    "output_directory": output_directory,
                },
            )

    def record_accepted_submission_uncertain(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        job_id: str,
        cluster: str | None,
        reason: str,
    ) -> None:
        """Fail closed after Slurm accepted a job but normal persistence failed.

        This deliberately omits the audit insert: it is the recovery path for a
        failed ledger/audit transaction. Ownership and consumed budget are more
        important than pretending the audit record was durable.
        """
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            self._registered(db, manifest)
            row = db.execute(
                """SELECT status,job_id FROM submission_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if not row:
                raise DelegationError("submission has no ledger reservation")
            if row[0] not in {"reserved", "uncertain"}:
                raise DelegationError(
                    f"cannot recover submission operation in state {row[0]!r}"
                )
            if row[1] not in {None, job_id}:
                raise DelegationError("submission recovery conflicts with recorded job ID")
            db.execute(
                """UPDATE submission_operations
                   SET status='uncertain',job_id=?,cluster=?,error=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?""",
                (
                    job_id, cluster, reason, _now(), manifest.identifier,
                    idempotency_key,
                ),
            )
            db.execute(
                """INSERT OR IGNORE INTO job_ownership
                   (delegation_id,job_id,cluster,idempotency_key,created_at)
                   VALUES (?,?,?,?,?)""",
                (
                    manifest.identifier, job_id, cluster or "", idempotency_key,
                    _now(),
                ),
            )
            owned = db.execute(
                """SELECT idempotency_key FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, job_id, cluster or ""),
            ).fetchone()
            if not owned or owned[0] != idempotency_key:
                raise DelegationError("submission recovery could not record job ownership")

    def release_reservation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        reason: str,
        uncertain: bool = False,
    ) -> None:
        status = "uncertain" if uncertain else "failed"
        with self._transaction() as db:
            db.execute(
                """UPDATE submission_operations SET status=?,error=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=? AND status='reserved'""",
                (status, reason, _now(), manifest.identifier, idempotency_key),
            )
            self._audit(
                db, manifest.identifier, "submission_result", status,
                {"idempotency_key": idempotency_key, "reason": reason},
            )

    def record_rejection(
        self,
        manifest: DelegationManifest,
        *,
        operation: str,
        detail: dict[str, Any],
    ) -> None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT manifest_sha256 FROM delegations WHERE delegation_id=?",
                (manifest.identifier,),
            ).fetchone()
            if not row or row[0] != manifest.digest:
                raise DelegationError("delegation is not registered with this ledger")
            self._audit(db, manifest.identifier, operation, "rejected", detail)

    def reconcile_job(
        self,
        manifest: DelegationManifest,
        *,
        job_id: str,
        cluster: str | None,
        state: str,
    ) -> None:
        terminal = {
            "BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE", "FAILED",
            "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "REVOKED", "TIMEOUT",
        }
        state_parts = state.split("+", 1)[0].strip().upper().split(maxsplit=1)
        normalized = state_parts[0] if state_parts else ""
        if normalized not in terminal:
            return
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            row = db.execute(
                """SELECT idempotency_key FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, job_id, cluster or ""),
            ).fetchone()
            if not row:
                raise DelegationError("cannot reconcile a job outside the delegation")
            db.execute(
                """UPDATE submission_operations SET status='terminal',updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?
                     AND status IN ('submitted','uncertain')""",
                (_now(), manifest.identifier, row[0]),
            )
            self._audit(
                db, manifest.identifier, "reconcile_job", "accepted",
                {"job_id": job_id, "cluster": cluster, "state": normalized},
            )

    def owned_jobs(
        self,
        manifest: DelegationManifest,
        *,
        include_terminal: bool = False,
    ) -> list[dict[str, str]]:
        with self._connection() as db:
            self._active(db, manifest)
            terminal_filter = "" if include_terminal else "AND operations.status != 'terminal'"
            rows = db.execute(
                f"""SELECT ownership.job_id,ownership.cluster,operations.status
                    FROM job_ownership AS ownership
                    JOIN submission_operations AS operations
                      ON operations.delegation_id=ownership.delegation_id
                     AND operations.idempotency_key=ownership.idempotency_key
                    WHERE ownership.delegation_id=? {terminal_filter}
                    ORDER BY ownership.created_at,ownership.job_id""",
                (manifest.identifier,),
            ).fetchall()
        return [
            {"job_id": row[0], "cluster": row[1], "status": row[2]}
            for row in rows
        ]

    def require_ownership(
        self,
        manifest: DelegationManifest,
        *,
        job_id: str,
        cluster: str | None,
    ) -> str:
        base_job_id = normalize_job_id(job_id)
        with self._connection() as db:
            self._active(db, manifest)
            row = db.execute(
                """SELECT 1 FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, base_job_id, cluster or ""),
            ).fetchone()
        if not row:
            self.record_rejection(
                manifest,
                operation="job_ownership",
                detail={"job_id": job_id, "cluster": cluster},
            )
            raise DelegationError(
                f"job {job_id!r} on cluster {cluster!r} is outside the delegation"
            )
        return base_job_id

    def reserve_lifecycle_operation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        operation: str,
        job_id: str,
        cluster: str | None,
    ) -> dict[str, Any]:
        try:
            return self._reserve_lifecycle_operation(
                manifest,
                idempotency_key=idempotency_key,
                operation=operation,
                job_id=job_id,
                cluster=cluster,
            )
        except DelegationError as error:
            self.record_rejection(
                manifest,
                operation=operation,
                detail={
                    "idempotency_key": idempotency_key,
                    "job_id": job_id,
                    "cluster": cluster,
                    "reason": str(error),
                },
            )
            raise

    def _reserve_lifecycle_operation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        operation: str,
        job_id: str,
        cluster: str | None,
    ) -> dict[str, Any]:
        if operation != "cancel":
            raise DelegationError(f"unsupported lifecycle mutation {operation!r}")
        validate_idempotency_key(idempotency_key)
        base_job_id = self.require_ownership(
            manifest, job_id=job_id, cluster=cluster
        )
        with self._transaction() as db:
            row = db.execute(
                """SELECT operation,job_id,cluster,status,result_json
                   FROM lifecycle_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if row:
                if (row[0], row[1], row[2]) != (
                    operation, base_job_id, cluster or ""
                ):
                    raise DelegationError(
                        "lifecycle idempotency key was used for a different operation"
                    )
                self._audit(
                    db, manifest.identifier, operation, "accepted",
                    {"idempotency_key": idempotency_key, "idempotent_replay": True},
                )
                return {
                    "idempotent_replay": True,
                    "status": row[3],
                    "result": json.loads(row[4]) if row[4] else None,
                }
            db.execute(
                """INSERT INTO lifecycle_operations
                   (delegation_id,idempotency_key,operation,job_id,cluster,status,
                    created_at,updated_at)
                   VALUES (?,?,?,?,?,'reserved',?,?)""",
                (
                    manifest.identifier, idempotency_key, operation,
                    base_job_id, cluster or "", _now(), _now(),
                ),
            )
            self._audit(
                db, manifest.identifier, operation, "accepted",
                {
                    "idempotency_key": idempotency_key,
                    "job_id": job_id,
                    "cluster": cluster,
                },
            )
            return {"idempotent_replay": False, "status": "reserved", "result": None}

    def record_lifecycle_result(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        succeeded: bool,
        result: dict[str, Any],
    ) -> None:
        status = "succeeded" if succeeded else "failed"
        with self._transaction() as db:
            changed = db.execute(
                """UPDATE lifecycle_operations
                   SET status=?,result_json=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?
                     AND status IN ('reserved','uncertain')""",
                (
                    status,
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    _now(),
                    manifest.identifier,
                    idempotency_key,
                ),
            ).rowcount
            if changed != 1:
                raise DelegationError("lifecycle operation has no active reservation")
            self._audit(
                db, manifest.identifier, "lifecycle_result", status,
                {"idempotency_key": idempotency_key, "result": result},
            )

    def record_accepted_lifecycle_uncertain(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        result: dict[str, Any],
        reason: str,
    ) -> None:
        """Persist a non-replayable recovery state without relying on audit."""
        recovery_result = dict(result)
        recovery_result["persistence_error"] = reason
        with self._transaction() as db:
            self._registered(db, manifest)
            changed = db.execute(
                """UPDATE lifecycle_operations
                   SET status='uncertain',result_json=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?
                     AND status IN ('reserved','uncertain')""",
                (
                    json.dumps(
                        recovery_result, sort_keys=True, separators=(",", ":")
                    ),
                    _now(), manifest.identifier, idempotency_key,
                ),
            ).rowcount
            if changed != 1:
                raise DelegationError("lifecycle operation has no active reservation")

    def owns_job(self, delegation_id: str, job_id: str, cluster: str | None) -> bool:
        base_job_id = normalize_job_id(job_id)
        with self._connection() as db:
            return db.execute(
                """SELECT 1 FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (delegation_id, base_job_id, cluster or ""),
            ).fetchone() is not None

    def summary(self, manifest: DelegationManifest) -> dict[str, Any]:
        with self._connection() as db:
            self._active(db, manifest)
            used, active, totals, quoted_total = self._usage(db, manifest)
        remaining = {}
        for key, limit in manifest.budget.items():
            consumed = (
                used if key == "max_submissions"
                else active if key == "max_active_jobs"
                else totals.get(key.removeprefix("max_total_"), 0)
            )
            remaining[key] = max(0, limit - consumed)
        quoted_credit: dict[str, Any] = {"configured": False}
        if manifest.credit_budget is not None:
            budget = manifest.credit_budget
            quoted_credit = {
                "configured": True,
                "consumed_quoted_maximum": {
                    "value": quoted_total,
                    "scale": budget.scale,
                    "unit": budget.unit,
                },
                "remaining_quoted_maximum": {
                    "value": max(0, budget.maximum_total - quoted_total),
                    "scale": budget.scale,
                    "unit": budget.unit,
                },
            }
        return {
            "used_submissions": used,
            "active_jobs": active,
            "requested_resources": totals,
            "remaining": remaining,
            "quoted_credit": quoted_credit,
        }

    def revoke(self, delegation_id: str, *, reason: str) -> None:
        with self._transaction() as db:
            count = db.execute(
                """UPDATE delegations SET revoked_at=?,revocation_reason=?
                   WHERE delegation_id=? AND revoked_at IS NULL""",
                (_now(), reason, delegation_id),
            ).rowcount
            if count != 1:
                raise DelegationError("unknown or already revoked delegation")
            self._audit(db, delegation_id, "revoke", "accepted", {"reason": reason})

    def _check_budget(
        self,
        manifest: DelegationManifest,
        used: int,
        active: int,
        totals: dict[str, int],
        requested: dict[str, int],
        *,
        quoted_cost: int | None,
        quoted_total: int,
    ) -> None:
        credit_budget = manifest.credit_budget
        if credit_budget is not None:
            if quoted_cost is None:
                raise SubmissionDenied(
                    SubmissionDenialCode.QUOTE_FORMAT,
                    "delegation requires a quoted-credit reservation",
                )
            if (
                credit_budget.maximum_per_job is not None
                and quoted_cost > credit_budget.maximum_per_job
            ):
                raise SubmissionDenied(
                    SubmissionDenialCode.PER_JOB_CREDIT,
                    "delegation per-job quoted-credit budget is exceeded",
                )
            if quoted_total + quoted_cost > credit_budget.maximum_total:
                raise SubmissionDenied(
                    SubmissionDenialCode.TOTAL_CREDITS,
                    "delegation total quoted-credit budget is exhausted",
                )
        if used >= manifest.budget.get("max_submissions", 2**63 - 1):
            raise SubmissionDenied(
                SubmissionDenialCode.SUBMISSION_COUNT,
                "delegation submission budget is exhausted",
            )
        if active >= manifest.budget.get("max_active_jobs", 2**63 - 1):
            raise SubmissionDenied(
                SubmissionDenialCode.ACTIVE_JOBS,
                "delegation active-job budget is exhausted",
            )
        for key, limit in manifest.budget.items():
            if key.startswith("max_total_"):
                resource = key.removeprefix("max_total_")
                if totals.get(resource, 0) + requested.get(resource, 0) > limit:
                    raise SubmissionDenied(
                        SubmissionDenialCode.RESOURCES,
                        f"delegation aggregate {resource} budget is exhausted",
                        resource=resource,
                    )

    def _usage(
        self,
        db: sqlite3.Connection,
        manifest: DelegationManifest,
    ) -> tuple[int, int, dict[str, int], int]:
        rows = db.execute(
            """SELECT status,resource_json,quoted_cost_value,quoted_cost_scale,
                      quoted_cost_unit,quote_evidence_token,quote_expires_at
               FROM submission_operations
               WHERE delegation_id=? AND status != 'failed'""",
            (manifest.identifier,),
        ).fetchall()
        totals: dict[str, int] = {}
        quoted_total = 0
        for (
            _,
            encoded,
            cost_value,
            cost_scale,
            cost_unit,
            evidence_token,
            quote_expires_at,
        ) in rows:
            for key, value in json.loads(encoded).items():
                totals[key] = totals.get(key, 0) + int(value)
            if manifest.credit_budget is None:
                if any(
                    value is not None
                    for value in (
                        cost_value,
                        cost_scale,
                        cost_unit,
                        evidence_token,
                        quote_expires_at,
                    )
                ):
                    raise DelegationError(
                        "resource-only delegation contains quoted-credit state"
                    )
                continue
            if (
                type(cost_value) is not int
                or not 0 <= cost_value <= MAX_CREDIT_VALUE
                or cost_scale != manifest.credit_budget.scale
                or cost_unit != manifest.credit_budget.unit
                or not isinstance(evidence_token, str)
                or not re.fullmatch(r"[0-9a-f]{64}", evidence_token)
                or not isinstance(quote_expires_at, str)
            ):
                raise DelegationError(
                    "credit delegation contains malformed quoted-credit state"
                )
            try:
                _parse_time(quote_expires_at)
            except DelegationError as error:
                raise DelegationError(
                    "credit delegation contains malformed quoted-credit state"
                ) from error
            quoted_total += cost_value
        used = len(rows)
        active = sum(
            row[0] in {"reserved", "submitted", "uncertain"}
            for row in rows
        )
        return used, active, totals, quoted_total

    def _active(self, db: sqlite3.Connection, manifest: DelegationManifest) -> None:
        row = db.execute(
            """SELECT manifest_sha256,expires_at,revoked_at,network_mode
               FROM delegations
               WHERE delegation_id=?""",
            (manifest.identifier,),
        ).fetchone()
        if not row or row[0] != manifest.digest:
            raise DelegationError("delegation is not registered with this ledger")
        if row[2]:
            raise DelegationError("delegation is revoked")
        if row[3] != manifest.network.mode.value:
            raise DelegationError("delegation network mode does not match the ledger")
        if _parse_time(row[1]) <= datetime.now(timezone.utc):
            raise DelegationError("delegation is expired")

    def _require_submission_allowed(
        self, db: sqlite3.Connection, manifest: DelegationManifest
    ) -> None:
        row = self._latest_controller(db, manifest.identifier)
        if row is None:
            raise DelegationError("delegation has no controller state")
        if row[2] != "running":
            raise DelegationError(
                f"delegated submission is blocked while controller is {row[2]!r}"
            )
        if row[3]:
            raise DelegationError(
                "delegated submission is blocked until startup reconciliation completes"
            )

    def _latest_controller(
        self, db: sqlite3.Connection, delegation_id: str
    ) -> tuple[int, int, str, int, str | None, str, str] | None:
        return db.execute(
            """SELECT generation,restart_count,state,reconciliation_required,
                      reason,started_at,updated_at
               FROM controller_attempts WHERE delegation_id=?
               ORDER BY generation DESC LIMIT 1""",
            (delegation_id,),
        ).fetchone()

    @staticmethod
    def _controller_dict(
        row: tuple[int, int, str, int, str | None, str, str]
    ) -> dict[str, Any]:
        return {
            "generation": row[0],
            "restart_count": row[1],
            "state": row[2],
            "reconciliation_required": bool(row[3]),
            "reason": row[4],
            "started_at": row[5],
            "updated_at": row[6],
        }

    def _registered(
        self, db: sqlite3.Connection, manifest: DelegationManifest
    ) -> None:
        row = db.execute(
            """SELECT manifest_sha256,network_mode FROM delegations
               WHERE delegation_id=?""",
            (manifest.identifier,),
        ).fetchone()
        if not row or row[0] != manifest.digest:
            raise DelegationError("delegation is not registered with this ledger")
        if row[1] != manifest.network.mode.value:
            raise DelegationError("delegation network mode does not match the ledger")

    def _audit(
        self,
        db: sqlite3.Connection,
        delegation_id: str,
        operation: str,
        decision: str,
        detail: dict[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO delegation_audit
               (delegation_id,occurred_at,operation,decision,detail_json)
               VALUES (?,?,?,?,?)""",
            (
                delegation_id, _now(), operation, decision,
                json.dumps(detail, sort_keys=True, separators=(",", ":")),
            ),
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        if not existed:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                existed = True
            else:
                os.close(descriptor)
        if self.path.is_symlink() or not self.path.is_file():
            raise DelegationError(
                f"delegation ledger must be a regular non-symlink file: {self.path}"
            )
        if os.name == "posix":
            stat = self.path.stat()
            if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                raise DelegationError(
                    f"delegation ledger must be server-owned with mode 0600: {self.path}"
                )
        db = sqlite3.connect(self.path, timeout=5.0)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            self._ensure_schema(db)
            yield db
        except sqlite3.Error as error:
            raise DelegationError(f"unable to use delegation ledger {self.path}: {error}") from error
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except Exception:
                db.rollback()
                raise
            else:
                db.commit()

    def _ensure_schema(self, db: sqlite3.Connection) -> None:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        schema_lock = version == 0
        if schema_lock:
            db.execute("BEGIN IMMEDIATE")
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            _execute_schema(db,
                """
                CREATE TABLE delegations (
                    delegation_id TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL, issuer TEXT NOT NULL,
                    profile TEXT NOT NULL, parent_job_id TEXT NOT NULL,
                    issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    network_mode TEXT NOT NULL CHECK (network_mode IN
                      ('model-only','model-indexed-search','model-live-search')),
                    manifest_json TEXT NOT NULL, revoked_at TEXT,
                    revocation_reason TEXT
                );
                CREATE TABLE submission_operations (
                    delegation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                    resource_json TEXT NOT NULL,
                    quoted_cost_value INTEGER, quoted_cost_scale INTEGER,
                    quoted_cost_unit TEXT, quote_evidence_token TEXT,
                    quote_expires_at TEXT, job_id TEXT, cluster TEXT,
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,idempotency_key),
                    UNIQUE (delegation_id,quote_evidence_token),
                    CHECK (
                      (quoted_cost_value IS NULL AND quoted_cost_scale IS NULL AND
                       quoted_cost_unit IS NULL AND quote_evidence_token IS NULL AND
                       quote_expires_at IS NULL) OR
                      (quoted_cost_value IS NOT NULL AND
                       quoted_cost_value BETWEEN 0 AND 9223372036854775807 AND
                       quoted_cost_scale IS NOT NULL AND
                       quoted_cost_scale BETWEEN 0 AND 9 AND
                       quoted_cost_unit IS NOT NULL AND
                       quote_evidence_token IS NOT NULL AND
                       quote_expires_at IS NOT NULL)
                    ),
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE TABLE job_ownership (
                    delegation_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    cluster TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,job_id,cluster),
                    UNIQUE (job_id,cluster),
                    FOREIGN KEY (delegation_id,idempotency_key)
                      REFERENCES submission_operations(delegation_id,idempotency_key)
                );
                CREATE TABLE lifecycle_operations (
                    delegation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    operation TEXT NOT NULL, job_id TEXT NOT NULL,
                    cluster TEXT NOT NULL, status TEXT NOT NULL,
                    result_json TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,idempotency_key),
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE TABLE delegation_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    delegation_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    operation TEXT NOT NULL, decision TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE INDEX delegation_audit_by_delegation
                  ON delegation_audit(delegation_id,sequence);
                CREATE TABLE controller_attempts (
                    delegation_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    parent_job_id TEXT NOT NULL, restart_count INTEGER NOT NULL,
                    state TEXT NOT NULL, reconciliation_required INTEGER NOT NULL,
                    reason TEXT, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,generation),
                    UNIQUE (delegation_id,restart_count),
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE TABLE controller_cleanup (
                    delegation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    status TEXT NOT NULL, last_error TEXT, updated_at TEXT NOT NULL,
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                """
            )
            db.execute(f"PRAGMA user_version={LEDGER_SCHEMA_VERSION}")
            version = LEDGER_SCHEMA_VERSION
        if schema_lock:
            db.commit()
        if version != LEDGER_SCHEMA_VERSION:
            raise DelegationError(
                f"unsupported delegation ledger schema version {version}; "
                f"expected {LEDGER_SCHEMA_VERSION}"
            )




_JOB_ID_PATTERN = re.compile(
    r"(?P<base>\d+)(?:\+\d+)?(?:_\d+)?(?:\.[A-Za-z0-9_-]+)?"
)


def normalize_job_id(job_id: str) -> str:
    match = _JOB_ID_PATTERN.fullmatch(job_id)
    if not match:
        raise DelegationError(
            "job ID must identify one numeric job, heterogeneous component, "
            "array task, or job step"
        )
    return match.group("base")


def validate_idempotency_key(value: str) -> None:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise DelegationError("invalid idempotency key")


def _controller_restart_count() -> int:
    value = os.environ.get(CONTROLLER_RESTART_ENV_VAR, "0")
    if not value.isdigit():
        raise DelegationError(
            f"{CONTROLLER_RESTART_ENV_VAR} must be a non-negative integer"
        )
    return int(value)

def _execute_schema(db: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            db.execute(statement)


def _controller_authority(
    detail: object,
    captured_at: str,
    manifest: DelegationManifest,
) -> ControllerAuthority:
    if not isinstance(detail, dict):
        raise DelegationError("captured controller authority is not an object")
    policy_value = detail.get("policy")
    try:
        policy = parse_capability_policy(
            policy_value,
            profile=f"captured controller {manifest.profile}",
        )
    except ValueError as error:
        raise DelegationError(
            f"captured controller policy is invalid: {error}"
        ) from error
    policy_json = json.dumps(
        policy.public_summary(),
        sort_keys=True,
        separators=(",", ":"),
    )
    calculated = hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
    policy_sha256 = detail.get("policy_sha256")
    config_path = detail.get("config_path")
    config_sha256 = detail.get("config_sha256")
    captured_credit_budget = _credit_budget(detail.get("credit_budget"))
    quote_format = detail.get("quote_format")
    if detail.get("network") != manifest.network.public_summary():
        raise DelegationError(
            "captured controller network policy does not match the delegation"
        )
    if calculated != policy_sha256:
        raise DelegationError("captured controller policy digest does not match")
    if not isinstance(config_path, str) or not config_path:
        raise DelegationError("captured controller config path is invalid")
    if not isinstance(config_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", config_sha256
    ):
        raise DelegationError("captured controller config digest is invalid")
    if captured_credit_budget != manifest.credit_budget:
        raise DelegationError(
            "captured controller credit budget does not match the delegation"
        )
    if quote_format is not None and quote_format != STRUCTURED_QUOTE_FORMAT_V1:
        raise DelegationError("captured controller quote format is invalid")
    if manifest.credit_budget is not None and quote_format is None:
        raise DelegationError("captured controller quote format is missing")
    return ControllerAuthority(
        policy=policy,
        policy_sha256=policy_sha256,
        config_path=config_path,
        config_sha256=config_sha256,
        credit_budget=captured_credit_budget,
        quote_format=quote_format,
        captured_at=captured_at,
    )


def _credit_budget(value: Any) -> CreditBudget | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DelegationError("credit_budget must be a table")
    known = {
        "unit",
        "scale",
        "maximum_total",
        "maximum_per_job",
        "quote_ttl_seconds",
    }
    _reject_unknown_keys(value, known, "credit_budget")
    required = {"unit", "scale", "maximum_total", "quote_ttl_seconds"}
    missing = sorted(required - set(value))
    if missing:
        raise DelegationError(
            f"credit_budget is missing field(s): {', '.join(missing)}"
        )

    unit = value["unit"]
    if not isinstance(unit, str) or not CREDIT_UNIT_PATTERN.fullmatch(unit):
        raise DelegationError(
            "credit_budget.unit must be a normalized lowercase ASCII identifier"
        )

    scale = _bounded_integer(
        value["scale"],
        "credit_budget.scale",
        minimum=0,
        maximum=MAX_CREDIT_SCALE,
    )
    maximum_total = _bounded_integer(
        value["maximum_total"],
        "credit_budget.maximum_total",
        minimum=1,
        maximum=MAX_CREDIT_VALUE,
    )
    maximum_per_job_value = value.get("maximum_per_job")
    maximum_per_job = None
    if maximum_per_job_value is not None:
        maximum_per_job = _bounded_integer(
            maximum_per_job_value,
            "credit_budget.maximum_per_job",
            minimum=1,
            maximum=MAX_CREDIT_VALUE,
        )
        if maximum_per_job > maximum_total:
            raise DelegationError(
                "credit_budget.maximum_per_job must not exceed maximum_total"
            )
    quote_ttl_seconds = _bounded_integer(
        value["quote_ttl_seconds"],
        "credit_budget.quote_ttl_seconds",
        minimum=1,
        maximum=86400,
    )
    return CreditBudget(
        unit=unit,
        scale=scale,
        maximum_total=maximum_total,
        maximum_per_job=maximum_per_job,
        quote_ttl_seconds=quote_ttl_seconds,
    )


def _bounded_integer(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DelegationError(
            f"{name} must be an integer from {minimum} to {maximum}"
        )
    return value

def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise DelegationError(f"delegation field {key!r} must be a non-empty string")
    return value


def _timestamp_field(data: dict[str, Any], key: str) -> str:
    value = _string(data, key)
    _parse_time(value)
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DelegationError(f"invalid delegation timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise DelegationError("delegation timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DelegationError("quoted-credit expiry must include a UTC offset")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _reservation_credit(
    manifest: DelegationManifest,
    quoted_credit: QuotedCreditReservation | None,
) -> dict[str, Any] | None:
    budget = manifest.credit_budget
    if budget is None:
        if quoted_credit is not None:
            raise DelegationError(
                "resource-only delegation does not accept quoted-credit state"
            )
        return None
    if not isinstance(quoted_credit, QuotedCreditReservation):
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            "delegation requires a quoted-credit reservation",
        )
    try:
        cost = parse_credit_amount(
            quoted_credit.cost.to_dict(),
            label="quoted-credit reservation cost",
        )
    except (AttributeError, CreditQuoteError) as error:
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            f"invalid quoted-credit reservation: {error}",
        ) from error
    if cost.unit != budget.unit:
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            "quoted-credit reservation unit does not match the delegation",
        )
    if cost.scale != budget.scale:
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            "quoted-credit reservation scale does not match the delegation",
        )
    if not isinstance(quoted_credit.evidence_token, str) or not re.fullmatch(
        r"[0-9a-f]{64}", quoted_credit.evidence_token
    ):
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            "quoted-credit evidence identity is invalid",
        )
    if not isinstance(quoted_credit.expires_at, datetime):
        raise SubmissionDenied(
            SubmissionDenialCode.QUOTE_FORMAT,
            "quoted-credit expiry must be a timestamp",
        )
    return {
        "quoted_cost": cost.to_dict(),
        "quote_evidence_token": quoted_credit.evidence_token,
        "quote_expires_at": _canonical_time(quoted_credit.expires_at),
    }


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise DelegationError(f"delegation field {key!r} must be a table")
    return value


def _strings(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DelegationError(f"allowed.{key} must be an array of strings")
    if len(set(value)) != len(value):
        raise DelegationError(f"allowed.{key} contains duplicates")
    return tuple(value)


def _positive_ints(
    value: Any,
    name: str,
    *,
    allowed_keys: set[str] | None = None,
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise DelegationError(f"{name} must be a table")
    if allowed_keys is not None:
        _reject_unknown_keys(value, allowed_keys, name)
    for key, item in value.items():
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise DelegationError(f"{name}.{key} must be a positive integer")
    return dict(value)


def _reject_unknown_keys(
    value: dict[str, Any], allowed: set[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DelegationError(f"unsupported {name} field(s): {', '.join(unknown)}")


def _network_policy(value: Any) -> AgentNetworkPolicy:
    if not isinstance(value, dict):
        raise DelegationError("network must be a table")
    _reject_unknown_keys(value, {"mode"}, "network")
    selected = value.get("mode")
    try:
        mode = AgentNetworkMode(selected)
    except (TypeError, ValueError) as error:
        choices = ", ".join(mode.value for mode in AgentNetworkMode)
        raise DelegationError(f"network.mode must be one of: {choices}") from error
    return AgentNetworkPolicy(mode=mode)


def _lifecycle_policy(value: Any) -> LifecyclePolicy:
    if value is None:
        return LifecyclePolicy()
    if not isinstance(value, dict):
        raise DelegationError("lifecycle must be a table")
    known = {
        "on_cancel",
        "on_timeout",
        "on_failure",
        "on_normal_exit_with_active_jobs",
        "max_requeues",
        "warning_seconds",
    }
    _reject_unknown_keys(value, known, "lifecycle")
    defaults = LifecyclePolicy()

    def action(name: str, allowed: set[str], default: str) -> str:
        selected = value.get(name, default)
        if not isinstance(selected, str) or selected not in allowed:
            choices = ", ".join(sorted(allowed))
            raise DelegationError(f"lifecycle.{name} must be one of: {choices}")
        return selected

    integers: dict[str, int] = {}
    bounds = {
        "max_requeues": (0, 100),
        "warning_seconds": (1, 65535),
    }
    for name, (minimum, maximum) in bounds.items():
        selected = value.get(name, getattr(defaults, name))
        if (
            not isinstance(selected, int)
            or isinstance(selected, bool)
            or not minimum <= selected <= maximum
        ):
            raise DelegationError(
                f"lifecycle.{name} must be an integer from {minimum} to {maximum}"
            )
        integers[name] = selected
    return LifecyclePolicy(
        on_cancel=action("on_cancel", {"cancel", "leave-running"}, defaults.on_cancel),
        on_timeout=action(
            "on_timeout",
            {"cancel", "leave-running", "requeue-or-cancel"},
            defaults.on_timeout,
        ),
        on_failure=action("on_failure", {"cancel", "leave-running"}, defaults.on_failure),
        on_normal_exit_with_active_jobs=action(
            "on_normal_exit_with_active_jobs",
            {"cancel", "leave-running"},
            defaults.on_normal_exit_with_active_jobs,
        ),
        **integers,
    )


def _filesystem_policy(value: Any) -> FilesystemPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DelegationError("filesystem must be a table")
    known = {
        "state_root", "work_root", "output_root", "input_roots",
        "apptainer_path", "max_file_blocks", "max_open_files",
    }
    unknown = sorted(set(value) - known)
    if unknown:
        raise DelegationError(
            f"unsupported filesystem field(s): {', '.join(unknown)}"
        )

    def absolute_path(name: str) -> Path:
        raw = value.get(name)
        if not isinstance(raw, str) or not raw:
            raise DelegationError(f"filesystem.{name} must be a non-empty string")
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise DelegationError(
                f"filesystem.{name} must be an absolute normalized path"
            )
        return path

    raw_inputs = value.get("input_roots", [])
    if not isinstance(raw_inputs, list) or not all(
        isinstance(item, str) and item for item in raw_inputs
    ):
        raise DelegationError("filesystem.input_roots must be an array of strings")
    input_roots: list[Path] = []
    for item in raw_inputs:
        path = Path(item)
        if not path.is_absolute() or ".." in path.parts:
            raise DelegationError(
                "filesystem.input_roots must contain absolute normalized paths"
            )
        input_roots.append(path)
    if len(set(input_roots)) != len(input_roots):
        raise DelegationError("filesystem.input_roots contains duplicates")

    limits = _positive_ints(
        {
            key: item
            for key, item in value.items()
            if key in {"max_file_blocks", "max_open_files"}
        },
        "filesystem",
    )
    policy = FilesystemPolicy(
        state_root=absolute_path("state_root"),
        work_root=absolute_path("work_root"),
        output_root=absolute_path("output_root"),
        input_roots=tuple(input_roots),
        apptainer_path=absolute_path("apptainer_path"),
        max_file_blocks=limits.get("max_file_blocks"),
        max_open_files=limits.get("max_open_files"),
    )
    roots = (policy.state_root, policy.work_root, policy.output_root, *policy.input_roots)
    for index, first in enumerate(roots):
        for second in roots[index + 1 :]:
            if _paths_overlap(first, second):
                raise DelegationError(
                    f"filesystem paths must not overlap: {first} and {second}"
                )
    for root in roots:
        if _paths_overlap(policy.apptainer_path, root):
            raise DelegationError(
                "filesystem.apptainer_path must be outside all container bind roots"
            )
    return policy


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _allow(
    name: str, value: Any, allowed: tuple[str, ...], *, required: bool = False
) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or value not in allowed:
        raise DelegationError(f"submission {name} {value!r} is outside the delegation")


def _under_roots(value: Any, roots: tuple[str, ...]) -> bool:
    if not isinstance(value, str) or "$" in value or "~" in value:
        return False
    path = Path(value)
    return path.is_absolute() and ".." not in path.parts and any(
        path == Path(root) or Path(root) in path.parents for root in roots
    )


def _array_shape(value: Any) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:-\d+)?(?:%\d+)?", value):
        raise DelegationError("only one numeric Slurm array range is supported")
    range_value, _, concurrency_value = value.partition("%")
    bounds = range_value.split("-", 1)
    if len(bounds) == 1:
        size = 1
    else:
        start, end = map(int, bounds)
        if end < start:
            raise DelegationError("Slurm array range is reversed")
        size = end - start + 1
    concurrency = int(concurrency_value) if concurrency_value else size
    if concurrency < 1:
        raise DelegationError("Slurm array concurrency must be positive")
    return size, min(size, concurrency)

def _time_seconds(value: Any) -> int:
    if not isinstance(value, str):
        raise DelegationError("time limit must be a string")
    match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
    if not match:
        raise DelegationError("time must use [days-]HH:MM:SS")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if minutes > 59 or seconds > 59:
        raise DelegationError("time has invalid minutes or seconds")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds



def _memory_mib(value: Any) -> int:
    if not isinstance(value, str):
        raise DelegationError("memory limit must be a string")
    match = re.fullmatch(r"(\d+)([KMGTP]?)", value, re.IGNORECASE)
    if not match or int(match.group(1)) < 1:
        raise DelegationError("memory must be a positive Slurm size using K, M, G, T, or P")
    amount = int(match.group(1))
    unit = match.group(2).upper() or "M"
    factors = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}
    return max(1, int(amount * factors[unit]))

def _now() -> str:
    return _utc_now().isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)
