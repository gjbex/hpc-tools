from __future__ import annotations

import re
import shlex

from hpc_tools.config import ConfigError


SQUEUE_FORMAT = "%.18i %.9P %.40j %.8u %.2t %.10M %.10l %.6D %R"
SQUEUE_JOB_FORMAT = "%.18i %.9P %.32j %.8T %.10M %.10l %.6D %R"
SACCT_FORMAT = "JobID,JobName%24,Partition,Account,State,ExitCode,Elapsed"
SLURM_LIMIT_CONFIG_PATTERN = (
    "ClusterName|MaxArraySize|MaxJobCount|MaxSubmitJobs|"
    "MaxTasksPerNode|SchedulerParameters"
)
SLURM_QOS_FORMAT = (
    "Name,MaxJobsPU,MaxSubmitJobsPU,MaxTRESPU,GrpJobs,"
    "GrpSubmitJobs,GrpTRES,MaxWall"
)
SLURM_ASSOC_FORMAT = (
    "Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,"
    "MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES"
)
SLURM_JOB_ID_PATTERN = re.compile(
    r"\d+(?:\+\d+)?(?:_\d+)?(?:\.[A-Za-z0-9_-]+)?"
)
SLURM_CLUSTER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def queue_state_command(queue_command: str) -> str:
    return queue_command


def squeue_user_command(cluster: str | None = None) -> str:
    parts = ["squeue"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.extend(["-u", "$USER", "-o", SQUEUE_FORMAT])
    return _quote_command_preserving_user(parts)


def squeue_job_command(jobid: str, cluster: str | None = None) -> str:
    parts = ["squeue"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.extend(["-j", jobid, "-o", SQUEUE_JOB_FORMAT])
    return _quote_command(parts)


def cancel_command(jobid: str, cluster: str | None = None) -> str:
    if not SLURM_JOB_ID_PATTERN.fullmatch(jobid):
        raise ConfigError(
            "job ID must be numeric, optionally followed by a heterogeneous "
            "component, one array task, or one job step"
        )
    if cluster and not SLURM_CLUSTER_PATTERN.fullmatch(cluster):
        raise ConfigError("cluster must be one Slurm cluster name")
    parts = ["scancel"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.append(jobid)
    return _quote_command(parts)


def slurm_limits_command(
    *,
    cluster: str | None = None,
    partition: str | None = None,
    qos: str | None = None,
) -> str:
    commands = [
        _section_command(
            "controller",
            f"{_quote_command(_with_cluster(['scontrol', 'show', 'config'], cluster))} "
            f"| grep -Ei {shlex.quote(SLURM_LIMIT_CONFIG_PATTERN)} || true",
        ),
        _section_command(
            "partitions",
            _quote_command(_with_cluster(["scontrol", "show", "partition"], cluster) + ([partition] if partition else [])),
        ),
        _section_command(
            "partition-summary",
            _quote_command(
                _with_cluster(["sinfo"], cluster)
                + (["-p", partition] if partition else [])
                + ["-o", "%P|%a|%l|%D|%c|%m|%G|%f"]
            ),
        ),
        _section_command(
            "partition-nodes",
            f"{_quote_command(_with_cluster(['sinfo'], cluster) + (['-p', partition] if partition else []) + ['-N', '-o', '%N|%c|%m|%G|%t'])} "
            "| sed -n '1,40p'",
        ),
        _section_command(
            "qos",
            _quote_command(
                ["sacctmgr", "-n", "-P", "show", "qos"]
                + ([qos] if qos else [])
                + [f"format={SLURM_QOS_FORMAT}"]
            )
            + " 2>/dev/null || true",
        ),
        _section_command(
            "associations",
            _quote_command_preserving_shell_vars(
                ["sacctmgr", "-n", "-P", "show", "assoc", "where"]
                + ([f"cluster={cluster}"] if cluster else [])
                + ["user=$USER"]
                + ([f"partition={partition}"] if partition else [])
                + [f"format={SLURM_ASSOC_FORMAT}"]
            )
            + " 2>/dev/null || true",
        ),
    ]
    return "; ".join(commands)


SUBMIT_OPTION_NAMES = {
    "account": "--account",
    "array": "--array",
    "cluster": "--clusters",
    "cpus_per_task": "--cpus-per-task",
    "dependency": "--dependency",
    "error": "--error",
    "export": "--export",
    "gpu_bind": "--gpu-bind",
    "gpus": "--gpus",
    "gpus_per_node": "--gpus-per-node",
    "gpus_per_task": "--gpus-per-task",
    "gres": "--gres",
    "job_name": "--job-name",
    "mem": "--mem",
    "mem_per_cpu": "--mem-per-cpu",
    "nodes": "--nodes",
    "ntasks": "--ntasks",
    "ntasks_per_node": "--ntasks-per-node",
    "output": "--output",
    "partition": "--partition",
    "reservation": "--reservation",
    "time": "--time",
}


def submit_command(
    jobscript: str,
    *,
    directory: str = ".",
    test_only: bool = False,
    overrides: dict[str, str | None] | None = None,
) -> str:
    sbatch_parts = ["sbatch"]
    if test_only:
        sbatch_parts.append("--test-only")
    if overrides:
        for name, value in overrides.items():
            if value is None:
                continue
            option = SUBMIT_OPTION_NAMES[name]
            sbatch_parts.extend([option, value])
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


def _quote_command_preserving_shell_vars(parts: list[str]) -> str:
    quoted = []
    for part in parts:
        quoted.append(part if "$" in part else shlex.quote(part))
    return " ".join(quoted)


def _with_cluster(parts: list[str], cluster: str | None) -> list[str]:
    if not cluster:
        return parts
    return [parts[0], "-M", cluster, *parts[1:]]


def _section_command(title: str, command: str) -> str:
    return f"printf '\\n## {title}\\n'; {command}"
