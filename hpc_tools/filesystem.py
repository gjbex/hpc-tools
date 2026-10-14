from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from importlib import resources
import json
import shlex
import subprocess
from typing import Any

from hpc_tools.config import Profile
from hpc_tools.execution import CommandExecutor, resolve_executor


FILESYSTEM_PROTOCOL_VERSION = 1
DEFAULT_MAX_BYTES = 1024 * 1024
DEFAULT_MAX_ENTRIES = 1000
DEFAULT_MAX_TRANSFER_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_PATH_CHARACTERS = 4096
MAX_ROOTS = 64
_HELPER_RESOURCE = "filesystem_helper.py"
_BOOTSTRAP = (
    "import sys;"
    "s=sys.stdin.buffer;"
    "n=int.from_bytes(s.read(8),'big');"
    "code=s.read(n);"
    "exec(compile(code,'<hpc-tools-filesystem-helper>','exec'),"
    "{'__name__':'__main__'})"
)


class FilesystemAction(str, Enum):
    PROBE = "probe"
    LIST = "list"
    READ = "read"
    WRITE = "write"
    MKDIR = "mkdir"
    REMOVE = "remove"
    CLEANUP = "cleanup"


class FilesystemFailureCode(str, Enum):
    CONFLICT = "conflict"
    ENCODING_ERROR = "encoding-error"
    HELPER_UNAVAILABLE = "helper-unavailable"
    INTERNAL_ERROR = "internal-error"
    INVALID_PATH = "invalid-path"
    INVALID_REQUEST = "invalid-request"
    IO_ERROR = "io-error"
    LIMIT_EXCEEDED = "limit-exceeded"
    MISSING_PARENT = "missing-parent"
    NOT_DIRECTORY = "not-directory"
    NOT_EMPTY = "not-empty"
    NOT_FOUND = "not-found"
    PERMISSION_DENIED = "permission-denied"
    PROTOCOL_ERROR = "protocol-error"
    ROOT_DENIED = "root-denied"
    SPECIAL_FILE_DENIED = "special-file-denied"
    SYMLINK_DENIED = "symlink-denied"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport-error"
    UNAVAILABLE_ENVIRONMENT = "unavailable-environment"
    UNSUPPORTED_PLATFORM = "unsupported-platform"


@dataclass(frozen=True)
class FilesystemLimits:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_transfer_bytes: int = DEFAULT_MAX_TRANSFER_BYTES
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_entries", "max_transfer_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")

    def protocol_value(self) -> dict[str, int | float]:
        return {
            "max_bytes": self.max_bytes,
            "max_entries": self.max_entries,
            "max_transfer_bytes": self.max_transfer_bytes,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class FilesystemRequest:
    action: FilesystemAction
    path: str | None = None
    roots: tuple[str, ...] = ()
    root: str | None = None
    data: bytes | None = None
    overwrite: bool = False
    mode: int = 0o600
    limits: FilesystemLimits = FilesystemLimits()

    def __post_init__(self) -> None:
        if not isinstance(self.action, FilesystemAction):
            raise ValueError("action must be a FilesystemAction")
        if self.action is FilesystemAction.PROBE:
            return
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("filesystem request path must be a non-empty string")
        if len(self.path) > MAX_PATH_CHARACTERS:
            raise ValueError("filesystem request path is too long")
        if not self.roots or not all(isinstance(root, str) for root in self.roots):
            raise ValueError("filesystem request roots must be non-empty strings")
        if len(self.roots) > MAX_ROOTS:
            raise ValueError("filesystem request has too many roots")
        if any(len(root) > MAX_PATH_CHARACTERS for root in self.roots):
            raise ValueError("filesystem request root is too long")
        if len(self.roots) != len(set(self.roots)):
            raise ValueError("filesystem request roots must not contain duplicates")
        if self.root is not None and self.root not in self.roots:
            raise ValueError("selected root must be one of the granted roots")
        if self.action is FilesystemAction.WRITE:
            if not isinstance(self.data, bytes):
                raise ValueError("write requests require bytes")
            if self.mode not in {0o600, 0o700}:
                raise ValueError("write mode must be 0600 or 0700")
            if len(self.data) > self.limits.max_transfer_bytes:
                raise ValueError("write data exceeds max_transfer_bytes")
        elif self.data is not None:
            raise ValueError("only write requests may carry data")

    def protocol_value(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol": FILESYSTEM_PROTOCOL_VERSION,
            "action": self.action.value,
            "limits": self.limits.protocol_value(),
        }
        if self.action is not FilesystemAction.PROBE:
            result.update({
                "path": self.path,
                "roots": list(self.roots),
                "root": self.root,
                "overwrite": self.overwrite,
            })
        if self.data is not None:
            result["data"] = base64.b64encode(self.data).decode("ascii")
            result["mode"] = self.mode
        return result


@dataclass(frozen=True)
class FilesystemEntry:
    name: str
    kind: str
    size: int | None
    mode: int


@dataclass(frozen=True)
class FilesystemFailure:
    code: FilesystemFailureCode
    message: str


@dataclass(frozen=True)
class FilesystemResult:
    action: FilesystemAction
    ok: bool
    entries: tuple[FilesystemEntry, ...] = ()
    data: bytes | None = None
    size: int | None = None
    truncated: bool = False
    overwritten: bool = False
    removed_kind: str | None = None
    removed_temporary: tuple[str, ...] = ()
    failure: FilesystemFailure | None = None


@dataclass(frozen=True)
class TextReadResult:
    ok: bool
    text: str | None
    size: int | None
    truncated: bool
    failure: FilesystemFailure | None = None


class FilesystemService:
    """Invoke the packaged helper through one local or SSH executor protocol."""

    def __init__(
        self,
        profile: Profile,
        *,
        executor: CommandExecutor | None = None,
        interpreter: str = "python3",
        limits: FilesystemLimits | None = None,
    ) -> None:
        if not interpreter or "\0" in interpreter or "\n" in interpreter:
            raise ValueError("filesystem helper interpreter is invalid")
        self.profile = profile
        self.executor = executor or resolve_executor()
        self.interpreter = interpreter
        self.limits = limits or FilesystemLimits()

    def probe(self) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.PROBE,
            limits=self.limits,
        ))

    def list_directory(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
    ) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.LIST,
            path=path,
            roots=roots,
            root=root,
            limits=self.limits,
        ))

    def read_bytes(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
    ) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.READ,
            path=path,
            roots=roots,
            root=root,
            limits=self.limits,
        ))

    def read_text(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> TextReadResult:
        binary = self.read_bytes(path, roots=roots, root=root)
        if not binary.ok:
            return TextReadResult(
                ok=False,
                text=None,
                size=binary.size,
                truncated=binary.truncated,
                failure=binary.failure,
            )
        try:
            text = (binary.data or b"").decode(encoding, errors=errors)
        except (LookupError, UnicodeDecodeError) as error:
            return TextReadResult(
                ok=False,
                text=None,
                size=binary.size,
                truncated=binary.truncated,
                failure=FilesystemFailure(
                    FilesystemFailureCode.ENCODING_ERROR,
                    f"could not decode file as {encoding}: {error}",
                ),
            )
        return TextReadResult(
            ok=True,
            text=text,
            size=binary.size,
            truncated=binary.truncated,
        )

    def write_bytes(
        self,
        path: str,
        data: bytes,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
        overwrite: bool = False,
        mode: int = 0o600,
    ) -> FilesystemResult:
        if len(data) > self.limits.max_transfer_bytes:
            return _local_failure(
                FilesystemAction.WRITE,
                FilesystemFailureCode.LIMIT_EXCEEDED,
                "write exceeds max_transfer_bytes",
            )
        return self.execute(FilesystemRequest(
            action=FilesystemAction.WRITE,
            path=path,
            roots=roots,
            root=root,
            data=data,
            overwrite=overwrite,
            mode=mode,
            limits=self.limits,
        ))

    def write_text(
        self,
        path: str,
        text: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
        overwrite: bool = False,
        encoding: str = "utf-8",
        mode: int = 0o600,
    ) -> FilesystemResult:
        return self.write_bytes(
            path,
            text.encode(encoding),
            roots=roots,
            root=root,
            overwrite=overwrite,
            mode=mode,
        )

    def make_directory(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
    ) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.MKDIR,
            path=path,
            roots=roots,
            root=root,
            limits=self.limits,
        ))

    def remove(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
    ) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.REMOVE,
            path=path,
            roots=roots,
            root=root,
            limits=self.limits,
        ))

    def cleanup_temporary(
        self,
        path: str,
        *,
        roots: tuple[str, ...],
        root: str | None = None,
    ) -> FilesystemResult:
        return self.execute(FilesystemRequest(
            action=FilesystemAction.CLEANUP,
            path=path,
            roots=roots,
            root=root,
            limits=self.limits,
        ))

    def execute(self, request: FilesystemRequest) -> FilesystemResult:
        try:
            helper = _helper_source()
        except (OSError, FileNotFoundError) as error:
            return _local_failure(
                request.action,
                FilesystemFailureCode.HELPER_UNAVAILABLE,
                f"packaged filesystem helper is unavailable: {error}",
            )
        encoded_request = json.dumps(
            request.protocol_value(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload = len(helper).to_bytes(8, "big") + helper + encoded_request
        command = f"{shlex.quote(self.interpreter)} -c {shlex.quote(_BOOTSTRAP)}"
        plan = self.executor.plan(self.profile, command)
        try:
            completed = self.executor.run_plan_bytes(
                plan,
                input_data=payload,
                timeout=float(request.limits.timeout_seconds) + 1.0,
            )
        except subprocess.TimeoutExpired:
            return _local_failure(
                request.action,
                FilesystemFailureCode.TIMEOUT,
                "filesystem helper transport timed out",
            )
        except (OSError, ValueError) as error:
            return _local_failure(
                request.action,
                FilesystemFailureCode.TRANSPORT_ERROR,
                f"filesystem helper transport failed: {error}",
            )
        if completed.returncode != 0:
            return _local_failure(
                request.action,
                FilesystemFailureCode.HELPER_UNAVAILABLE,
                "filesystem helper or interpreter failed to start",
            )
        response_limit = max(
            request.limits.max_transfer_bytes,
            request.limits.max_bytes * 2 + 65536,
            request.limits.max_entries * 1024 + 65536,
        )
        if len(completed.stdout) > response_limit:
            return _local_failure(
                request.action,
                FilesystemFailureCode.LIMIT_EXCEEDED,
                "filesystem helper response exceeded the transport limit",
            )
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as error:
            return _local_failure(
                request.action,
                FilesystemFailureCode.PROTOCOL_ERROR,
                f"invalid filesystem helper response: {error}",
            )
        return _parse_response(request.action, response)


def _helper_source() -> bytes:
    return resources.files("hpc_tools.data").joinpath(_HELPER_RESOURCE).read_bytes()


def _parse_response(
    expected_action: FilesystemAction,
    response: object,
) -> FilesystemResult:
    if not isinstance(response, dict):
        return _local_failure(
            expected_action,
            FilesystemFailureCode.PROTOCOL_ERROR,
            "filesystem helper response is not an object",
        )
    if response.get("protocol") != FILESYSTEM_PROTOCOL_VERSION:
        return _local_failure(
            expected_action,
            FilesystemFailureCode.PROTOCOL_ERROR,
            "filesystem helper protocol version mismatch",
        )
    if response.get("action") != expected_action.value:
        return _local_failure(
            expected_action,
            FilesystemFailureCode.PROTOCOL_ERROR,
            "filesystem helper returned a mismatched action",
        )
    if response.get("ok") is not True:
        error = response.get("error")
        if not isinstance(error, dict):
            return _local_failure(
                expected_action,
                FilesystemFailureCode.PROTOCOL_ERROR,
                "filesystem helper omitted structured failure data",
            )
        try:
            code = FilesystemFailureCode(error.get("code"))
        except ValueError:
            code = FilesystemFailureCode.INTERNAL_ERROR
        message = error.get("message")
        if not isinstance(message, str):
            message = "filesystem helper returned an invalid failure message"
        return _local_failure(expected_action, code, message)

    try:
        entries = tuple(
            FilesystemEntry(
                name=item["name"],
                kind=item["kind"],
                size=item.get("size"),
                mode=item["mode"],
            )
            for item in response.get("entries", [])
        )
        data_value = response.get("data")
        data = (
            base64.b64decode(data_value, validate=True)
            if data_value is not None
            else None
        )
        return FilesystemResult(
            action=expected_action,
            ok=True,
            entries=entries,
            data=data,
            size=response.get("size"),
            truncated=bool(response.get("truncated", False)),
            overwritten=bool(response.get("overwritten", False)),
            removed_kind=response.get("kind"),
            removed_temporary=tuple(response.get("removed", [])),
        )
    except (KeyError, TypeError, ValueError) as error:
        return _local_failure(
            expected_action,
            FilesystemFailureCode.PROTOCOL_ERROR,
            f"malformed filesystem helper success response: {error}",
        )


def _local_failure(
    action: FilesystemAction,
    code: FilesystemFailureCode,
    message: str,
) -> FilesystemResult:
    return FilesystemResult(
        action=action,
        ok=False,
        failure=FilesystemFailure(code=code, message=message),
    )
