from __future__ import annotations

import json
import shlex

from hpc_tools import slurm, submissions
from hpc_tools.config import ConfigError, Profile

def render_install_script(
    *,
    missing_packages: list[str],
    modules: list[str],
    venv: str,
    cluster: str | None,
    partition: str,
    job_name: str,
    time: str,
    cpus_per_task: str,
    arch_guard: str | None,
    system_site_packages: bool,
    upgrade_pip: bool,
    install_packages: list[str] | None = None,
) -> str:
    packages_to_install = install_packages if install_packages is not None else missing_packages
    packages_expr = " ".join(shlex.quote(package) for package in packages_to_install)
    verify_packages = json.dumps(missing_packages)
    cluster_line = f"#SBATCH --clusters={cluster}\n" if cluster else ""
    venv_flags = "--system-site-packages" if system_site_packages else ""
    arch_guard_block = ""
    if arch_guard:
        arch_guard_block = (
            f'if [[ "${{VSC_ARCH_LOCAL}}" != "{arch_guard}" ]]; then\n'
            f'    echo "This script is intended for {arch_guard} nodes only; got VSC_ARCH_LOCAL=${{VSC_ARCH_LOCAL}}." >&2\n'
            "    exit 1\n"
            "fi\n\n"
        )
    upgrade_block = "python -m pip install --upgrade pip\n" if upgrade_pip else ""
    return (
        "#!/bin/bash -l\n"
        f"#SBATCH --job-name={job_name}\n"
        f"{cluster_line}"
        f"#SBATCH --partition={partition}\n"
        "#SBATCH --nodes=1\n"
        "#SBATCH --ntasks=1\n"
        f"#SBATCH --cpus-per-task={cpus_per_task}\n"
        f"#SBATCH --time={time}\n"
        "#SBATCH --output=%x-%j.out\n\n"
        "set -euo pipefail\n\n"
        "# Add the account at submission time with hpc submit --account <account>\n\n"
        "module purge\n"
        + "".join(f"module load {module_name}\n" for module_name in modules)
        + "\n"
        + arch_guard_block
        + 'BUILD_ROOT="${VSC_SCRATCH_NODE:-${TMPDIR:-/tmp}}/python-pkg-build-${SLURM_JOB_ID:-manual}"\n'
        + 'mkdir -p "${BUILD_ROOT}"\n'
        + 'export TMPDIR="${BUILD_ROOT}"\n'
        + 'export PIP_CACHE_DIR="${BUILD_ROOT}/pip-cache"\n'
        + 'trap \'rm -rf "${BUILD_ROOT}"\' EXIT\n\n'
        + f'VENV={shlex.quote(venv)}\n'
        + 'echo "Creating or updating venv ${VENV}"\n'
        + 'echo "Temporary build root ${TMPDIR}"\n'
        + f"python -m venv {venv_flags} \"${{VENV}}\"\n"
        + 'source "${VENV}/bin/activate"\n'
        + 'echo "Python executable $(python -c \'import sys; print(sys.executable)\')"\n'
        + 'echo "Python version $(python --version)"\n'
        + "module list\n"
        + upgrade_block
        + f"python -m pip install --no-cache-dir {packages_expr}\n\n"
        + "python - <<'HPC_TOOLS_PYTHON_VERIFY'\n"
        + "import importlib.util, sys\n"
        + f"packages = {verify_packages}\n"
        + "missing = []\n"
        + "print('\\nPackage status:')\n"
        + "for package in packages:\n"
        + "    status = 'OK' if importlib.util.find_spec(package) is not None else 'MISSING'\n"
        + "    print(f'{package} {status}')\n"
        + "    if status == 'MISSING':\n"
        + "        missing.append(package)\n"
        + "print('\\nPython executable:')\n"
        + "print(sys.executable)\n"
        + "print('\\nPython sys.path:')\n"
        + "for entry in sys.path:\n"
        + "    print(entry)\n"
        + "sys.exit(1 if missing else 0)\n"
        + "HPC_TOOLS_PYTHON_VERIFY\n"
    )

def build_stage_script_command(*, directory: str, remote_name: str, contents: str) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    quoted_name = shlex.quote(remote_name)
    delimiter = "HPC_TOOLS_PYTHON_INSTALL_SCRIPT"
    return (
        f"mkdir -p {remote_dir} && cd {remote_dir} && "
        f"cat > {quoted_name} <<'{delimiter}'\n"
        f"{contents}"
        f"{delimiter}\n"
        f"chmod +x {quoted_name}"
    )

def build_quote_args(
    *,
    remote_script_path: str,
    account: str,
    cluster: str | None,
    partition: str | None,
    reservation: str | None,
    time: str | None,
    nodes: str | None,
    cpus_per_task: str | None,
) -> list[str]:
    args = ["sbatch", remote_script_path, "-A", account]
    if cluster:
        args.extend(["-M", cluster])
    if partition:
        args.extend(["-p", partition])
    if reservation:
        args.extend(["--reservation", reservation])
    if time:
        args.extend(["-t", time])
    if nodes:
        args.extend(["-N", nodes])
    if cpus_per_task:
        args.extend(["-c", cpus_per_task])
    return args

def build_quote_command(base_command: str, quote_args: list[str]) -> str:
    if not quote_args:
        raise ConfigError("quote requires arguments")
    if quote_args[0] not in {"sbatch", "srun", "salloc"}:
        raise ConfigError("quote first argument must be one of: sbatch, srun, salloc")
    if "-A" not in quote_args and "--account" not in quote_args:
        raise ConfigError("quote requires a Slurm account option: -A <account> or --account <account>")
    return " ".join([base_command, *(shlex.quote(part) for part in quote_args)])

def _remote_script_path(directory: str, remote_name: str) -> str:
    if directory in {".", ""}:
        return remote_name
    separator = "" if directory.endswith("/") else "/"
    return f"{directory}{separator}{remote_name}"

def _log_submission(
    *,
    profile: Profile,
    remote_directory: str,
    remote_name: str,
    command: str,
    overrides: dict[str, str],
    sbatch_output: str,
) -> None:
    try:
        job_id, cluster = submissions.parse_sbatch_submission(sbatch_output)
    except ValueError as error:
        print(f"hpc: warning: {error}; submission was not logged", file=sys.stderr)
        return
    event = submissions.submitted_event(
        profile=profile.name,
        job_id=job_id,
        cluster=cluster or overrides.get("cluster") or profile.default_cluster,
        remote_directory=remote_directory,
        jobscript=remote_name,
        submit_command=command,
        overrides=overrides,
    )
    submissions.append_event(event)

