from __future__ import annotations

import shlex


SQUEUE_FORMAT = "%.18i %.9P %.40j %.8u %.2t %.10M %.10l %.6D %R"
SACCT_FORMAT = "JobID,JobName%24,Partition,Account,State,ExitCode,Elapsed"


def queue_state_command(queue_command: str) -> str:
    return queue_command


def squeue_user_command(cluster: str | None = None) -> str:
    parts = ["squeue"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.extend(["-u", "$USER", "-o", SQUEUE_FORMAT])
    return _quote_command_preserving_user(parts)


def submit_command(jobscript: str, *, directory: str = ".", test_only: bool = False) -> str:
    sbatch_parts = ["sbatch"]
    if test_only:
        sbatch_parts.append("--test-only")
    sbatch_parts.append(jobscript)
    return f"cd {_quote_remote_path_expression(directory)} && {_quote_command(sbatch_parts)}"


def sacct_command(jobid: str, cluster: str | None = None) -> str:
    parts = ["sacct"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.extend(["-j", jobid, f"--format={SACCT_FORMAT}"])
    return _quote_command(parts)


def _quote_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _quote_remote_path_expression(path: str) -> str:
    if path.startswith("$") or path.startswith("~"):
        return path
    return shlex.quote(path)


def _quote_command_preserving_user(parts: list[str]) -> str:
    quoted = []
    for part in parts:
        quoted.append(part if part == "$USER" else shlex.quote(part))
    return " ".join(quoted)
