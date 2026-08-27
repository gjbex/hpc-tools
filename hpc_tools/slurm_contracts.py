from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hpc_tools import slurm
from hpc_tools.config import ConfigError, Profile

_EVIDENCE_SECRET: bytes | None = None


@dataclass(frozen=True)
class SubmitOverrides:
    values: Mapping[str, str | None]

    @classmethod
    def from_values(
        cls,
        *,
        account: str | None = None,
        **overrides: str | None,
    ) -> SubmitOverrides:
        unknown = sorted(set(overrides) - set(slurm.SUBMIT_OPTION_NAMES))
        if unknown:
            raise ConfigError(f"unsupported submit override(s): {', '.join(unknown)}")
        normalized = {name: overrides.get(name) for name in slurm.SUBMIT_OPTION_NAMES}
        if account is not None:
            normalized["account"] = account
        return cls(normalized)

    @classmethod
    def from_namespace(cls, namespace: Any) -> SubmitOverrides:
        return cls(
            {
                name: getattr(namespace, name)
                for name in slurm.SUBMIT_OPTION_NAMES
            }
        )

    def to_dict(self, *, include_empty: bool = True) -> dict[str, str | None]:
        if include_empty:
            return dict(self.values)
        return {
            name: value
            for name, value in self.values.items()
            if value is not None
        }

    def quote_args(self, jobscript: str) -> list[str]:
        parts = ["sbatch"]
        for name, value in self.values.items():
            if value is None:
                continue
            parts.extend([slurm.SUBMIT_OPTION_NAMES[name], value])
        parts.append(jobscript)
        return parts

    def account(self) -> str | None:
        return self.values.get("account")


@dataclass(frozen=True)
class SubmissionShape:
    profile: str
    account: str | None
    jobscript: str
    directory: str
    overrides: Mapping[str, str]
    boundary: Mapping[str, Any] | None = None

    @classmethod
    def from_submit(
        cls,
        *,
        profile: Profile,
        jobscript: str,
        directory: str,
        overrides: SubmitOverrides | Mapping[str, str | None],
    ) -> SubmissionShape:
        submit_overrides = _coerce_overrides(overrides)
        return cls(
            profile=profile.name,
            account=submit_overrides.account(),
            jobscript=jobscript,
            directory=directory,
            overrides={
                key: value
                for key, value in submit_overrides.values.items()
                if value is not None
            },
            boundary=None,
        )

    def to_dict(self) -> dict[str, Any]:
        shape = {
            "profile": self.profile,
            "account": self.account,
            "jobscript": self.jobscript,
            "directory": self.directory,
            "overrides": dict(self.overrides),
        }
        if self.boundary is not None:
            shape["boundary"] = dict(self.boundary)
        shape["shape_token"] = shape_token(shape)
        return shape


@dataclass(frozen=True)
class SubmissionEvidence:
    evidence_type: str
    shape: SubmissionShape
    command: str
    executor: str
    execution_command: str
    ssh_command: str | None
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool

    @classmethod
    def from_remote_result(
        cls,
        evidence_type: str,
        shape: SubmissionShape | Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> SubmissionEvidence:
        return cls(
            evidence_type=evidence_type,
            shape=_coerce_shape(shape),
            command=str(result["command"]),
            executor=str(result.get("executor", "ssh")),
            execution_command=str(
                result.get("execution_command", result.get("ssh_command", ""))
            ),
            ssh_command=(
                str(result["ssh_command"])
                if result.get("ssh_command") is not None
                else None
            ),
            returncode=int(result["returncode"]),
            stdout=str(result["stdout"]),
            stderr=str(result["stderr"]),
            dry_run=bool(result["dry_run"]),
        )

    def to_dict(self) -> dict[str, Any]:
        shape = self.shape.to_dict()
        evidence = {
            "type": self.evidence_type,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "profile": shape["profile"],
            "account": shape["account"],
            "jobscript": shape["jobscript"],
            "directory": shape["directory"],
            "overrides": shape["overrides"],
            "shape_token": shape["shape_token"],
            "command": self.command,
            "executor": self.executor,
            "execution_command": self.execution_command,
            "ssh_command": self.ssh_command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "dry_run": self.dry_run,
        }
        evidence["ok"] = evidence["returncode"] == 0
        evidence["evidence_token"] = evidence_token(evidence)
        return evidence


def normalize_submit_overrides(
    account: str | None = None,
    **overrides: str | None,
) -> dict[str, str | None]:
    return SubmitOverrides.from_values(account=account, **overrides).to_dict()


def namespace_submit_overrides(namespace: Any) -> dict[str, str | None]:
    return SubmitOverrides.from_namespace(namespace).to_dict()


def quote_args_for_submit(
    jobscript: str,
    overrides: SubmitOverrides | Mapping[str, str | None],
) -> list[str]:
    return _coerce_overrides(overrides).quote_args(jobscript)


def submission_shape(
    profile: Profile,
    jobscript: str,
    directory: str,
    overrides: SubmitOverrides | Mapping[str, str | None],
) -> dict[str, Any]:
    return SubmissionShape.from_submit(
        profile=profile,
        jobscript=jobscript,
        directory=directory,
        overrides=overrides,
    ).to_dict()


def submission_evidence(
    evidence_type: str,
    shape: SubmissionShape | Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return SubmissionEvidence.from_remote_result(evidence_type, shape, result).to_dict()


def validate_evidence(
    evidence_type: str,
    evidence: Mapping[str, Any],
    shape: SubmissionShape | Mapping[str, Any],
    *,
    executor: str | None = None,
) -> None:
    shape_dict = _coerce_shape(shape).to_dict()
    if not isinstance(evidence, Mapping):
        raise ConfigError(f"{evidence_type} evidence must be an object")
    if evidence.get("type") != evidence_type:
        raise ConfigError(f"expected {evidence_type} evidence")
    if evidence.get("shape_token") != shape_dict["shape_token"]:
        raise ConfigError(
            f"{evidence_type} evidence is stale for this resource shape; quote and validate again"
        )
    if evidence.get("returncode") != 0 or not evidence.get("ok"):
        raise ConfigError(f"{evidence_type} evidence did not succeed")
    if evidence.get("dry_run"):
        raise ConfigError(f"{evidence_type} evidence came from a dry run")
    evidence_executor = evidence.get("executor", "ssh")
    if executor is not None and evidence_executor != executor:
        raise ConfigError(
            f"{evidence_type} evidence used the {evidence_executor} executor, "
            f"not the current {executor} executor"
        )
    if evidence.get("evidence_token") != evidence_token(evidence):
        raise ConfigError(f"{evidence_type} evidence token is invalid")


def shape_token(shape: Mapping[str, Any]) -> str:
    token_shape = {key: value for key, value in shape.items() if key != "shape_token"}
    encoded = json.dumps(token_shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_token(evidence: Mapping[str, Any]) -> str:
    token_evidence = {
        key: value
        for key, value in evidence.items()
        if key != "evidence_token"
    }
    encoded = json.dumps(token_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_evidence_secret(), encoded, hashlib.sha256).hexdigest()


def _coerce_overrides(overrides: SubmitOverrides | Mapping[str, str | None]) -> SubmitOverrides:
    if isinstance(overrides, SubmitOverrides):
        return overrides
    return SubmitOverrides(dict(overrides))


def _coerce_shape(shape: SubmissionShape | Mapping[str, Any]) -> SubmissionShape:
    if isinstance(shape, SubmissionShape):
        return shape
    overrides = shape.get("overrides", {})
    if not isinstance(overrides, Mapping):
        raise ConfigError("resource shape overrides must be an object")
    return SubmissionShape(
        profile=str(shape["profile"]),
        account=shape.get("account") if isinstance(shape.get("account"), str) else None,
        jobscript=str(shape["jobscript"]),
        directory=str(shape["directory"]),
        overrides={
            str(key): str(value)
            for key, value in overrides.items()
        },
        boundary=(
            {str(key): value for key, value in shape["boundary"].items()}
            if isinstance(shape.get("boundary"), Mapping)
            else None
        ),
    )


def _evidence_secret() -> bytes:
    global _EVIDENCE_SECRET
    if _EVIDENCE_SECRET is None:
        import secrets

        _EVIDENCE_SECRET = secrets.token_bytes(32)
    return _EVIDENCE_SECRET
