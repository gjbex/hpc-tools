from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hpc_tools import slurm
from hpc_tools.config import ConfigError, Profile
from hpc_tools.credit_quotes import CreditAmount, CreditQuoteError, parse_credit_amount

_EVIDENCE_SECRET: bytes | None = None


class QuoteEvidenceExpiredError(ConfigError):
    """Raised when otherwise checked quote evidence is no longer current."""


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
    controller_generation: int | None = None

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
            controller_generation=None,
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
        if self.controller_generation is not None:
            shape["controller_generation"] = self.controller_generation
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
    quoted_cost: CreditAmount | None = None
    quote_ttl_seconds: int | None = None
    quote_evidence_token: str | None = None
    issued_at: datetime | None = None

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
        issued_at = _normalize_now(self.issued_at).replace(microsecond=0)
        evidence = {
            "type": self.evidence_type,
            "timestamp": issued_at.isoformat(timespec="seconds"),
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
        if self.quoted_cost is not None:
            if self.evidence_type != "quote":
                raise ConfigError("only quote evidence may contain quoted cost")
            if type(self.quote_ttl_seconds) is not int or self.quote_ttl_seconds <= 0:
                raise ConfigError("cost-bearing quote evidence requires a positive TTL")
            evidence["quoted_cost"] = self.quoted_cost.to_dict()
            evidence["expires_at"] = (
                issued_at + timedelta(seconds=self.quote_ttl_seconds)
            ).isoformat(timespec="seconds")
        elif self.quote_ttl_seconds is not None:
            raise ConfigError("quote evidence TTL requires a quoted cost")
        if self.quote_evidence_token is not None:
            if self.evidence_type != "validation":
                raise ConfigError(
                    "only validation evidence may bind a quote evidence token"
                )
            evidence["quote_evidence_token"] = self.quote_evidence_token
        evidence["ok"] = evidence["returncode"] == 0
        evidence["evidence_token"] = evidence_token(evidence)
        return evidence


@dataclass(frozen=True)
class ValidatedEvidence:
    evidence_type: str
    timestamp: datetime
    evidence_token: str
    quoted_cost: CreditAmount | None
    expires_at: datetime | None
    quote_evidence_token: str | None


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
    *,
    quoted_cost: CreditAmount | None = None,
    quote_ttl_seconds: int | None = None,
    quote_evidence_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    base = SubmissionEvidence.from_remote_result(evidence_type, shape, result)
    return SubmissionEvidence(
        evidence_type=base.evidence_type,
        shape=base.shape,
        command=base.command,
        executor=base.executor,
        execution_command=base.execution_command,
        ssh_command=base.ssh_command,
        returncode=base.returncode,
        stdout=base.stdout,
        stderr=base.stderr,
        dry_run=base.dry_run,
        quoted_cost=quoted_cost,
        quote_ttl_seconds=quote_ttl_seconds,
        quote_evidence_token=quote_evidence_token,
        issued_at=now,
    ).to_dict()


def validate_evidence(
    evidence_type: str,
    evidence: Mapping[str, Any],
    shape: SubmissionShape | Mapping[str, Any],
    *,
    executor: str | None = None,
    now: datetime | None = None,
    credit_unit: str | None = None,
    credit_scale: int | None = None,
    quote_ttl_seconds: int | None = None,
    allow_expired_quote: bool = False,
    expected_quote_evidence_token: str | None = None,
    not_before: datetime | None = None,
) -> ValidatedEvidence:
    shape_dict = _coerce_shape(shape).to_dict()
    if not isinstance(evidence, Mapping):
        raise ConfigError(f"{evidence_type} evidence must be an object")
    if evidence.get("type") != evidence_type:
        raise ConfigError(f"expected {evidence_type} evidence")
    supplied_token = evidence.get("evidence_token")
    if not isinstance(supplied_token, str):
        raise ConfigError(f"{evidence_type} evidence token is invalid")
    try:
        expected_token = evidence_token(evidence)
    except (TypeError, ValueError):
        raise ConfigError(f"{evidence_type} evidence token is invalid") from None
    if not hmac.compare_digest(supplied_token, expected_token):
        raise ConfigError(f"{evidence_type} evidence token is invalid")
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
    checked_at = _normalize_now(now)
    timestamp = _parse_timestamp(
        evidence.get("timestamp"),
        f"{evidence_type} evidence timestamp",
    )
    if timestamp > checked_at:
        raise ConfigError(f"{evidence_type} evidence timestamp is in the future")

    quoted_cost = None
    expires_at = None
    credit_requested = any(
        value is not None
        for value in (credit_unit, credit_scale, quote_ttl_seconds)
    )
    if credit_requested:
        if evidence_type != "quote":
            raise ConfigError("credit dimensions apply only to quote evidence")
        if (
            not isinstance(credit_unit, str)
            or type(credit_scale) is not int
            or type(quote_ttl_seconds) is not int
            or quote_ttl_seconds <= 0
        ):
            raise ConfigError("complete credit quote dimensions are required")
        try:
            quoted_cost = parse_credit_amount(
                evidence.get("quoted_cost"),
                label="quote evidence quoted_cost",
            )
        except CreditQuoteError as error:
            raise ConfigError(str(error)) from error
        if quoted_cost.unit != credit_unit:
            raise ConfigError(
                f"quote evidence credit unit {quoted_cost.unit!r} does not match "
                f"the configured unit {credit_unit!r}"
            )
        if quoted_cost.scale != credit_scale:
            raise ConfigError(
                f"quote evidence credit scale {quoted_cost.scale} does not match "
                f"the configured scale {credit_scale}"
            )
        expires_at = _parse_timestamp(
            evidence.get("expires_at"),
            "quote evidence expiry",
        )
        expected_expiry = timestamp + timedelta(seconds=quote_ttl_seconds)
        if expires_at != expected_expiry:
            raise ConfigError("quote evidence expiry does not match the configured TTL")
        if checked_at >= expires_at and not allow_expired_quote:
            raise QuoteEvidenceExpiredError(
                "quote evidence has expired; quote and validate again"
            )
    elif "quoted_cost" in evidence or "expires_at" in evidence:
        raise ConfigError("unexpected credit fields in non-credit evidence")

    bound_quote_token = evidence.get("quote_evidence_token")
    if expected_quote_evidence_token is not None:
        if evidence_type != "validation":
            raise ConfigError("quote identity applies only to validation evidence")
        if not isinstance(bound_quote_token, str) or not hmac.compare_digest(
            bound_quote_token,
            expected_quote_evidence_token,
        ):
            raise ConfigError("validation evidence is not bound to the current quote")
        if not_before is None:
            raise ConfigError("bound validation evidence requires the quote timestamp")
        if timestamp < _normalize_now(not_before):
            raise ConfigError("validation evidence predates its bound quote")
    elif bound_quote_token is not None:
        raise ConfigError("unexpected quote binding in validation evidence")

    return ValidatedEvidence(
        evidence_type=evidence_type,
        timestamp=timestamp,
        evidence_token=supplied_token,
        quoted_cost=quoted_cost,
        expires_at=expires_at,
        quote_evidence_token=(
            bound_quote_token if isinstance(bound_quote_token, str) else None
        ),
    )


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
    controller_generation = shape.get("controller_generation")
    if controller_generation is not None and (
        type(controller_generation) is not int or controller_generation < 1
    ):
        raise ConfigError("resource shape controller_generation must be a positive integer")
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
        controller_generation=controller_generation,
    )


def _normalize_now(value: datetime | None) -> datetime:
    selected = value if value is not None else datetime.now(UTC)
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise ConfigError("evidence clock must be timezone-aware")
    return selected.astimezone(UTC)


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ConfigError(f"{label} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfigError(f"{label} must include a UTC offset")
    return parsed.astimezone(UTC)


def _evidence_secret() -> bytes:
    global _EVIDENCE_SECRET
    if _EVIDENCE_SECRET is None:
        import secrets

        _EVIDENCE_SECRET = secrets.token_bytes(32)
    return _EVIDENCE_SECRET
