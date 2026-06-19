from __future__ import annotations

import argparse
from dataclasses import dataclass
from email.parser import Parser
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from hpc_tools.config import ConfigError, Profile
from hpc_tools import slurm, submissions
from hpc_tools.ssh import run_remote_capture


PACKAGE_CALL_RE = re.compile(
    r"\b(?:library|require|requireNamespace)\(\s*(?:[\"']?([A-Za-z][A-Za-z0-9._]*)[\"']?)"
)
PACKAGE_OPERATOR_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9._]*):::{0,2}[A-Za-z][A-Za-z0-9._]*")
SOURCE_CALL_RE = re.compile(r"\bsource\(\s*[\"']([^\"']+)[\"']")
STATUS_LINE_RE = re.compile(r"^(?P<package>[A-Za-z][A-Za-z0-9._]*)\t(?P<status>OK|MISSING)$")
BASE_PACKAGES = {
    "base",
    "compiler",
    "datasets",
    "graphics",
    "grDevices",
    "grid",
    "methods",
    "parallel",
    "splines",
    "stats",
    "stats4",
    "tcltk",
    "tools",
    "utils",
}
DEFAULT_LIBRARY_ROOT_TEMPLATE = "${VSC_DATA}/Rlibs/${VSC_OS_LOCAL}/${VSC_ARCH_LOCAL}/R-${EBVERSIONR}"


@dataclass(frozen=True)
class PackageHit:
    package: str
    file: Path
    line_number: int
    origin: str


@dataclass
class ScanResult:
    packages: dict[str, list[PackageHit]]
    scanned_files: list[Path]
    notes: list[str]


@dataclass
class CheckResult:
    packages: list[str]
    available: list[str]
    missing: list[str]
    modules: list[str]
    remote_command: str
    stdout: str
    stderr: str
    returncode: int
    notes: list[str]


@dataclass
class VerifyResult:
    statuses: dict[str, str]
    library_paths: list[str]
    stdout: str


class RSupportPlugin:
    name = "r"
    description = "R dependency scanning helpers for HPC workflows."

    def register(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        profile: Profile | None,
    ) -> None:
        parser = subparsers.add_parser(
            "r",
            help="R workflow helpers provided by the bundled R plugin",
        )
        r_subparsers = parser.add_subparsers(dest="r_command", metavar="<subcommand>", required=True)

        scan_parser = r_subparsers.add_parser(
            "scan",
            help="Scan an R script or project directory for package dependencies",
        )
        scan_parser.add_argument("target", type=Path, help="R script path or project directory")
        scan_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        scan_parser.set_defaults(handler=cmd_r_scan)

        check_parser = r_subparsers.add_parser(
            "check",
            help="Check whether packages are available under a chosen remote R module stack",
        )
        _add_target_and_package_args(check_parser)
        _add_module_args(check_parser)
        check_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        check_parser.set_defaults(handler=cmd_r_check)

        plan_parser = r_subparsers.add_parser(
            "plan-install",
            help="Generate a Slurm install job script for missing packages",
        )
        _add_target_and_package_args(plan_parser)
        _add_module_args(plan_parser)
        plan_parser.add_argument("--output", type=Path, required=True, help="Output Slurm script path")
        plan_parser.add_argument(
            "--cluster",
            default=profile.default_cluster if profile else None,
            help="Target cluster name for the install job",
        )
        plan_parser.add_argument("--partition", required=True, help="Target partition for the install job")
        plan_parser.add_argument("--job-name", default="r-package-install", help="SBATCH job name")
        plan_parser.add_argument("--time", default="01:00:00", help="SBATCH walltime")
        plan_parser.add_argument("--cpus-per-task", default="4", help="SBATCH CPUs per task")
        plan_parser.add_argument(
            "--library-root-template",
            default=DEFAULT_LIBRARY_ROOT_TEMPLATE,
            help="Shell expression used for R_LIBS_USER inside the job script",
        )
        plan_parser.add_argument(
            "--arch-guard",
            help="Fail fast unless VSC_ARCH_LOCAL matches this value, for example icelake",
        )
        plan_parser.add_argument(
            "--archive-package",
            action="append",
            default=[],
            metavar="PKG=URL",
            help="Install this package from an explicit archive/source tarball URL",
        )
        plan_parser.add_argument(
            "--extra-repo",
            action="append",
            default=[],
            metavar="NAME=URL",
            help="Additional repository entry added to the repos vector, for example INLA=https://...",
        )
        plan_parser.add_argument("--force", action="store_true", help="Overwrite the output script if it exists")
        plan_parser.set_defaults(handler=cmd_r_plan_install)

        submit_parser = r_subparsers.add_parser(
            "submit-install",
            help="Stage a generated install script remotely, quote it, and submit it",
        )
        submit_parser.add_argument("jobscript", type=Path, help="Local Slurm install script path")
        submit_parser.add_argument("--directory", "-C", required=True, help="Remote directory for the script")
        submit_parser.add_argument("--account", "-A", required=True, help="Slurm account for quote and submit")
        submit_parser.add_argument(
            "--remote-name",
            help="Remote filename; defaults to the local script basename",
        )
        submit_parser.add_argument("--cluster", "-M", help="Override sbatch --clusters")
        submit_parser.add_argument("--partition", "-p", help="Override sbatch --partition")
        submit_parser.add_argument("--reservation", help="Override sbatch --reservation")
        submit_parser.add_argument("--time", "-t", help="Override sbatch --time")
        submit_parser.add_argument("--cpus-per-task", "-c", help="Override sbatch --cpus-per-task")
        submit_parser.add_argument("--nodes", "-N", help="Override sbatch --nodes")
        submit_parser.add_argument(
            "--skip-quote",
            action="store_true",
            help="Skip the quote helper even if the profile defines one",
        )
        submit_parser.add_argument(
            "--no-validate-first",
            action="store_true",
            help="Skip sbatch --test-only before submitting",
        )
        submit_parser.set_defaults(handler=cmd_r_submit_install)

        verify_parser = r_subparsers.add_parser(
            "verify-install",
            help="Verify package status from a completed install job output file",
        )
        verify_parser.add_argument("--job-output", required=True, help="Remote path to the job output file")
        verify_parser.add_argument(
            "--package",
            action="append",
            required=True,
            dest="packages",
            help="Package name expected in the verification block; repeat for each package",
        )
        verify_parser.add_argument(
            "--require-lib-fragment",
            help="Optional substring that must appear in the recorded .libPaths() block",
        )
        verify_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        verify_parser.set_defaults(handler=cmd_r_verify_install)

    def requires_profile(self, argv: list[str]) -> bool:
        if not argv:
            return False
        return argv[0] not in {"scan"}


def get_plugin() -> RSupportPlugin:
    return RSupportPlugin()


def cmd_r_scan(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    result = scan_target(args.target)
    if args.json:
        print(
            json.dumps(
                {
                    "packages": sorted(result.packages),
                    "scanned_files": [str(path) for path in result.scanned_files],
                    "notes": result.notes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _print_scan_result(args.target.resolve(), result)
    return 0


def cmd_r_check(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("r check requires a configured profile")
    result = check_packages(
        profile,
        target=args.target,
        explicit_packages=args.packages,
        module=args.module,
        cran_bundle=args.cran_bundle,
        bioc_bundle=args.bioc_bundle,
        dry_run=args.dry_run,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "packages": result.packages,
                    "available": result.available,
                    "missing": result.missing,
                    "modules": result.modules,
                    "remote_command": result.remote_command,
                    "returncode": result.returncode,
                    "notes": result.notes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"Target: {args.target.resolve()}")
    print(f"Modules: {', '.join(result.modules)}")
    print("")
    print("Available:")
    for package in result.available:
        print(f"- {package}")
    if not result.available:
        print("- none")
    print("")
    print("Missing:")
    for package in result.missing:
        print(f"- {package}")
    if not result.missing:
        print("- none")
    if result.notes:
        print("")
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")
    if result.returncode not in {0, 1} and not result.available and not result.missing:
        raise ConfigError(result.stderr.strip() or "remote package check failed")
    return 0


def cmd_r_plan_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("r plan-install requires a configured profile")
    if args.output.exists() and not args.force:
        raise ConfigError(f"output already exists: {args.output}")

    archive_packages = _parse_mapping_args(args.archive_package, "archive-package")
    extra_repos = _parse_mapping_args(args.extra_repo, "extra-repo")
    result = check_packages(
        profile,
        target=args.target,
        explicit_packages=args.packages,
        module=args.module,
        cran_bundle=args.cran_bundle,
        bioc_bundle=args.bioc_bundle,
        dry_run=args.dry_run,
    )
    if result.returncode not in {0, 1} and not result.available and not result.missing:
        raise ConfigError(result.stderr.strip() or "remote package check failed")
    if not result.missing:
        print("All requested packages are already available; no install script written.")
        return 0

    script_text = render_install_script(
        missing_packages=result.missing,
        module=args.module,
        cran_bundle=args.cran_bundle,
        bioc_bundle=args.bioc_bundle,
        cluster=args.cluster or profile.default_cluster,
        partition=args.partition,
        job_name=args.job_name,
        time=args.time,
        cpus_per_task=args.cpus_per_task,
        library_root_template=args.library_root_template,
        arch_guard=args.arch_guard,
        archive_packages=archive_packages,
        extra_repos=extra_repos,
    )
    args.output.write_text(script_text, encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Missing packages: {', '.join(result.missing)}")
    print(f"Modules: {', '.join(result.modules)}")
    return 0


def cmd_r_verify_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("r verify-install requires a configured profile")
    command = f"cat {shlex.quote(args.job_output)}"
    completed = run_remote_capture(profile, command, dry_run=args.dry_run)
    if completed.returncode != 0:
        raise ConfigError(completed.stderr.strip() or f"could not read job output: {args.job_output}")
    result = parse_verify_output(completed.stdout, args.packages)
    if args.require_lib_fragment and not any(args.require_lib_fragment in line for line in result.library_paths):
        raise ConfigError(
            f"required library path fragment not found in job output: {args.require_lib_fragment}"
        )
    if args.json:
        print(
            json.dumps(
                {
                    "statuses": result.statuses,
                    "library_paths": result.library_paths,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"Job output: {args.job_output}")
    print("")
    print("Package status:")
    for package in args.packages:
        print(f"- {package}: {result.statuses.get(package, 'UNKNOWN')}")
    if result.library_paths:
        print("")
        print("Library paths:")
        for line in result.library_paths:
            print(f"- {line}")
    if any(result.statuses.get(package) != "OK" for package in args.packages):
        raise ConfigError("one or more packages are still missing according to the job output")
    return 0


def cmd_r_submit_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("r submit-install requires a configured profile")
    if not args.jobscript.exists():
        raise ConfigError(f"local job script does not exist: {args.jobscript}")

    remote_name = args.remote_name or args.jobscript.name
    script_contents = args.jobscript.read_text(encoding="utf-8")
    stage_command = build_stage_script_command(
        directory=args.directory,
        remote_name=remote_name,
        contents=script_contents,
    )
    stage = run_remote_capture(profile, stage_command, dry_run=args.dry_run)
    if stage.stdout:
        print(stage.stdout, end="")
    if stage.stderr:
        print(stage.stderr, end="", file=sys.stderr)
    if stage.returncode != 0:
        return stage.returncode

    overrides = {
        "account": args.account,
        "cluster": args.cluster,
        "cpus_per_task": args.cpus_per_task,
        "nodes": args.nodes,
        "partition": args.partition,
        "reservation": args.reservation,
        "time": args.time,
    }
    overrides = {name: value for name, value in overrides.items() if value is not None}
    quote_args = build_quote_args(
        remote_script_path=_remote_script_path(args.directory, remote_name),
        account=args.account,
        cluster=args.cluster,
        partition=args.partition,
        reservation=args.reservation,
        time=args.time,
        nodes=args.nodes,
        cpus_per_task=args.cpus_per_task,
    )
    if not args.skip_quote and profile.sam_quote_command:
        quote_command = build_quote_command(profile.sam_quote_command, quote_args)
        quoted = run_remote_capture(profile, quote_command, dry_run=args.dry_run)
        if quoted.stdout:
            print(quoted.stdout, end="")
        if quoted.stderr:
            print(quoted.stderr, end="", file=sys.stderr)
        if quoted.returncode != 0:
            return quoted.returncode

    submit_command = slurm.submit_command(
        remote_name,
        directory=args.directory,
        test_only=False,
        overrides=overrides,
    )
    validation_command = slurm.submit_command(
        remote_name,
        directory=args.directory,
        test_only=True,
        overrides=overrides,
    )
    if args.dry_run:
        if not args.no_validate_first:
            run_remote_capture(profile, validation_command, dry_run=True)
        run_remote_capture(profile, submit_command, dry_run=True)
        return 0

    if not args.no_validate_first:
        validation = run_remote_capture(profile, validation_command)
        if validation.stdout:
            print(validation.stdout, end="")
        if validation.stderr:
            print(validation.stderr, end="", file=sys.stderr)
        if validation.returncode != 0:
            return validation.returncode

    completed = run_remote_capture(profile, submit_command)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode == 0:
        _log_submission(
            profile=profile,
            remote_directory=args.directory,
            remote_name=remote_name,
            command=submit_command,
            overrides=overrides,
            sbatch_output=completed.stdout + completed.stderr,
        )
    return completed.returncode


def scan_target(target: Path) -> ScanResult:
    resolved = target.expanduser().resolve()
    packages: dict[str, list[PackageHit]] = {}
    scanned_files: list[Path] = []
    notes: list[str] = []
    visited: set[Path] = set()

    if resolved.is_file():
        _scan_r_file(resolved, packages, scanned_files, notes, visited)
        _scan_project_metadata(resolved.parent, packages, scanned_files, notes)
        return ScanResult(packages=packages, scanned_files=scanned_files, notes=notes)

    if not resolved.is_dir():
        raise FileNotFoundError(f"R target does not exist: {resolved}")

    for path in sorted(resolved.rglob("*")):
        if path.is_file() and path.suffix.lower() == ".r":
            _scan_r_file(path, packages, scanned_files, notes, visited)

    _scan_project_metadata(resolved, packages, scanned_files, notes)
    return ScanResult(packages=packages, scanned_files=scanned_files, notes=notes)


def check_packages(
    profile: Profile,
    *,
    target: Path,
    explicit_packages: list[str] | None,
    module: str,
    cran_bundle: str | None,
    bioc_bundle: str | None,
    dry_run: bool = False,
) -> CheckResult:
    scan = scan_target(target)
    packages = _resolve_package_list(scan, explicit_packages)
    modules = [module, *(bundle for bundle in (cran_bundle, bioc_bundle) if bundle)]
    command = build_check_command(packages, modules)
    completed = run_remote_capture(profile, command, dry_run=dry_run)
    available, missing = parse_status_output(completed.stdout, packages)
    return CheckResult(
        packages=packages,
        available=available,
        missing=missing,
        modules=modules,
        remote_command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        notes=scan.notes,
    )


def build_check_command(packages: list[str], modules: list[str]) -> str:
    if not packages:
        raise ConfigError("no R packages were found to check")
    r_packages = ", ".join(json.dumps(package) for package in packages)
    expression = (
        f"packages <- c({r_packages}); "
        "status <- vapply(packages, requireNamespace, logical(1), quietly = TRUE); "
        'for (pkg in packages) cat(pkg, "\\t", if (status[[pkg]]) "OK" else "MISSING", "\\n", sep = ""); '
        "if (any(!status)) quit(status = 1)"
    )
    parts = []
    if modules:
        parts.append("module load " + " ".join(shlex.quote(module) for module in modules))
    parts.append("Rscript -e " + shlex.quote(expression))
    return " && ".join(parts)


def parse_status_output(stdout: str, packages: list[str]) -> tuple[list[str], list[str]]:
    statuses: dict[str, str] = {}
    for line in stdout.splitlines():
        match = STATUS_LINE_RE.match(line.strip())
        if match:
            statuses[match.group("package")] = match.group("status")
    available = [package for package in packages if statuses.get(package) == "OK"]
    missing = [package for package in packages if statuses.get(package) != "OK"]
    return available, missing


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


def parse_verify_output(stdout: str, packages: list[str]) -> VerifyResult:
    statuses: dict[str, str] = {}
    library_paths: list[str] = []
    in_library_paths = False
    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^(?P<package>[A-Za-z][A-Za-z0-9._]*)\s+(?P<status>OK|MISSING)$", line.strip())
        if match:
            statuses[match.group("package")] = match.group("status")
        if line.strip() == "Library paths:":
            in_library_paths = True
            continue
        if in_library_paths:
            if not line.strip():
                in_library_paths = False
                continue
            library_paths.append(line.strip())
    for package in packages:
        statuses.setdefault(package, "UNKNOWN")
    return VerifyResult(statuses=statuses, library_paths=library_paths, stdout=stdout)


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


def _add_target_and_package_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", type=Path, help="R script path or project directory")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        dest="packages",
        help="Additional package name to include; repeat for each package",
    )


def _add_module_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--module", required=True, help="R module to load remotely")
    parser.add_argument("--cran-bundle", help="Optional R-bundle-CRAN module")
    parser.add_argument("--bioc-bundle", help="Optional R-bundle-Bioconductor module")


def _print_scan_result(target: Path, result: ScanResult) -> None:
    print(f"Target: {target}")
    print("")
    print("Packages:")
    for package in sorted(result.packages):
        first = result.packages[package][0]
        print(f"- {package}  ({first.origin} in {first.file}:{first.line_number})")
    if not result.packages:
        print("- none detected")
    print("")
    print("Files scanned:")
    for path in result.scanned_files:
        print(f"- {path}")
    if result.notes:
        print("")
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")


def _resolve_package_list(scan: ScanResult, explicit_packages: list[str] | None) -> list[str]:
    packages = set(scan.packages)
    packages.update(explicit_packages or [])
    return sorted(package for package in packages if package not in BASE_PACKAGES)


def _scan_r_file(
    path: Path,
    packages: dict[str, list[PackageHit]],
    scanned_files: list[Path],
    notes: list[str],
    visited: set[Path],
) -> None:
    if path in visited or not path.exists():
        return
    visited.add(path)
    scanned_files.append(path)

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
        notes.append(f"Read {path} as latin-1 after UTF-8 decoding failed.")

    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in PACKAGE_CALL_RE.finditer(line):
            _record_package(packages, match.group(1), path, line_number, "package call")
        for match in PACKAGE_OPERATOR_RE.finditer(line):
            _record_package(packages, match.group(1), path, line_number, "namespace operator")
        if any(token in line for token in ("library(", "require(", "requireNamespace(")) and not PACKAGE_CALL_RE.search(line):
            notes.append(f"{path}:{line_number} contains a dynamic package call that was not statically resolved.")
        for match in SOURCE_CALL_RE.finditer(line):
            source_path = _resolve_source_path(path, match.group(1))
            if source_path is None:
                notes.append(f"{path}:{line_number} sources missing file {match.group(1)}.")
                continue
            _scan_r_file(source_path, packages, scanned_files, notes, visited)


def _scan_project_metadata(
    directory: Path,
    packages: dict[str, list[PackageHit]],
    scanned_files: list[Path],
    notes: list[str],
) -> None:
    description = directory / "DESCRIPTION"
    if description.exists():
        scanned_files.append(description)
        _scan_description(description, packages)

    renv_lock = directory / "renv.lock"
    if renv_lock.exists():
        scanned_files.append(renv_lock)
        _scan_renv_lock(renv_lock, packages, notes)


def _scan_description(path: Path, packages: dict[str, list[PackageHit]]) -> None:
    message = Parser().parsestr(path.read_text(encoding="utf-8"))
    for field in ("Imports", "Depends", "LinkingTo"):
        value = message.get(field)
        if value is None:
            continue
        for package in _split_description_packages(value):
            _record_package(packages, package, path, 1, f"DESCRIPTION {field}")


def _scan_renv_lock(path: Path, packages: dict[str, list[PackageHit]], notes: list[str]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        notes.append(f"Could not parse {path}; ignoring renv lockfile.")
        return
    packages_node = payload.get("Packages", {})
    if not isinstance(packages_node, dict):
        return
    for package in sorted(packages_node):
        _record_package(packages, package, path, 1, "renv.lock")


def _split_description_packages(value: str) -> list[str]:
    packages = []
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        name = token.split("(")[0].strip()
        if name and name != "R":
            packages.append(name)
    return packages


def _record_package(
    packages: dict[str, list[PackageHit]],
    package: str | None,
    path: Path,
    line_number: int,
    origin: str,
) -> None:
    if not package or package in BASE_PACKAGES:
        return
    hit = PackageHit(package=package, file=path, line_number=line_number, origin=origin)
    existing = packages.setdefault(package, [])
    if hit not in existing:
        existing.append(hit)


def _resolve_source_path(origin: Path, relative_path: str) -> Path | None:
    candidates = [(origin.parent / relative_path).resolve()]
    for parent in origin.parent.parents:
        candidates.append((parent / relative_path).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_mapping_args(values: list[str], option_name: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        key, separator, entry = value.partition("=")
        if not separator or not key or not entry:
            raise ConfigError(f"{option_name} entries must use NAME=VALUE syntax: {value}")
        mapping[key] = entry
    return mapping


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
