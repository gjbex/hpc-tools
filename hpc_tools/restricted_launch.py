from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from hpc_tools import __version__, delegation
from hpc_tools.config import (
    ConfigError,
    default_config_path,
    load_config,
    resolve_profile,
)
from hpc_tools.mcp_bridge import SOCKET_ENV_VAR, readiness_path

CONTAINER_SOCKET_DIRECTORY = "/run/hpc-tools-mcp"
FORBIDDEN_COMMANDS = (
    "ssh",
    "scp",
    "sftp",
    "sbatch",
    "scancel",
    "squeue",
    "sacct",
    "scontrol",
    "srun",
    "salloc",
    "munge",
    "unmunge",
)
REQUEUE_SIGNAL = signal.SIGUSR1
TERMINATION_SIGNALS = (signal.SIGTERM, signal.SIGINT)
MAX_PROMPT_BYTES = 1024 * 1024
MAX_ENVIRONMENT_FILE_BYTES = 64 * 1024
NETWORK_MODE_ENV_VAR = "HPC_TOOLS_AGENT_NETWORK_MODE"
AGENT_CREDENTIAL_ENV_NAMES = frozenset({"OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"})
NETWORK_ENV_NAMES = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "ssl_cert_file",
        "ssl_cert_dir",
        "requests_ca_bundle",
        "curl_ca_bundle",
    }
)


@dataclass(frozen=True)
class AgentArtifacts:
    directory: Path
    provenance_path: Path
    prompt_path: Path | None
    event_log: Path
    diagnostic_log: Path


@dataclass(frozen=True)
class NetworkEnvironmentEvidence:
    supplied: bool
    sha256: str | None

    def public_summary(self) -> dict[str, bool | str | None]:
        return {"supplied": self.supplied, "sha256": self.sha256}


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
            f"{NETWORK_MODE_ENV_VAR}={manifest.network.mode.value}",
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
    manifest_path: Path | None = None,
    manifest_template_path: Path | None = None,
    manifest_output_path: Path | None = None,
    ledger_path: Path,
    profile: str,
    agent_image: Path,
    agent_image_sha256: str,
    agent_command: list[str],
    runtime_base: Path | None = None,
    agent_env_file: Path | None = None,
    network_env_file: Path | None = None,
    prompt_file: Path | None = None,
    config_path: Path | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> int:
    expected_agent_image_sha256 = _validated_sha256(
        agent_image_sha256,
        "agent image SHA-256",
    )
    parent_job_id = os.environ.get("SLURM_JOB_ID")
    if not parent_job_id:
        raise ConfigError("hpc-agent-launch must run inside a Slurm allocation")
    manifest, materialization, pending_manifest_payload = _select_manifest(
        manifest_path=manifest_path,
        manifest_template_path=manifest_template_path,
        manifest_output_path=manifest_output_path,
        profile=profile,
        parent_job_id=parent_job_id,
        dry_run=dry_run,
        now=now,
    )
    selected_config_path = (
        config_path if config_path is not None else default_config_path()
    ).expanduser().resolve()
    selected_profile = resolve_profile(
        load_config(str(selected_config_path)),
        profile,
    )
    delegation.require_credit_configuration(
        manifest,
        sam_quote_command=selected_profile.sam_quote_command,
        sam_quote_format=selected_profile.sam_quote_format,
    )
    config_sha256 = hashlib.sha256(selected_config_path.read_bytes()).hexdigest()
    ledger_path = _absolute_literal(ledger_path, "ledger")
    policy = _require_policy(manifest)
    _prepare_policy_paths(policy)
    if pending_manifest_payload is None:
        _ensure_private_file(manifest.source_path, "delegation manifest")
    manifest_private_paths = [manifest.source_path]
    if materialization is not None:
        manifest_private_paths.append(materialization.template_path)
    _ensure_not_exposed(
        (
            *manifest_private_paths,
            ledger_path,
            selected_config_path,
            policy.state_root,
        ),
        (policy.work_root, policy.output_root, *policy.input_roots),
    )
    selected_credential_file = None
    if agent_env_file is not None:
        selected_credential_file = _absolute_literal(
            agent_env_file, "agent environment file"
        )
        _ensure_private_file(selected_credential_file, "agent environment file")
        _ensure_not_exposed(
            (selected_credential_file,),
            (policy.work_root, policy.output_root, *policy.input_roots),
        )
    selected_network_file = None
    if network_env_file is not None:
        selected_network_file = _absolute_literal(
            network_env_file, "network environment file"
        )
        _ensure_private_file(selected_network_file, "network environment file")
        _ensure_not_exposed(
            (selected_network_file,),
            (policy.work_root, policy.output_root, *policy.input_roots),
        )
    selected_prompt_file = None
    if prompt_file is not None:
        selected_prompt_file = _absolute_literal(prompt_file, "agent prompt file")
        _ensure_private_file(selected_prompt_file, "agent prompt file")
        if selected_prompt_file.stat().st_size > MAX_PROMPT_BYTES:
            raise ConfigError(
                f"agent prompt file exceeds the {MAX_PROMPT_BYTES}-byte limit"
            )
        _ensure_not_exposed(
            (selected_prompt_file,),
            (policy.work_root, policy.output_root, *policy.input_roots),
        )
    image = _secure_file(agent_image, "agent image")
    if stat.S_IMODE(image.stat().st_mode) & 0o022:
        raise ConfigError("agent image must not be group- or world-writable")
    verified_agent_image_sha256 = _sha256_file(image)
    if verified_agent_image_sha256 != expected_agent_image_sha256:
        raise ConfigError(
            "agent image SHA-256 mismatch: "
            f"expected {expected_agent_image_sha256}, "
            f"got {verified_agent_image_sha256}"
        )
    if not agent_command:
        raise ConfigError("an agent command is required after --")
    _validate_agent_command(agent_command)

    selected_runtime_base = runtime_base or _default_runtime_base()
    selected_runtime_base = _secure_directory(
        selected_runtime_base, "runtime base", private=True
    )
    if pending_manifest_payload is not None and not dry_run:
        assert materialization is not None
        delegation.publish_materialized_manifest(
            materialization.manifest_path,
            pending_manifest_payload,
        )
        _ensure_private_file(materialization.manifest_path, "delegation manifest")
    ledger = delegation.DelegationLedger(ledger_path)
    authority = None
    if dry_run:
        delegation.require_controller_authority(
            selected_profile.capabilities,
            operation="agent.controller.start",
        )
    else:
        ledger.register(manifest)
        authority = ledger.controller_authority_or_none(manifest)
        if authority is None:
            authority = ledger.capture_controller_authority(
                manifest,
                policy=selected_profile.capabilities,
                config_path=selected_config_path,
                config_sha256=config_sha256,
                quote_format=selected_profile.sam_quote_format,
            )
        delegation.require_controller_authority(
            authority.policy,
            operation="agent.controller.continue",
        )
    with tempfile.TemporaryDirectory(
        prefix=f"hpc-tools-{parent_job_id}-", dir=selected_runtime_base
    ) as temporary:
        socket_directory = Path(temporary)
        os.chmod(socket_directory, 0o700)
        socket_path = socket_directory / "server.sock"
        materialized_env_file, network_environment = _materialize_agent_environment(
            socket_directory,
            credential_file=selected_credential_file,
            network_file=selected_network_file,
        )
        container_command = build_apptainer_command(
            manifest=manifest,
            agent_image=image,
            socket_directory=socket_directory,
            agent_command=agent_command,
            agent_env_file=materialized_env_file,
        )
        if dry_run:
            rendered = subprocess.list2cmdline(container_command)
            if selected_prompt_file is not None:
                rendered += f" < {shlex.quote(str(selected_prompt_file))}"
            print(rendered)
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
        assert authority is not None
        controller = ledger.begin_controller(
            manifest, restart_count=_controller_restart_count()
        )
        try:
            artifacts = _prepare_agent_artifacts(
                manifest=manifest,
                policy=policy,
                generation=int(controller["generation"]),
                prompt_file=selected_prompt_file,
                agent_image=image,
                expected_agent_image_sha256=expected_agent_image_sha256,
                verified_agent_image_sha256=verified_agent_image_sha256,
                agent_command=agent_command,
                controller_authority=authority,
                network_environment=network_environment,
                manifest_materialization=materialization,
            )
            ledger.record_controller_artifacts(
                manifest,
                generation=int(controller["generation"]),
                artifact_directory=str(artifacts.directory),
                provenance_path=str(artifacts.provenance_path),
                event_log=str(artifacts.event_log),
                diagnostic_log=str(artifacts.diagnostic_log),
                manifest_materialization=(
                    materialization.public_summary()
                    if materialization is not None
                    else None
                ),
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
                "--config",
                str(selected_config_path),
                "--delegation",
                str(manifest.source_path),
                "--ledger",
                str(ledger_path),
            ]
            server_environment = _sanitized_server_environment(parent_job_id)
            bridge = subprocess.Popen(bridge_command, env=server_environment)
        except (OSError, ConfigError, delegation.DelegationError) as error:
            ledger.finalize_controller(
                manifest, reason=f"launcher setup failed: {error}"
            )
            raise
        pending_signal: list[int] = []
        previous_handlers: dict[int, signal.Handlers] = {}

        def request_shutdown(signum: int, _frame: object) -> None:
            pending_signal.append(signum)

        for signum in (REQUEUE_SIGNAL, *TERMINATION_SIGNALS):
            previous_handlers[signum] = signal.signal(signum, request_shutdown)
        try:
            prompt_handle: IO[bytes] | None = None
            event_handle: IO[bytes] | None = None
            diagnostic_handle: IO[bytes] | None = None
            try:
                _wait_for_socket(socket_path, bridge)
                prompt_handle = (
                    artifacts.prompt_path.open("rb")
                    if artifacts.prompt_path is not None
                    else None
                )
                event_handle = artifacts.event_log.open("wb")
                diagnostic_handle = artifacts.diagnostic_log.open("wb")
                agent = subprocess.Popen(
                    container_command,
                    env=_sanitized_apptainer_environment(),
                    stdin=prompt_handle,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except (OSError, ConfigError) as error:
                for handle in (event_handle, diagnostic_handle, prompt_handle):
                    if handle is not None:
                        handle.close()
                ledger.finalize_controller(
                    manifest, reason=f"agent startup failed: {error}"
                )
                raise
            assert event_handle is not None
            assert diagnostic_handle is not None
            assert agent.stdout is not None
            assert agent.stderr is not None
            pump_errors: list[Exception] = []
            pumps = [
                threading.Thread(
                    target=_tee_stream,
                    args=(agent.stdout, event_handle, sys.stdout, pump_errors),
                    daemon=True,
                ),
                threading.Thread(
                    target=_tee_stream,
                    args=(agent.stderr, diagnostic_handle, sys.stderr, pump_errors),
                    daemon=True,
                ),
            ]
            for pump in pumps:
                pump.start()
            while agent.poll() is None and not pending_signal and not pump_errors:
                time.sleep(0.1)
            if pump_errors and not pending_signal:
                _terminate_process(agent, timeout=5)
                _finish_logged_process(
                    pumps,
                    event_handle,
                    diagnostic_handle,
                    prompt_handle,
                )
                reason = f"agent log capture failed: {pump_errors[0]}"
                ledger.finalize_controller(manifest, reason=reason)
                raise ConfigError(reason)
            if pending_signal:
                signum = pending_signal[0]
                reason = signal.Signals(signum).name
                ledger.begin_draining(manifest, reason=reason)
                _terminate_process(agent, timeout=5)
                _finish_logged_process(
                    pumps,
                    event_handle,
                    diagnostic_handle,
                    prompt_handle,
                )
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
            _finish_logged_process(
                pumps,
                event_handle,
                diagnostic_handle,
                prompt_handle,
            )
            if pump_errors:
                reason = f"agent log capture failed: {pump_errors[0]}"
                ledger.finalize_controller(manifest, reason=reason)
                raise ConfigError(reason)
            active = len(ledger.owned_jobs_for_cleanup(manifest))
            reason = (
                "normal exit with active delegated jobs"
                if returncode == 0 and active
                else "normal exit"
                if returncode == 0
                else f"agent exited {returncode}"
            )
            ledger.finalize_controller(manifest, reason=reason)
            return returncode
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            if bridge.poll() is None:
                _terminate_process(bridge, timeout=5)


def _select_manifest(
    *,
    manifest_path: Path | None,
    manifest_template_path: Path | None,
    manifest_output_path: Path | None,
    profile: str,
    parent_job_id: str,
    dry_run: bool,
    now: datetime | None,
) -> tuple[
    delegation.DelegationManifest,
    delegation.ManifestMaterialization | None,
    bytes | None,
]:
    if manifest_path is not None and manifest_template_path is not None:
        raise ConfigError("--manifest and --manifest-template are mutually exclusive")
    if manifest_path is None and manifest_template_path is None:
        raise ConfigError("either --manifest or --manifest-template is required")
    if manifest_template_path is None:
        if manifest_output_path is not None:
            raise ConfigError("--manifest-output requires --manifest-template")
        assert manifest_path is not None
        return (
            delegation.load_manifest(
                manifest_path,
                expected_profile=profile,
                expected_parent_job_id=parent_job_id,
                now=now,
            ),
            None,
            None,
        )
    if manifest_output_path is None:
        raise ConfigError("--manifest-template requires --manifest-output")
    restart_count = _controller_restart_count()
    if restart_count:
        manifest, evidence = delegation.verify_materialized_manifest(
            manifest_template_path,
            manifest_output_path,
            expected_profile=profile,
            parent_job_id=parent_job_id,
            now=now,
        )
        return manifest, evidence, None
    manifest, evidence, payload = delegation.prepare_manifest_template(
        manifest_template_path,
        manifest_output_path,
        expected_profile=profile,
        parent_job_id=parent_job_id,
        now=now,
    )
    return manifest, evidence, payload


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
    authority = ledger.controller_authority(manifest)
    delegation.require_controller_authority(
        authority.policy,
        operation="agent.controller.requeue",
    )
    try:
        ledger.request_requeue(manifest)
    except delegation.DelegationError as error:
        ledger.finalize_controller(manifest, reason=f"timeout-requeue-failed: {error}")
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
    authority = ledger.controller_authority(manifest)
    delegation.require_controller_authority(
        authority.policy,
        operation="agent.cleanup.register",
    )
    reaper = shutil.which("hpc-agent-reap")
    if not reaper:
        raise ConfigError("hpc-agent-reap is not available in the host PATH")
    reaper_path = _secure_file(
        Path(reaper).resolve(), "host cleanup executable", executable=True
    )
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
            raise ConfigError(
                f"existing cleanup script has unexpected contents: {path}"
            )
        os.chmod(path, 0o500)
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o500)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _validate_agent_command(agent_command: list[str]) -> None:
    if agent_command != ["codex-agent", "-"]:
        raise ConfigError(
            "restricted agent command must be exactly 'codex-agent -'; "
            "configuration and sandbox overrides are not accepted"
        )


def _materialize_agent_environment(
    runtime_directory: Path,
    *,
    credential_file: Path | None,
    network_file: Path | None,
) -> tuple[Path | None, NetworkEnvironmentEvidence]:
    credentials = (
        _parse_environment_file(
            credential_file,
            label="agent environment file",
            allowed_names=AGENT_CREDENTIAL_ENV_NAMES,
        )
        if credential_file is not None
        else {}
    )
    if len(credentials) > 1:
        raise ConfigError(
            "agent environment file must contain exactly one supported credential"
        )
    network = (
        _parse_environment_file(
            network_file,
            label="network environment file",
            allowed_names=NETWORK_ENV_NAMES,
        )
        if network_file is not None
        else {}
    )
    network_payload = _environment_payload(network)
    evidence = NetworkEnvironmentEvidence(
        supplied=network_file is not None,
        sha256=(
            hashlib.sha256(network_payload).hexdigest()
            if network_file is not None
            else None
        ),
    )
    combined = credentials | network
    if not combined:
        return None, evidence
    destination = runtime_directory / "agent-environment.env"
    _write_private_bytes(destination, _environment_payload(combined))
    return destination, evidence


def _parse_environment_file(
    path: Path,
    *,
    label: str,
    allowed_names: frozenset[str],
) -> dict[str, str]:
    _ensure_private_file(path, label)
    payload = path.read_bytes()
    if len(payload) > MAX_ENVIRONMENT_FILE_BYTES:
        raise ConfigError(
            f"{label} exceeds the {MAX_ENVIRONMENT_FILE_BYTES}-byte limit"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"{label} must be UTF-8") from error
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not name or not value:
            raise ConfigError(f"invalid {label} entry on line {line_number}")
        if name not in allowed_names:
            raise ConfigError(
                f"unsupported {label} variable on line {line_number}: {name}"
            )
        if name in values:
            raise ConfigError(f"duplicate {label} variable: {name}")
        if "\x00" in value:
            raise ConfigError(f"invalid NUL byte in {label} variable: {name}")
        values[name] = value
    if not values:
        raise ConfigError(f"{label} contains no supported variables")
    return values


def _environment_payload(values: dict[str, str]) -> bytes:
    return "".join(
        f"{name}={values[name]}\n" for name in sorted(values)
    ).encode("utf-8")


def _prepare_agent_artifacts(
    *,
    manifest: delegation.DelegationManifest,
    policy: delegation.FilesystemPolicy,
    generation: int,
    prompt_file: Path | None,
    agent_image: Path,
    expected_agent_image_sha256: str,
    verified_agent_image_sha256: str,
    agent_command: list[str],
    controller_authority: delegation.ControllerAuthority,
    network_environment: NetworkEnvironmentEvidence | None = None,
    manifest_materialization: delegation.ManifestMaterialization | None = None,
) -> AgentArtifacts:
    attempts_root = policy.state_root / "agent-attempts"
    _mkdir_private(attempts_root, "agent attempt root")
    attempt_directory = attempts_root / f"generation-{generation}"
    _reject_existing_symlinks(
        attempt_directory, "agent attempt directory", require_leaf=False
    )
    try:
        attempt_directory.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ConfigError(
            f"agent attempt artifacts already exist: {attempt_directory}"
        ) from error
    _secure_directory(attempt_directory, "agent attempt directory", private=True)

    manifest_contents = manifest.source_path.read_bytes()
    manifest_snapshot = attempt_directory / "delegation.toml"
    _write_private_bytes(manifest_snapshot, manifest_contents)

    prompt_snapshot = None
    prompt_sha256 = None
    if prompt_file is not None:
        prompt_contents = prompt_file.read_bytes()
        prompt_snapshot = attempt_directory / "task.md"
        _write_private_bytes(prompt_snapshot, prompt_contents)
        prompt_sha256 = hashlib.sha256(prompt_contents).hexdigest()

    codex_version_output = _read_image_text(policy, agent_image, ["codex", "--version"])
    codex_version = codex_version_output.strip() if codex_version_output else None
    codex_config = _read_image_text(
        policy,
        agent_image,
        [
            "cat",
            f"/opt/hpc-tools/config/{manifest.network.mode.value}.toml",
        ],
    )
    codex_config_snapshot = None
    codex_config_sha256 = None
    if codex_config is not None:
        encoded_config = codex_config.encode("utf-8")
        codex_config_snapshot = attempt_directory / "codex-config.toml"
        _write_private_bytes(codex_config_snapshot, encoded_config)
        codex_config_sha256 = hashlib.sha256(encoded_config).hexdigest()

    event_log = attempt_directory / "codex-events.jsonl"
    diagnostic_log = attempt_directory / "codex-stderr.log"
    _write_private_bytes(event_log, b"")
    _write_private_bytes(diagnostic_log, b"")
    provenance_path = attempt_directory / "provenance.json"
    provenance = {
        "format_version": 5,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "delegation_id": manifest.identifier,
        "controller_generation": generation,
        "parent_job_id": manifest.parent_job_id,
        "controller_authority": controller_authority.public_summary(
            include_config_path=True
        ),
        "network": manifest.network.public_summary()
        | {
            "environment": (
                network_environment or NetworkEnvironmentEvidence(False, None)
            ).public_summary()
        },
        "agent_command": agent_command,
        "prompt": (
            {
                "source_path": str(prompt_file),
                "snapshot_path": str(prompt_snapshot),
                "sha256": prompt_sha256,
            }
            if prompt_file is not None
            else None
        ),
        "manifest": {
            "source_path": str(manifest.source_path),
            "snapshot_path": str(manifest_snapshot),
            "sha256": hashlib.sha256(manifest_contents).hexdigest(),
            "materialization": (
                manifest_materialization.public_summary()
                if manifest_materialization is not None
                else {"mode": "pre-materialized", "template": None}
            ),
        },
        "agent_image": {
            "path": str(agent_image),
            "expected_sha256": expected_agent_image_sha256,
            "sha256": verified_agent_image_sha256,
        },
        "codex": {
            "version": codex_version,
            "config_snapshot_path": (
                str(codex_config_snapshot) if codex_config_snapshot else None
            ),
            "config_sha256": codex_config_sha256,
        },
        "hpc_tools": {
            "version": __version__,
            "source_revision": _git_revision(Path(__file__).resolve().parents[1]),
        },
        "work_source": _git_revision(policy.work_root),
        "logs": {
            "events": str(event_log),
            "diagnostics": str(diagnostic_log),
        },
    }
    _write_private_bytes(
        provenance_path,
        (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return AgentArtifacts(
        directory=attempt_directory,
        provenance_path=provenance_path,
        prompt_path=prompt_snapshot,
        event_log=event_log,
        diagnostic_log=diagnostic_log,
    )


def _write_private_bytes(path: Path, contents: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(contents)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_sha256(value: str, label: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ConfigError(
            f"{label} must be a lowercase 64-character hexadecimal digest"
        )
    return value


def _read_image_text(
    policy: delegation.FilesystemPolicy,
    image: Path,
    command: list[str],
) -> str | None:
    invocation = _base_apptainer_command(policy.apptainer_path)
    invocation.extend([str(image), *command])
    try:
        completed = subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            text=True,
            env=_sanitized_apptainer_environment(),
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _git_revision(path: Path) -> dict[str, object] | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        revision = subprocess.run(
            [git, "-C", str(path), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        status = subprocess.run(
            [git, "-C", str(path), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if revision.returncode != 0:
        return None
    return {
        "commit": revision.stdout.strip(),
        "dirty": status.returncode != 0 or bool(status.stdout),
    }


def _tee_stream(
    source: IO[bytes],
    artifact: IO[bytes],
    target: IO[str],
    errors: list[Exception],
) -> None:
    try:
        target_buffer = getattr(target, "buffer", None)
        while chunk := source.read(64 * 1024):
            artifact.write(chunk)
            artifact.flush()
            if target_buffer is not None:
                target_buffer.write(chunk)
                target_buffer.flush()
            else:
                target.write(chunk.decode("utf-8", errors="replace"))
                target.flush()
    except (OSError, ValueError) as error:
        errors.append(error)


def _finish_logged_process(
    pumps: list[threading.Thread],
    event_handle: IO[bytes],
    diagnostic_handle: IO[bytes],
    prompt_handle: IO[bytes] | None,
) -> None:
    for pump in pumps:
        pump.join()
    event_handle.close()
    diagnostic_handle.close()
    if prompt_handle is not None:
        prompt_handle.close()


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
        'if command -v "$command" >/dev/null 2>&1; then '
        'echo "forbidden command in agent image: $command" >&2; exit 42; fi; done; '
        "for path in /run/munge /var/run/munge /etc/slurm /etc/ssh /root/.ssh; do "
        'if [ -e "$path" ]; then '
        'echo "forbidden credential or configuration path visible: $path" >&2; '
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
    ready = readiness_path(path)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if bridge.poll() is not None:
            raise ConfigError(
                f"host MCP bridge exited before startup with return code {bridge.returncode}"
            )
        try:
            marker = ready.read_text(encoding="ascii").strip()
            if (
                stat.S_ISSOCK(path.stat().st_mode)
                and stat.S_ISREG(ready.stat().st_mode)
                and marker == str(bridge.pid)
            ):
                return
        except (OSError, UnicodeError):
            pass
        time.sleep(0.05)
    raise ConfigError("timed out waiting for the host MCP bridge readiness marker")


def _sanitized_apptainer_environment() -> dict[str, str]:
    allowed_names = {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "LANG",
        "LANGUAGE",
        "TERM",
        "TZ",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
        "LD_LIBRARY_PATH",
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
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "CREDENTIAL",
        "API_KEY",
        "ACCESS_KEY",
        "COOKIE",
    )
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if key in blocked_names or any(
            fragment in upper for fragment in blocked_fragments
        ):
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
    manifest_group = parser.add_mutually_exclusive_group(required=True)
    manifest_group.add_argument("--manifest", type=Path)
    manifest_group.add_argument("--manifest-template", type=Path)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="private mode-0600 output used with --manifest-template",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--agent-image", type=Path, required=True)
    parser.add_argument(
        "--agent-image-sha256",
        required=True,
        help="reviewed lowercase SHA-256 digest of --agent-image",
    )
    parser.add_argument("--runtime-directory", type=Path)
    parser.add_argument(
        "--agent-env-file",
        type=Path,
        help=(
            "private mode-0600 file containing exactly one supported parent-agent "
            "credential"
        ),
    )
    parser.add_argument(
        "--network-env-file",
        type=Path,
        help=(
            "private mode-0600 allowlisted proxy and CA environment for the "
            "parent agent"
        ),
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help=("private mode-0600 prompt file to snapshot and pass to the parent agent"),
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
            manifest_template_path=args.manifest_template,
            manifest_output_path=args.manifest_output,
            ledger_path=args.ledger,
            profile=args.profile,
            agent_image=args.agent_image,
            agent_image_sha256=args.agent_image_sha256,
            agent_command=command,
            runtime_base=args.runtime_directory,
            agent_env_file=args.agent_env_file,
            network_env_file=args.network_env_file,
            prompt_file=args.prompt_file,
            config_path=args.config,
            dry_run=args.dry_run,
        )
    except (ConfigError, OSError) as error:
        print(f"hpc-agent-launch: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
