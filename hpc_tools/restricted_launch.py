from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from hpc_tools import delegation
from hpc_tools.config import ConfigError
from hpc_tools.mcp_bridge import SOCKET_ENV_VAR

CONTAINER_SOCKET_DIRECTORY = "/run/hpc-tools-mcp"
FORBIDDEN_COMMANDS = (
    "ssh", "scp", "sftp",
    "sbatch", "scancel", "squeue", "sacct", "scontrol", "srun", "salloc",
    "munge", "unmunge",
)
REQUEUE_SIGNAL = signal.SIGUSR1
TERMINATION_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def build_apptainer_command(
    *,
    manifest: delegation.DelegationManifest,
    agent_image: Path,
    socket_directory: Path,
    agent_command: list[str],
    agent_env_file: Path | None = None,
) -> list[str]:
    policy = _require_policy(manifest)
    command = _base_apptainer_command(policy.apptainer_path)
    binds = [
        (policy.work_root, policy.work_root, "rw"),
        (policy.output_root, policy.output_root, "ro"),
        *((path, path, "ro") for path in policy.input_roots),
        (socket_directory, Path(CONTAINER_SOCKET_DIRECTORY), "ro"),
    ]
    for source, target, mode in binds:
        _validate_bind_path(source)
        _validate_bind_path(target)
        command.extend(["--bind", f"{source}:{target}:{mode}"])
    if agent_env_file is not None:
        command.extend(["--env-file", str(agent_env_file)])
    command.extend(
        [
            "--env",
            "HOME=/tmp",
            "--env",
            f"{SOCKET_ENV_VAR}={CONTAINER_SOCKET_DIRECTORY}/server.sock",
            "--pwd",
            str(policy.work_root),
            str(agent_image),
            *agent_command,
        ]
    )
    return command


def launch(
    *,
    manifest_path: Path,
    ledger_path: Path,
    profile: str,
    agent_image: Path,
    agent_command: list[str],
    runtime_base: Path | None = None,
    agent_env_file: Path | None = None,
    dry_run: bool = False,
) -> int:
    parent_job_id = os.environ.get("SLURM_JOB_ID")
    if not parent_job_id:
        raise ConfigError("hpc-agent-launch must run inside a Slurm allocation")
    manifest = delegation.load_manifest(
        manifest_path,
        expected_profile=profile,
        expected_parent_job_id=parent_job_id,
    )
    policy = _require_policy(manifest)
    _prepare_policy_paths(policy)
    _ensure_private_file(manifest.source_path, "delegation manifest")
    ledger_path = _absolute_literal(ledger_path, "ledger")
    _ensure_not_exposed(
        (manifest.source_path, ledger_path, policy.state_root),
        (policy.work_root, policy.output_root, *policy.input_roots),
    )
    selected_env_file = None
    if agent_env_file is not None:
        selected_env_file = _absolute_literal(agent_env_file, "agent environment file")
        _ensure_private_file(selected_env_file, "agent environment file")
        _ensure_not_exposed(
            (selected_env_file,),
            (policy.work_root, policy.output_root, *policy.input_roots),
        )
    image = _secure_file(agent_image, "agent image")
    if stat.S_IMODE(image.stat().st_mode) & 0o022:
        raise ConfigError("agent image must not be group- or world-writable")
    if not agent_command:
        raise ConfigError("an agent command is required after --")

    selected_runtime_base = runtime_base or _default_runtime_base()
    selected_runtime_base = _secure_directory(
        selected_runtime_base, "runtime base", private=True
    )
    with tempfile.TemporaryDirectory(
        prefix=f"hpc-tools-{parent_job_id}-", dir=selected_runtime_base
    ) as temporary:
        socket_directory = Path(temporary)
        os.chmod(socket_directory, 0o700)
        socket_path = socket_directory / "server.sock"
        container_command = build_apptainer_command(
            manifest=manifest,
            agent_image=image,
            socket_directory=socket_directory,
            agent_command=agent_command,
            agent_env_file=selected_env_file,
        )
        if dry_run:
            print(subprocess.list2cmdline(container_command))
            return 0

        _preflight_image(policy, image, label="parent agent image")
        for worker_value in manifest.allowed["containers"]:
            worker_image = _secure_file(Path(worker_value), "approved worker image")
            if stat.S_IMODE(worker_image.stat().st_mode) & 0o022:
                raise ConfigError(
                    f"approved worker image must not be group- or world-writable: {worker_image}"
                )
            _preflight_image(policy, worker_image, label="approved worker image")
        hpc_mcp = shutil.which("hpc-mcp")
        if not hpc_mcp:
            raise ConfigError("hpc-mcp is not available in the host PATH")
        hpc_mcp_path = _secure_file(
            Path(hpc_mcp).resolve(), "host hpc-mcp executable", executable=True
        )
        _ensure_not_exposed(
            (
                hpc_mcp_path,
                Path(sys.executable).resolve(),
                Path(__file__).resolve(),
            ),
            (policy.work_root, policy.output_root, *policy.input_roots),
        )
        ledger = delegation.DelegationLedger(ledger_path)
        ledger.register(manifest)
        ledger.begin_controller(
            manifest, restart_count=_controller_restart_count()
        )
        _ensure_cleanup_job(
            manifest=manifest,
            ledger=ledger,
            ledger_path=ledger_path,
            profile=profile,
            parent_job_id=parent_job_id,
        )
        bridge_command = [
            sys.executable,
            "-m",
            "hpc_tools.mcp_bridge",
            "serve",
            "--socket",
            str(socket_path),
            "--",
            str(hpc_mcp_path),
            "--executor",
            "local",
            "--preset",
            "slurm-job",
            "--profile",
            profile,
            "--delegation",
            str(manifest.source_path),
            "--ledger",
            str(ledger_path),
        ]
        server_environment = _sanitized_server_environment(parent_job_id)
        bridge = subprocess.Popen(bridge_command, env=server_environment)
        pending_signal: list[int] = []
        previous_handlers: dict[int, signal.Handlers] = {}

        def request_shutdown(signum: int, _frame: object) -> None:
            pending_signal.append(signum)

        for signum in (REQUEUE_SIGNAL, *TERMINATION_SIGNALS):
            previous_handlers[signum] = signal.signal(signum, request_shutdown)
        try:
            _wait_for_socket(socket_path, bridge)
            agent = subprocess.Popen(
                container_command,
                env=_sanitized_apptainer_environment(),
            )
            while agent.poll() is None and not pending_signal:
                time.sleep(0.1)
            if pending_signal:
                signum = pending_signal[0]
                reason = signal.Signals(signum).name
                ledger.begin_draining(manifest, reason=reason)
                _terminate_process(agent, timeout=5)
                if not _wait_for_inflight_submissions(
                    ledger,
                    manifest,
                    timeout=_drain_settle_timeout(manifest.lifecycle),
                ):
                    failure_reason = (
                        "timeout-requeue-failed: in-flight submission did not "
                        "settle during drain"
                        if signum == REQUEUE_SIGNAL
                        else "in-flight submission did not settle during drain"
                    )
                    ledger.finalize_controller(
                        manifest,
                        reason=failure_reason,
                    )
                    return 2
                if signum == REQUEUE_SIGNAL:
                    if manifest.lifecycle.on_timeout != "requeue-or-cancel":
                        ledger.finalize_controller(manifest, reason="timeout")
                        return 124
                    return _request_parent_requeue(
                        ledger=ledger,
                        manifest=manifest,
                        parent_job_id=parent_job_id,
                    )
                ledger.finalize_controller(manifest, reason=reason)
                return 128 + signum

            returncode = agent.returncode if agent.returncode is not None else 1
            active = len(ledger.owned_jobs_for_cleanup(manifest))
            reason = (
                "normal exit with active delegated jobs"
                if returncode == 0 and active
                else "normal exit" if returncode == 0 else f"agent exited {returncode}"
            )
            ledger.finalize_controller(manifest, reason=reason)
            return returncode
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            if bridge.poll() is None:
                _terminate_process(bridge, timeout=5)


def _controller_restart_count() -> int:
    value = os.environ.get(delegation.CONTROLLER_RESTART_ENV_VAR, "0")
    if not value.isdigit():
        raise ConfigError(
            f"{delegation.CONTROLLER_RESTART_ENV_VAR} must be a non-negative integer"
        )
    return int(value)


def _drain_settle_timeout(policy: delegation.LifecyclePolicy) -> float:
    available = max(1.0, float(policy.warning_seconds) - 30.0)
    return min(300.0, available)


def _wait_for_inflight_submissions(
    ledger: delegation.DelegationLedger,
    manifest: delegation.DelegationManifest,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while ledger.inflight_submission_count(manifest):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _request_parent_requeue(
    *,
    ledger: delegation.DelegationLedger,
    manifest: delegation.DelegationManifest,
    parent_job_id: str,
) -> int:
    try:
        ledger.request_requeue(manifest)
    except delegation.DelegationError as error:
        ledger.finalize_controller(
            manifest, reason=f"timeout-requeue-failed: {error}"
        )
        return 2
    completed = subprocess.run(
        ["scontrol", "requeue", parent_job_id],
        check=False,
        capture_output=True,
        text=True,
    )
    scheduler_detail = completed.stderr.strip() or completed.stdout.strip()
    detail = (
        scheduler_detail
        if completed.returncode == 0
        else f"timeout-requeue-failed: {scheduler_detail or 'scontrol failed'}"
    )
    ledger.record_requeue_result(
        manifest,
        accepted=completed.returncode == 0,
        detail=detail,
    )
    return 0 if completed.returncode == 0 else 2


def _ensure_cleanup_job(
    *,
    manifest: delegation.DelegationManifest,
    ledger: delegation.DelegationLedger,
    ledger_path: Path,
    profile: str,
    parent_job_id: str,
) -> str:
    existing = ledger.cleanup_job_id(manifest)
    if existing is not None:
        return existing
    reaper = shutil.which("hpc-agent-reap")
    if not reaper:
        raise ConfigError("hpc-agent-reap is not available in the host PATH")
    reaper_path = _secure_file(Path(reaper).resolve(), "host cleanup executable", executable=True)
    policy = _require_policy(manifest)
    script_path = policy.state_root / "parent-cleanup.sh"
    command = [
        str(reaper_path),
        "--manifest",
        str(manifest.source_path),
        "--ledger",
        str(ledger_path),
        "--profile",
        profile,
        "--parent-job-id",
        parent_job_id,
    ]
    script = "#!/bin/sh\nset -eu\numask 077\nexec " + shlex.join(command) + "\n"
    _write_private_script(script_path, script)
    submit = [
        "sbatch",
        "--parsable",
        f"--dependency=afterany:{parent_job_id}",
        "--job-name=hpc-agent-cleanup",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=1",
        "--time=00:15:00",
        "--export=NONE",
        f"--output={policy.state_root / 'cleanup-%j.out'}",
        f"--error={policy.state_root / 'cleanup-%j.err'}",
    ]
    account = os.environ.get("SLURM_JOB_ACCOUNT")
    partition = os.environ.get("SLURM_JOB_PARTITION")
    if account:
        submit.append(f"--account={account}")
    if partition:
        submit.append(f"--partition={partition}")
    submit.append(str(script_path))
    completed = subprocess.run(submit, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ConfigError(
            "unable to submit parent cleanup job: "
            + (completed.stderr.strip() or f"sbatch exited {completed.returncode}")
        )
    token = completed.stdout.strip().split(";", 1)[0]
    try:
        job_id = delegation.normalize_job_id(token)
    except delegation.DelegationError as error:
        raise ConfigError(
            "cleanup sbatch succeeded but its job ID could not be parsed"
        ) from error
    try:
        ledger.record_cleanup_job(manifest, job_id=job_id)
    except delegation.DelegationError:
        subprocess.run(["scancel", job_id], check=False, capture_output=True, text=True)
        raise
    return job_id


def _write_private_script(path: Path, content: str) -> None:
    _reject_existing_symlinks(path, "cleanup script", require_leaf=False)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ConfigError(f"cleanup script must be a regular file: {path}")
        if path.read_text(encoding="utf-8") != content:
            raise ConfigError(f"existing cleanup script has unexpected contents: {path}")
        os.chmod(path, 0o500)
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o500)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _terminate_process(process: subprocess.Popen[object], *, timeout: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _preflight_image(
    policy: delegation.FilesystemPolicy, image: Path, *, label: str
) -> None:
    checks = " ".join(FORBIDDEN_COMMANDS)
    script = (
        "set -eu; "
        f"for command in {checks}; do "
        "if command -v \"$command\" >/dev/null 2>&1; then "
        "echo \"forbidden command in agent image: $command\" >&2; exit 42; fi; done; "
        "for path in /run/munge /var/run/munge /etc/slurm /etc/ssh /root/.ssh; do "
        "if [ -e \"$path\" ]; then "
        "echo \"forbidden credential or configuration path visible: $path\" >&2; "
        "exit 43; fi; done"
    )
    command = _base_apptainer_command(policy.apptainer_path)
    command.extend([str(image), "/bin/sh", "-c", script])
    completed = subprocess.run(
        command,
        check=False,
        env=_sanitized_apptainer_environment(),
    )
    if completed.returncode != 0:
        raise ConfigError(
            f"{label} boundary preflight failed with return code {completed.returncode}"
        )


def _base_apptainer_command(apptainer_path: Path) -> list[str]:
    executable = _secure_file(apptainer_path, "Apptainer executable", executable=True)
    return [
        str(executable),
        "exec",
        "--containall",
        "--cleanenv",
        "--no-home",
        "--no-mount",
        "home,cwd,hostfs,bind-paths",
    ]


def _prepare_policy_paths(policy: delegation.FilesystemPolicy) -> None:
    _mkdir_private(policy.state_root, "filesystem.state_root")
    _mkdir_private(policy.work_root, "filesystem.work_root")
    _mkdir_private(policy.output_root, "filesystem.output_root")
    _secure_file(policy.apptainer_path, "filesystem.apptainer_path", executable=True)
    for path in policy.input_roots:
        _secure_directory(path, "filesystem input root")


def _require_policy(
    manifest: delegation.DelegationManifest,
) -> delegation.FilesystemPolicy:
    if manifest.filesystem is None:
        raise ConfigError("agent launch requires a [filesystem] delegation policy")
    return manifest.filesystem


def _default_runtime_base() -> Path:
    value = os.environ.get("SLURM_TMPDIR")
    if not value:
        raise ConfigError(
            "SLURM_TMPDIR is required unless --runtime-directory is supplied"
        )
    return _absolute_literal(Path(value), "SLURM_TMPDIR")


def _wait_for_socket(path: Path, bridge: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if bridge.poll() is not None:
            raise ConfigError(
                f"host MCP bridge exited before startup with return code {bridge.returncode}"
            )
        try:
            if stat.S_ISSOCK(path.stat().st_mode):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    raise ConfigError("timed out waiting for the host MCP socket")


def _sanitized_apptainer_environment() -> dict[str, str]:
    allowed_names = {
        "HOME", "USER", "LOGNAME", "PATH", "LANG", "LANGUAGE", "TERM", "TZ",
        "TMPDIR", "XDG_RUNTIME_DIR", "LD_LIBRARY_PATH",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
    }
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        if key not in allowed_names and not key.startswith(("LC_", "SLURM_")):
            continue
        environment[key] = value
    return environment


def _sanitized_server_environment(parent_job_id: str) -> dict[str, str]:
    blocked_names = {"SSH_AUTH_SOCK", "SSH_AGENT_PID", "LD_PRELOAD"}
    blocked_fragments = (
        "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY",
        "ACCESS_KEY", "COOKIE",
    )
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if key in blocked_names or any(fragment in upper for fragment in blocked_fragments):
            continue
        environment[key] = value
    environment[delegation.PARENT_JOB_ENV_VAR] = parent_job_id
    return environment


def _ensure_not_exposed(private: tuple[Path, ...], exposed: tuple[Path, ...]) -> None:
    for private_path in private:
        for exposed_path in exposed:
            if (
                private_path == exposed_path
                or exposed_path in private_path.parents
                or private_path in exposed_path.parents
            ):
                raise ConfigError(
                    f"private host path {private_path} overlaps container bind {exposed_path}"
                )


def _validate_bind_path(path: Path) -> None:
    value = str(path)
    if ":" in value or "," in value:
        raise ConfigError(f"unsupported character in Apptainer bind path: {path}")


def _absolute_literal(path: Path, label: str) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{label} must be an absolute normalized path")
    return path


def _secure_directory(path: Path, label: str, *, private: bool = False) -> Path:
    selected = _absolute_literal(path, label)
    _reject_existing_symlinks(selected, label, require_leaf=True)
    if selected.is_symlink() or not selected.is_dir():
        raise ConfigError(f"{label} must be a real directory: {selected}")
    if private:
        info = selected.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ConfigError(f"{label} must be owned by this user with mode 0700")
    return selected


def _secure_file(path: Path, label: str, *, executable: bool = False) -> Path:
    selected = _absolute_literal(path, label)
    _reject_existing_symlinks(selected, label, require_leaf=True)
    if selected.is_symlink() or not selected.is_file():
        raise ConfigError(f"{label} must be a real regular file: {selected}")
    if executable and not os.access(selected, os.X_OK):
        raise ConfigError(f"{label} is not executable: {selected}")
    return selected


def _ensure_private_file(path: Path, label: str) -> None:
    selected = _secure_file(path, label)
    info = selected.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ConfigError(f"{label} must be owned by this user with mode 0600")


def _mkdir_private(path: Path, label: str) -> None:
    selected = _absolute_literal(path, label)
    _reject_existing_symlinks(selected, label, require_leaf=False)
    selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(selected, 0o700)
    _secure_directory(selected, label, private=True)


def _reject_existing_symlinks(path: Path, label: str, *, require_leaf: bool) -> None:
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:], start=1):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if require_leaf or index < len(path.parts) - 1:
                raise ConfigError(f"{label} does not exist: {current}")
            return
        if stat.S_ISLNK(mode):
            raise ConfigError(f"{label} contains a symbolic link: {current}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpc-agent-launch")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--agent-image", type=Path, required=True)
    parser.add_argument("--runtime-directory", type=Path)
    parser.add_argument(
        "--agent-env-file",
        type=Path,
        help="private mode-0600 env file injected only into the parent agent",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("agent_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = (
        args.agent_command[1:]
        if args.agent_command[:1] == ["--"]
        else args.agent_command
    )
    try:
        return launch(
            manifest_path=args.manifest,
            ledger_path=args.ledger,
            profile=args.profile,
            agent_image=args.agent_image,
            agent_command=command,
            runtime_base=args.runtime_directory,
            agent_env_file=args.agent_env_file,
            dry_run=args.dry_run,
        )
    except (ConfigError, OSError) as error:
        print(f"hpc-agent-launch: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
