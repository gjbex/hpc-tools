from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hpc_tools import delegation, slurm_contracts

MAX_PAYLOAD_BYTES = 1024 * 1024
CONTAINER_PAYLOAD_PATH = "/opt/hpc-tools/job/payload.sh"


@dataclass
class PreparedJob:
    """Logical request plus server-owned files used for one delegated job."""

    shape: dict[str, Any]
    jobscript: str
    directory: str
    overrides: dict[str, str | None]
    output_directory: str
    temporary_directory: Any = None
    persistent: bool = False

    def cleanup(self) -> None:
        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()
            self.temporary_directory = None

    def discard(self) -> str | None:
        """Remove an unsubmitted persistent staging area without recursion."""
        if not self.persistent:
            return None
        try:
            _discard_staged(Path(self.directory), Path(self.output_directory))
        except OSError as error:
            return str(error)
        self.persistent = False
        return None


def prepare_job(
    runtime: delegation.DelegationRuntime,
    *,
    profile: Any,
    jobscript: str,
    directory: str,
    container: str | None,
    idempotency_key: str | None,
    overrides: Mapping[str, str | None],
    stage: bool,
    temporary: bool = False,
) -> PreparedJob:
    """Validate and stage a containerized job without exposing host control paths."""
    manifest = runtime.manifest
    policy = manifest.filesystem
    if policy is None:
        raise delegation.DelegationError(
            "restricted submission requires a [filesystem] delegation policy"
        )
    if not idempotency_key:
        raise delegation.DelegationError(
            "restricted quotation, validation, and submission require an idempotency_key"
        )
    delegation.validate_idempotency_key(idempotency_key)
    if not container:
        raise delegation.DelegationError(
            "restricted submission requires an approved container"
        )
    for name in ("error", "output", "export"):
        if overrides.get(name) is not None:
            raise delegation.DelegationError(
                f"restricted submission does not accept the {name!r} Slurm override"
            )

    work_root = _secure_directory(policy.work_root, label="filesystem.work_root")
    request_directory = _secure_directory(
        _absolute_request_path(directory), label="submission directory"
    )
    _require_under(request_directory, work_root, "submission directory")
    payload_path = _payload_path(request_directory, jobscript)
    payload = _read_regular_file(payload_path, label="job payload")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise delegation.DelegationError(
            f"job payload exceeds the {MAX_PAYLOAD_BYTES}-byte staging limit"
        )
    script_digest = hashlib.sha256(payload).hexdigest()

    container_path = _secure_regular_file(
        _absolute_request_path(container), label="approved container"
    )
    if _is_under(container_path, work_root) or _is_under(
        container_path, policy.output_root
    ):
        raise delegation.DelegationError(
            "approved container must be outside agent-writable and generated output roots"
        )
    if stat.S_IMODE(container_path.stat().st_mode) & 0o022:
        raise delegation.DelegationError(
            "approved container must not be group- or world-writable"
        )

    logical_overrides = dict(overrides)
    _validate_supported_runtime_shape(logical_overrides)
    logical_shape = slurm_contracts.submission_shape(
        profile,
        jobscript,
        str(request_directory),
        logical_overrides,
    )
    logical_shape.pop("shape_token", None)
    logical_shape["boundary"] = {
        "container": str(container_path),
        "script_sha256": script_digest,
        "idempotency_key": idempotency_key,
    }
    logical_shape["shape_token"] = slurm_contracts.shape_token(logical_shape)
    delegation.authorize_shape(manifest, logical_shape)

    request_digest = hashlib.sha256(
        (
            f"{manifest.identifier}\0{idempotency_key}\0"
            f"{logical_shape['shape_token']}"
        ).encode()
    ).hexdigest()[:32]
    state_root = policy.state_root
    output_root = policy.output_root
    persistent_state_directory = state_root / "jobs" / request_digest
    public_output_directory = output_root / request_digest
    temporary_directory = None
    if stage and temporary:
        _secure_private_root(state_root, "filesystem.state_root")
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="validation-", dir=state_root
        )
        state_directory = Path(temporary_directory.name)
        output_directory = state_directory / "output"
    else:
        state_directory = persistent_state_directory
        output_directory = public_output_directory
    staged_payload = state_directory / "payload.sh"
    staged_jobscript = state_directory / "job.slurm"

    effective_overrides = dict(logical_overrides)
    array_job = effective_overrides.get("array") is not None
    slurm_token = "%A_%a" if array_job else "%j"
    effective_overrides["output"] = str(output_directory / f"slurm-{slurm_token}.out")
    effective_overrides["error"] = str(output_directory / f"slurm-{slurm_token}.err")
    effective_overrides["export"] = "NONE"

    if stage:
        try:
            if temporary:
                _secure_private_root(state_directory, "temporary staging directory")
            else:
                _secure_private_root(state_root, "filesystem.state_root")
                _secure_private_root(output_root, "filesystem.output_root")
                _mkdir_private(state_root / "jobs")
            _mkdir_private(state_directory)
            _mkdir_private(output_directory)
            _write_exact(staged_payload, payload, mode=0o500)
            wrapper = _render_wrapper(
                policy,
                payload_path=staged_payload,
                payload_directory=request_directory,
                output_directory=output_directory,
                container=container_path,
            )
            _write_exact(staged_jobscript, wrapper.encode("utf-8"), mode=0o500)
        except Exception:
            if temporary_directory is not None:
                temporary_directory.cleanup()
            else:
                try:
                    _discard_staged(state_directory, output_directory)
                except OSError:
                    pass
            raise

    return PreparedJob(
        shape=logical_shape,
        jobscript=staged_jobscript.name,
        directory=str(state_directory),
        overrides=effective_overrides,
        output_directory=str(public_output_directory),
        temporary_directory=temporary_directory,
        persistent=stage and not temporary,
    )


def _render_wrapper(
    policy: delegation.FilesystemPolicy,
    *,
    payload_path: Path,
    payload_directory: Path,
    output_directory: Path,
    container: Path,
) -> str:
    apptainer = _secure_regular_file(
        policy.apptainer_path, label="filesystem.apptainer_path", executable=True
    )
    bind_paths = (
        payload_path, policy.work_root, output_directory, *policy.input_roots
    )
    for path in bind_paths:
        if ":" in str(path) or "," in str(path):
            raise delegation.DelegationError(
                "filesystem paths containing ':' or ',' cannot be used as Apptainer binds"
            )
    binds = [
        f"{payload_path}:{CONTAINER_PAYLOAD_PATH}:ro",
        f"{policy.work_root}:{policy.work_root}:ro",
        f"{output_directory}:{output_directory}:rw",
        *(f"{path}:{path}:ro" for path in policy.input_roots),
    ]
    command = [
        str(apptainer),
        "exec",
        "--containall",
        "--cleanenv",
        "--no-home",
        "--no-mount",
        "home,cwd,hostfs,bind-paths",
        "--pwd",
        str(payload_directory),
    ]
    for bind in binds:
        command.extend(["--bind", bind])
    command.extend(
        [
            "--env",
            "HOME=/tmp",
            "--env",
            f"HPC_TOOLS_DELEGATE_OUTPUT={output_directory}",
            str(container),
            "/bin/sh",
            CONTAINER_PAYLOAD_PATH,
        ]
    )
    file_limit = (
        f"ulimit -f {policy.max_file_blocks}\n"
        if policy.max_file_blocks is not None
        else ""
    )
    open_limit = (
        f"ulimit -n {policy.max_open_files}\n"
        if policy.max_open_files is not None
        else ""
    )
    output = shlex.quote(str(output_directory))
    rendered = " ".join(shlex.quote(part) for part in command)
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        "umask 077\n"
        f"output_directory={output}\n"
        'incomplete="$output_directory/.hpc-tools-incomplete"\n'
        'status="$output_directory/.hpc-tools-status.json"\n'
        'temporary_status="$status.$$"\n'
        ': > "$incomplete"\n'
        f"{file_limit}"
        f"{open_limit}"
        "set +e\n"
        f"{rendered}\n"
        "exit_code=$?\n"
        "set -e\n"
        "printf '{\"exit_code\":%s,\"complete\":%s}\\n' "
        '"$exit_code" "$([ "$exit_code" -eq 0 ] && printf true || printf false)" '
        '> "$temporary_status"\n'
        'mv -f "$temporary_status" "$status"\n'
        '[ "$exit_code" -ne 0 ] || rm -f "$incomplete"\n'
        'exit "$exit_code"\n'
    )


def _validate_supported_runtime_shape(overrides: Mapping[str, str | None]) -> None:
    for name in ("nodes", "ntasks", "ntasks_per_node"):
        value = overrides.get(name)
        if value is not None and value != "1":
            raise delegation.DelegationError(
                "the restricted container wrapper currently supports one Slurm node "
                "and one task; use an array or add reviewed site-specific srun integration"
            )
    unsupported_gpu = (
        "gpu_bind", "gpus", "gpus_per_node", "gpus_per_task", "gres"
    )
    if any(overrides.get(name) is not None for name in unsupported_gpu):
        raise delegation.DelegationError(
            "GPU and GRES requests require reviewed site-specific Apptainer device integration"
        )


def _absolute_request_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "$" in value or "~" in value:
        raise delegation.DelegationError("restricted paths must be absolute literals")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise delegation.DelegationError("restricted paths must be absolute and normalized")
    return path


def _payload_path(directory: Path, jobscript: str) -> Path:
    if not isinstance(jobscript, str) or not jobscript or "$" in jobscript or "~" in jobscript:
        raise delegation.DelegationError("jobscript must be one literal path")
    candidate = Path(jobscript)
    path = candidate if candidate.is_absolute() else directory / candidate
    if ".." in path.parts:
        raise delegation.DelegationError("jobscript must not contain parent traversal")
    _require_under(path, directory, "jobscript")
    return path


def _secure_directory(path: Path, *, label: str) -> Path:
    _reject_symlinks(path, label)
    if not path.is_dir():
        raise delegation.DelegationError(f"{label} is not a directory: {path}")
    return path


def _secure_regular_file(
    path: Path, *, label: str, executable: bool = False
) -> Path:
    _reject_symlinks(path, label)
    if not path.is_file():
        raise delegation.DelegationError(f"{label} is not a regular file: {path}")
    if executable and not os.access(path, os.X_OK):
        raise delegation.DelegationError(f"{label} is not executable: {path}")
    return path


def _read_regular_file(path: Path, *, label: str) -> bytes:
    _secure_regular_file(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        expected = path.stat()
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise delegation.DelegationError(f"{label} changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_PAYLOAD_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _reject_symlinks(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as error:
            raise delegation.DelegationError(f"{label} does not exist: {current}") from error
        if stat.S_ISLNK(mode):
            raise delegation.DelegationError(f"{label} contains a symbolic link: {current}")


def _require_under(path: Path, root: Path, label: str) -> None:
    if not _is_under(path, root):
        raise delegation.DelegationError(f"{label} is outside {root}")


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _secure_private_root(path: Path, label: str) -> None:
    _secure_directory(path, label=label)
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise delegation.DelegationError(
            f"{label} must be server-owned and inaccessible to group and other users"
        )


def _mkdir_private(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _secure_private_root(path, str(path))


def _write_exact(path: Path, content: bytes, *, mode: int) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        existing = _read_regular_file(path, label=str(path))
        if existing != content:
            raise delegation.DelegationError(
                f"staged control file already exists with different contents: {path}"
            )
        if stat.S_IMODE(path.stat().st_mode) != mode:
            raise delegation.DelegationError(f"staged control file has unsafe mode: {path}")
        return
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _discard_staged(state_directory: Path, output_directory: Path) -> None:
    for path in (state_directory / "job.slurm", state_directory / "payload.sh"):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"refusing to remove unexpected staged path: {path}")
        path.unlink()
    try:
        output_directory.rmdir()
    except FileNotFoundError:
        pass
    try:
        state_directory.rmdir()
    except FileNotFoundError:
        pass


def job_metadata(prepared: PreparedJob) -> str:
    """Return stable metadata for operator diagnostics without private state paths."""
    return json.dumps(
        {
            "shape_token": prepared.shape["shape_token"],
            "output_directory": prepared.output_directory,
        },
        sort_keys=True,
    )
