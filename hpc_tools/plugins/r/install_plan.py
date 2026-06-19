from __future__ import annotations

import json
import shlex

from hpc_tools import slurm, submissions
from hpc_tools.config import ConfigError, Profile

DEFAULT_LIBRARY_ROOT_TEMPLATE = "${VSC_DATA}/Rlibs/${VSC_OS_LOCAL}/${VSC_ARCH_LOCAL}/R-${EBVERSIONR}"

def render_install_script(
    *,
    missing_packages: list[str],
    module: str,
    cran_bundle: str | None,
    bioc_bundle: str | None,
    cluster: str | None,
    partition: str,
    job_name: str,
    time: str,
    cpus_per_task: str,
    library_root_template: str,
    arch_guard: str | None,
    archive_packages: dict[str, str],
    extra_repos: dict[str, str],
) -> str:
    modules = [module, *(bundle for bundle in (cran_bundle, bioc_bundle) if bundle)]
    live_packages = [package for package in missing_packages if package not in archive_packages]
    archive_install_blocks = []
    for package in missing_packages:
        if package not in archive_packages:
            continue
        archive_install_blocks.append(
            "\n".join(
                [
                    f'if (!requireNamespace({json.dumps(package)}, quietly = TRUE)) {{',
                    "  install.packages(",
                    f"    {json.dumps(archive_packages[package])},",
                    '    repos = NULL, type = "source", dependencies = TRUE',
                    "  )",
                    "}",
                ]
            )
        )

    repo_entries = ['CRAN = "https://cloud.r-project.org"']
    for name, url in extra_repos.items():
        repo_entries.append(f"{name} = {json.dumps(url)}")
    repos_vector = "c(" + ", ".join(repo_entries) + ")"
    live_packages_expr = ", ".join(json.dumps(package) for package in live_packages)
    verify_packages_expr = ", ".join(json.dumps(package) for package in missing_packages)
    cluster_line = f"#SBATCH --clusters={cluster}\n" if cluster else ""
    arch_guard_block = ""
    if arch_guard:
        arch_guard_block = (
            f'if [[ "${{VSC_ARCH_LOCAL}}" != "{arch_guard}" ]]; then\n'
            f'    echo "This script is intended for {arch_guard} nodes only; got VSC_ARCH_LOCAL=${{VSC_ARCH_LOCAL}}." >&2\n'
            "    exit 1\n"
            "fi\n\n"
        )
    install_live_block = (
        f"install_if_missing(c({live_packages_expr}), repos = repos)\n" if live_packages else ""
    )
    archive_block = "\n\n".join(archive_install_blocks)
    if archive_block:
        archive_block += "\n"

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
        'if [[ -z "${VSC_DATA:-}" || -z "${VSC_OS_LOCAL:-}" || -z "${VSC_ARCH_LOCAL:-}" || -z "${EBVERSIONR:-}" ]]; then\n'
        '    echo "Expected VSC_DATA, VSC_OS_LOCAL, VSC_ARCH_LOCAL, and EBVERSIONR to be set after loading modules." >&2\n'
        "    exit 1\n"
        "fi\n\n"
        + arch_guard_block
        + f'R_LIBS_USER="{library_root_template}"\n'
        'mkdir -p "${R_LIBS_USER}"\n'
        "export R_LIBS_USER\n\n"
        'BUILD_ROOT="${VSC_SCRATCH_NODE:-${TMPDIR:-/tmp}}/r-pkg-build-${SLURM_JOB_ID:-manual}"\n'
        'mkdir -p "${BUILD_ROOT}"\n'
        'export TMPDIR="${BUILD_ROOT}"\n'
        'trap \'rm -rf "${BUILD_ROOT}"\' EXIT\n\n'
        'echo "Installing into ${R_LIBS_USER}"\n'
        'echo "Temporary build root ${TMPDIR}"\n'
        'echo "R version $(Rscript -e \'cat(as.character(getRversion()))\')"\n\n'
        "Rscript - <<'EOF'\n"
        f"repos <- {repos_vector}\n"
        "\n"
        "install_if_missing <- function(packages, repos) {\n"
        "  missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]\n"
        "  if (length(missing)) {\n"
        "    install.packages(missing, repos = repos, dependencies = TRUE)\n"
        "  }\n"
        "}\n\n"
        + install_live_block
        + archive_block
        + f"packages <- c({verify_packages_expr})\n"
        "status <- vapply(packages, requireNamespace, logical(1), quietly = TRUE)\n"
        "for (pkg in packages) {\n"
        '  cat(pkg, if (status[[pkg]]) "OK" else "MISSING", "\\n")\n'
        "}\n\n"
        "if (any(!status)) {\n"
        "  quit(status = 1)\n"
        "}\n\n"
        'cat("\\nLibrary paths:\\n")\n'
        "print(.libPaths())\n"
        'cat("\\nSession info:\\n")\n'
        "print(sessionInfo())\n"
        "EOF\n"
    )

def build_stage_script_command(*, directory: str, remote_name: str, contents: str) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    quoted_name = shlex.quote(remote_name)
    delimiter = "HPC_TOOLS_R_INSTALL_SCRIPT"
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

