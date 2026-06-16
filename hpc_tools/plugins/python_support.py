from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from hpc_tools.config import ConfigError, Profile
from hpc_tools import slurm, submissions
from hpc_tools.ssh import run_remote_capture


REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
STATUS_LINE_RE = re.compile(r"^(?P<package>[A-Za-z0-9_.-]+)\t(?P<status>OK|MISSING)$")
IMPORT_NAME_ALIASES = {
    "beautifulsoup4": "bs4",
    "mysql_connector_python": "mysql.connector",
    "opencv_python": "cv2",
    "opencv_python_headless": "cv2",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "python_dateutil": "dateutil",
    "python_levenshtein": "Levenshtein",
    "scikit_learn": "sklearn",
}


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


@dataclass(frozen=True)
class DependencySpec:
    name: str
    source: str
    file: Path
    line_number: int
    raw: str


@dataclass
class DependencyInspection:
    target: Path
    scanned_files: list[Path]
    requirements: list[DependencySpec]
    pyproject_dependencies: list[DependencySpec]
    conda_dependencies: list[DependencySpec]
    pip_dependencies: list[DependencySpec]
    channels: list[str]
    python_versions: list[str]
    binary_hints: list[str]
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
    python_executable: str | None
    sys_path: list[str]
    stdout: str


class PythonSupportPlugin:
    name = "python"
    description = "Python package checks and venv bootstrap helpers for HPC workflows."

    def register(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        profile: Profile | None,
    ) -> None:
        parser = subparsers.add_parser(
            "python",
            help="Python workflow helpers provided by the bundled Python plugin",
        )
        py_subparsers = parser.add_subparsers(dest="python_command", metavar="<subcommand>", required=True)

        scan_parser = py_subparsers.add_parser(
            "scan",
            help="Scan a Python script or project directory for import dependencies",
        )
        scan_parser.add_argument("target", type=Path, help="Python script path or project directory")
        scan_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        scan_parser.set_defaults(handler=cmd_python_scan)

        inspect_parser = py_subparsers.add_parser(
            "inspect-deps",
            help="Inspect Python dependency files without creating or modifying environments",
        )
        inspect_parser.add_argument("target", type=Path, help="Python project directory or file")
        inspect_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        inspect_parser.set_defaults(handler=cmd_python_inspect_deps)

        check_parser = py_subparsers.add_parser(
            "check",
            help="Check whether Python packages are importable under a chosen remote module stack",
        )
        _add_target_and_package_args(check_parser)
        _add_module_args(check_parser)
        check_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        check_parser.set_defaults(handler=cmd_python_check)

        plan_parser = py_subparsers.add_parser(
            "plan-install",
            help="Generate a Slurm venv install job script for missing Python packages",
        )
        _add_target_and_package_args(plan_parser)
        _add_module_args(plan_parser)
        plan_parser.add_argument("--output", type=Path, required=True, help="Output Slurm script path")
        plan_parser.add_argument("--venv", required=True, help="Remote virtualenv path to create or update")
        plan_parser.add_argument(
            "--cluster",
            default=profile.default_cluster if profile else None,
            help="Target cluster name for the install job",
        )
        plan_parser.add_argument("--partition", required=True, help="Target partition for the install job")
        plan_parser.add_argument("--job-name", default="python-package-install", help="SBATCH job name")
        plan_parser.add_argument("--time", default="00:30:00", help="SBATCH walltime")
        plan_parser.add_argument("--cpus-per-task", default="2", help="SBATCH CPUs per task")
        plan_parser.add_argument(
            "--arch-guard",
            help="Fail fast unless VSC_ARCH_LOCAL matches this value, for example icelake",
        )
        plan_parser.add_argument(
            "--no-system-site-packages",
            action="store_true",
            help="Create the venv without access to site module packages",
        )
        plan_parser.add_argument(
            "--upgrade-pip",
            action="store_true",
            help="Upgrade pip in the venv before installing missing packages",
        )
        plan_parser.add_argument("--force", action="store_true", help="Overwrite the output script if it exists")
        plan_parser.set_defaults(handler=cmd_python_plan_install)

        submit_parser = py_subparsers.add_parser(
            "submit-install",
            help="Stage a generated Python install script remotely, quote it, and submit it",
        )
        submit_parser.add_argument("jobscript", type=Path, help="Local Slurm install script path")
        submit_parser.add_argument("--directory", "-C", required=True, help="Remote directory for the script")
        submit_parser.add_argument("--account", "-A", required=True, help="Slurm account for quote and submit")
        submit_parser.add_argument("--remote-name", help="Remote filename; defaults to the local script basename")
        submit_parser.add_argument("--cluster", "-M", help="Override sbatch --clusters")
        submit_parser.add_argument("--partition", "-p", help="Override sbatch --partition")
        submit_parser.add_argument("--reservation", help="Override sbatch --reservation")
        submit_parser.add_argument("--time", "-t", help="Override sbatch --time")
        submit_parser.add_argument("--cpus-per-task", "-c", help="Override sbatch --cpus-per-task")
        submit_parser.add_argument("--nodes", "-N", help="Override sbatch --nodes")
        submit_parser.add_argument("--skip-quote", action="store_true", help="Skip the quote helper if configured")
        submit_parser.add_argument(
            "--no-validate-first",
            action="store_true",
            help="Skip sbatch --test-only before submitting",
        )
        submit_parser.set_defaults(handler=cmd_python_submit_install)

        verify_parser = py_subparsers.add_parser(
            "verify-install",
            help="Verify package status from a completed Python install job output file",
        )
        verify_parser.add_argument("--job-output", required=True, help="Remote path to the job output file")
        verify_parser.add_argument(
            "--package",
            action="append",
            required=True,
            dest="packages",
            help="Import/package name expected in the verification block; repeat for each package",
        )
        verify_parser.add_argument(
            "--require-venv-fragment",
            help="Optional substring that must appear in the recorded Python executable path",
        )
        verify_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        verify_parser.set_defaults(handler=cmd_python_verify_install)

    def requires_profile(self, argv: list[str]) -> bool:
        if not argv:
            return False
        return argv[0] not in {"scan", "inspect-deps"}


def get_plugin() -> PythonSupportPlugin:
    return PythonSupportPlugin()


def cmd_python_scan(args: argparse.Namespace, profile: Profile | None) -> int:
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


def cmd_python_inspect_deps(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    result = inspect_dependencies(args.target)
    if args.json:
        print(
            json.dumps(
                {
                    "target": str(result.target),
                    "scanned_files": [str(path) for path in result.scanned_files],
                    "requirements": [_dependency_spec_json(spec) for spec in result.requirements],
                    "pyproject_dependencies": [
                        _dependency_spec_json(spec) for spec in result.pyproject_dependencies
                    ],
                    "conda_dependencies": [_dependency_spec_json(spec) for spec in result.conda_dependencies],
                    "pip_dependencies": [_dependency_spec_json(spec) for spec in result.pip_dependencies],
                    "channels": result.channels,
                    "python_versions": result.python_versions,
                    "binary_hints": result.binary_hints,
                    "notes": result.notes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _print_dependency_inspection(result)
    return 0


def cmd_python_check(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("python check requires a configured profile")
    result = check_packages(
        profile,
        target=args.target,
        explicit_packages=args.packages,
        modules=args.modules,
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
    print(f"Modules: {', '.join(result.modules) if result.modules else 'none'}")
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
        raise ConfigError(result.stderr.strip() or "remote Python package check failed")
    return 0


def cmd_python_plan_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("python plan-install requires a configured profile")
    if args.output.exists() and not args.force:
        raise ConfigError(f"output already exists: {args.output}")
    dependency_inspection = inspect_dependencies(args.target)
    dependency_packages = _dependency_file_import_names(dependency_inspection)
    install_name_map = _dependency_file_install_name_map(dependency_inspection)
    explicit_packages = [*(args.packages or []), *dependency_packages]
    result = check_packages(
        profile,
        target=args.target,
        explicit_packages=explicit_packages,
        modules=args.modules,
        dry_run=args.dry_run,
    )
    if result.returncode not in {0, 1} and not result.available and not result.missing:
        raise ConfigError(result.stderr.strip() or "remote Python package check failed")
    if not result.missing:
        print("All requested packages are already importable; no install script written.")
        return 0
    install_packages = [install_name_map.get(package, package) for package in result.missing]
    script_text = render_install_script(
        missing_packages=result.missing,
        install_packages=install_packages,
        modules=args.modules,
        venv=args.venv,
        cluster=args.cluster or profile.default_cluster,
        partition=args.partition,
        job_name=args.job_name,
        time=args.time,
        cpus_per_task=args.cpus_per_task,
        arch_guard=args.arch_guard,
        system_site_packages=not args.no_system_site_packages,
        upgrade_pip=args.upgrade_pip,
    )
    args.output.write_text(script_text, encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Missing packages: {', '.join(result.missing)}")
    if install_packages != result.missing:
        print(f"Pip install names: {', '.join(install_packages)}")
    print(f"Modules: {', '.join(result.modules) if result.modules else 'none'}")
    print(f"Venv: {args.venv}")
    plan_notes = _dependency_plan_notes(dependency_inspection)
    if plan_notes:
        print("")
        print("Dependency-file notes:")
        for note in plan_notes:
            print(f"- {note}")
    return 0


def cmd_python_verify_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("python verify-install requires a configured profile")
    completed = run_remote_capture(profile, f"cat {shlex.quote(args.job_output)}", dry_run=args.dry_run)
    if completed.returncode != 0:
        raise ConfigError(completed.stderr.strip() or f"could not read job output: {args.job_output}")
    result = parse_verify_output(completed.stdout, args.packages)
    if args.require_venv_fragment and (
        not result.python_executable or args.require_venv_fragment not in result.python_executable
    ):
        raise ConfigError(f"required venv fragment not found in Python executable: {args.require_venv_fragment}")
    if args.json:
        print(
            json.dumps(
                {
                    "statuses": result.statuses,
                    "python_executable": result.python_executable,
                    "sys_path": result.sys_path,
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
    if result.python_executable:
        print("")
        print(f"Python executable: {result.python_executable}")
    if any(result.statuses.get(package) != "OK" for package in args.packages):
        raise ConfigError("one or more packages are still missing according to the job output")
    return 0


def cmd_python_submit_install(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("python submit-install requires a configured profile")
    if not args.jobscript.exists():
        raise ConfigError(f"local job script does not exist: {args.jobscript}")
    remote_name = args.remote_name or args.jobscript.name
    stage = run_remote_capture(
        profile,
        build_stage_script_command(
            directory=args.directory,
            remote_name=remote_name,
            contents=args.jobscript.read_text(encoding="utf-8"),
        ),
        dry_run=args.dry_run,
    )
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
        quoted = run_remote_capture(profile, build_quote_command(profile.sam_quote_command, quote_args), dry_run=args.dry_run)
        if quoted.stdout:
            print(quoted.stdout, end="")
        if quoted.stderr:
            print(quoted.stderr, end="", file=sys.stderr)
        if quoted.returncode != 0:
            return quoted.returncode

    submit_command = slurm.submit_command(remote_name, directory=args.directory, test_only=False, overrides=overrides)
    validation_command = slurm.submit_command(remote_name, directory=args.directory, test_only=True, overrides=overrides)
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
    if resolved.is_file():
        _scan_file(resolved, packages, scanned_files, notes)
        _scan_project_metadata(resolved.parent, packages, scanned_files, notes)
        return ScanResult(packages=packages, scanned_files=scanned_files, notes=notes)
    if not resolved.is_dir():
        raise FileNotFoundError(f"Python target does not exist: {resolved}")
    for path in sorted(resolved.rglob("*")):
        if path.is_file() and path.suffix == ".py":
            _scan_file(path, packages, scanned_files, notes)
    _scan_project_metadata(resolved, packages, scanned_files, notes)
    return ScanResult(packages=packages, scanned_files=scanned_files, notes=notes)


def inspect_dependencies(target: Path) -> DependencyInspection:
    resolved = target.expanduser().resolve()
    root = resolved.parent if resolved.is_file() else resolved
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Python target does not exist: {resolved}")

    scanned_files: list[Path] = []
    requirements: list[DependencySpec] = []
    pyproject_dependencies: list[DependencySpec] = []
    conda_dependencies: list[DependencySpec] = []
    pip_dependencies: list[DependencySpec] = []
    channels: list[str] = []
    python_versions: list[str] = []
    binary_hints: list[str] = []
    notes: list[str] = []

    for path in _requirement_files(root):
        _inspect_requirements_file(
            path,
            scanned_files=scanned_files,
            requirements=requirements,
            notes=notes,
            visited=set(),
        )

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        scanned_files.append(pyproject)
        _inspect_pyproject_dependencies(pyproject, pyproject_dependencies, notes)

    for name in ("environment.yml", "environment.yaml"):
        environment = root / name
        if environment.exists():
            scanned_files.append(environment)
            _inspect_environment_file(
                environment,
                conda_dependencies=conda_dependencies,
                pip_dependencies=pip_dependencies,
                channels=channels,
                python_versions=python_versions,
                binary_hints=binary_hints,
                notes=notes,
            )

    return DependencyInspection(
        target=resolved,
        scanned_files=scanned_files,
        requirements=requirements,
        pyproject_dependencies=pyproject_dependencies,
        conda_dependencies=conda_dependencies,
        pip_dependencies=pip_dependencies,
        channels=_unique_preserve_order(channels),
        python_versions=_unique_preserve_order(python_versions),
        binary_hints=_unique_preserve_order(binary_hints),
        notes=notes,
    )


def _dependency_file_import_names(inspection: DependencyInspection) -> list[str]:
    names: list[str] = []
    for spec in [
        *inspection.requirements,
        *inspection.pyproject_dependencies,
        *inspection.pip_dependencies,
    ]:
        import_name = _dependency_import_name_from_spec(spec)
        if import_name not in names:
            names.append(import_name)
    return names


def _dependency_file_install_name_map(inspection: DependencyInspection) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for spec in [
        *inspection.requirements,
        *inspection.pyproject_dependencies,
        *inspection.pip_dependencies,
    ]:
        import_name = _dependency_import_name_from_spec(spec)
        mapping.setdefault(import_name, _dependency_install_name_from_raw(spec.raw, spec.name))
    return mapping


def _dependency_plan_notes(inspection: DependencyInspection) -> list[str]:
    notes = list(inspection.notes)
    if inspection.conda_dependencies:
        conda_names = ", ".join(spec.name for spec in inspection.conda_dependencies)
        notes.append(
            "Conda dependencies were inspected but are not pip-installed by plan-install: "
            + conda_names
        )
    if inspection.pip_dependencies:
        pip_names = ", ".join(spec.name for spec in inspection.pip_dependencies)
        notes.append("Nested environment.yml pip dependencies are included in the import check: " + pip_names)
    if inspection.python_versions:
        notes.append("Python version pins from environment.yml: " + ", ".join(inspection.python_versions))
    if inspection.channels:
        notes.append("Conda channels from environment.yml: " + ", ".join(inspection.channels))
    if inspection.binary_hints:
        notes.append("Binary/runtime dependencies may require modules or conda/micromamba: " + ", ".join(inspection.binary_hints))
    return notes


def check_packages(
    profile: Profile,
    *,
    target: Path,
    explicit_packages: list[str] | None,
    modules: list[str],
    dry_run: bool = False,
) -> CheckResult:
    scan = scan_target(target)
    packages = _resolve_package_list(scan, explicit_packages)
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
        raise ConfigError("no Python packages were found to check")
    script = (
        "import importlib.util, sys\n"
        f"packages = {json.dumps(packages)}\n"
        "missing = []\n"
        "for package in packages:\n"
        "    status = 'OK' if importlib.util.find_spec(package) is not None else 'MISSING'\n"
        "    print(f'{package}\\t{status}')\n"
        "    if status == 'MISSING':\n"
        "        missing.append(package)\n"
        "sys.exit(1 if missing else 0)\n"
    )
    parts = []
    if modules:
        parts.append("module load " + " ".join(shlex.quote(module) for module in modules))
    parts.append("python - <<'HPC_TOOLS_PYTHON_CHECK'\n" + script + "HPC_TOOLS_PYTHON_CHECK")
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


def parse_verify_output(stdout: str, packages: list[str]) -> VerifyResult:
    statuses: dict[str, str] = {}
    python_executable: str | None = None
    sys_path: list[str] = []
    in_python_executable = False
    in_sys_path = False
    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^(?P<package>[A-Za-z0-9_.-]+)\s+(?P<status>OK|MISSING)$", line.strip())
        if match:
            statuses[match.group("package")] = match.group("status")
        if line.strip() == "Python executable:":
            in_python_executable = True
            in_sys_path = False
            continue
        if in_python_executable:
            if line.strip():
                python_executable = line.strip()
            in_python_executable = False
            continue
        if line.strip() == "Python sys.path:":
            in_sys_path = True
            continue
        if in_sys_path:
            if not line.strip():
                in_sys_path = False
                continue
            sys_path.append(line.strip())
    for package in packages:
        statuses.setdefault(package, "UNKNOWN")
    return VerifyResult(statuses=statuses, python_executable=python_executable, sys_path=sys_path, stdout=stdout)


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


def _add_target_and_package_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", type=Path, help="Python script path or project directory")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        dest="packages",
        help="Additional import/package name to include; repeat for each package",
    )


def _add_module_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        dest="modules",
        help="Module to load before running Python; repeat to preserve the full runtime stack",
    )


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


def _print_dependency_inspection(result: DependencyInspection) -> None:
    print(f"Target: {result.target}")
    print("")
    print("Files inspected:")
    for path in result.scanned_files:
        print(f"- {path}")
    if not result.scanned_files:
        print("- none")
    print("")
    _print_dependency_group("Requirements", result.requirements)
    _print_dependency_group("Pyproject dependencies", result.pyproject_dependencies)
    _print_dependency_group("Conda dependencies", result.conda_dependencies)
    _print_dependency_group("Pip dependencies", result.pip_dependencies)
    if result.channels:
        print("Channels:")
        for channel in result.channels:
            print(f"- {channel}")
        print("")
    if result.python_versions:
        print("Python version pins:")
        for version in result.python_versions:
            print(f"- {version}")
        print("")
    if result.binary_hints:
        print("Binary/runtime hints:")
        for hint in result.binary_hints:
            print(f"- {hint}")
        print("")
    if result.notes:
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")


def _print_dependency_group(title: str, specs: list[DependencySpec]) -> None:
    print(f"{title}:")
    for spec in specs:
        print(f"- {spec.name}  ({spec.source} in {spec.file}:{spec.line_number})")
    if not specs:
        print("- none")
    print("")


def _dependency_spec_json(spec: DependencySpec) -> dict[str, str | int]:
    return {
        "name": spec.name,
        "source": spec.source,
        "file": str(spec.file),
        "line_number": spec.line_number,
        "raw": spec.raw,
    }


def _resolve_package_list(scan: ScanResult, explicit_packages: list[str] | None) -> list[str]:
    packages = set(scan.packages)
    packages.update(explicit_packages or [])
    local_modules = {path.stem for path in scan.scanned_files if path.suffix == ".py"}
    stdlib_modules = getattr(sys, "stdlib_module_names", set())
    return sorted(
        package
        for package in packages
        if package
        and package not in local_modules
        and package not in stdlib_modules
        and package != "__future__"
    )


def _scan_file(
    path: Path,
    packages: dict[str, list[PackageHit]],
    scanned_files: list[Path],
    notes: list[str],
) -> None:
    scanned_files.append(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as error:
        notes.append(f"Could not parse {path}: {error}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _record_package(packages, alias.name.split(".")[0], path, node.lineno, "import")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                _record_package(packages, node.module.split(".")[0], path, node.lineno, "from import")


def _scan_project_metadata(
    directory: Path,
    packages: dict[str, list[PackageHit]],
    scanned_files: list[Path],
    notes: list[str],
) -> None:
    for pattern in ("requirements.txt", "requirements-*.txt"):
        for path in sorted(directory.glob(pattern)):
            if path.is_file():
                scanned_files.append(path)
                _scan_requirements(path, packages, notes)
    pyproject = directory / "pyproject.toml"
    if pyproject.exists():
        scanned_files.append(pyproject)
        _scan_pyproject_lightweight(pyproject, packages, notes)


def _requirement_files(directory: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in ("requirements.txt", "requirements-*.txt"):
        for path in sorted(directory.glob(pattern)):
            if path.is_file() and path not in paths:
                paths.append(path)
    return paths


def _scan_requirements(path: Path, packages: dict[str, list[PackageHit]], notes: list[str]) -> None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-", "git+", "http://", "https://")):
            continue
        match = REQUIREMENT_RE.match(stripped)
        if match:
            raw_name = match.group(1)
            _record_package(
                packages,
                _dependency_import_name_from_raw(raw_name, _normalize_requirement_name(raw_name)),
                path,
                line_number,
                "requirements",
            )
        else:
            notes.append(f"{path}:{line_number} contains a requirement that was not statically resolved.")


def _inspect_requirements_file(
    path: Path,
    *,
    scanned_files: list[Path],
    requirements: list[DependencySpec],
    notes: list[str],
    visited: set[Path],
) -> None:
    resolved = path.resolve()
    if resolved in visited:
        return
    visited.add(resolved)
    if resolved not in scanned_files:
        scanned_files.append(resolved)
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = resolved.read_text(encoding="latin-1").splitlines()
        notes.append(f"Read {resolved} as latin-1 after UTF-8 decoding failed.")

    for line_number, line in enumerate(lines, start=1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith(("-r ", "--requirement ")):
            include_name = stripped.split(maxsplit=1)[1]
            include_path = (resolved.parent / include_name).resolve()
            if include_path.exists():
                _inspect_requirements_file(
                    include_path,
                    scanned_files=scanned_files,
                    requirements=requirements,
                    notes=notes,
                    visited=visited,
                )
            else:
                notes.append(f"{resolved}:{line_number} includes missing requirements file {include_name}.")
            continue
        if stripped.startswith(("-c ", "--constraint ")):
            notes.append(f"{resolved}:{line_number} references a constraints file; inspect version pins manually.")
            continue
        if stripped.startswith("-e "):
            notes.append(f"{resolved}:{line_number} contains an editable install; map it manually to imports.")
            continue
        if stripped.startswith(("-", "git+", "http://", "https://")):
            notes.append(f"{resolved}:{line_number} contains a non-package requirement: {stripped}")
            continue
        match = REQUIREMENT_RE.match(stripped)
        if match:
            _append_dependency_spec(
                requirements,
                name=_normalize_requirement_name(match.group(1)),
                source="requirements",
                file=resolved,
                line_number=line_number,
                raw=stripped,
            )
        else:
            notes.append(f"{resolved}:{line_number} contains a requirement that was not statically resolved.")


def _scan_pyproject_lightweight(path: Path, packages: dict[str, list[PackageHit]], notes: list[str]) -> None:
    in_dependencies = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_dependencies = False
            continue
        if stripped.startswith("dependencies") and "[" in stripped:
            in_dependencies = True
        if in_dependencies:
            for match in re.finditer(r'["\']([A-Za-z0-9_.-]+)', stripped):
                raw_name = match.group(1)
                _record_package(
                    packages,
                    _dependency_import_name_from_raw(raw_name, _normalize_requirement_name(raw_name)),
                    path,
                    line_number,
                    "pyproject dependencies",
                )
            if "]" in stripped:
                in_dependencies = False


def _inspect_pyproject_dependencies(
    path: Path,
    dependencies: list[DependencySpec],
    notes: list[str],
) -> None:
    in_dependencies = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_dependencies = False
            continue
        if stripped.startswith("dependencies") and "[" in stripped:
            in_dependencies = True
        if in_dependencies:
            for match in re.finditer(r'["\']([^"\']+)["\']', stripped):
                raw = match.group(1).strip()
                name = _dependency_name_from_requirement(raw)
                if name:
                    _append_dependency_spec(
                        dependencies,
                        name=_normalize_requirement_name(name),
                        source="pyproject dependencies",
                        file=path,
                        line_number=line_number,
                        raw=raw,
                    )
                else:
                    notes.append(f"{path}:{line_number} contains a dependency that was not statically resolved.")
            if "]" in stripped:
                in_dependencies = False


def _inspect_environment_file(
    path: Path,
    *,
    conda_dependencies: list[DependencySpec],
    pip_dependencies: list[DependencySpec],
    channels: list[str],
    python_versions: list[str],
    binary_hints: list[str],
    notes: list[str],
) -> None:
    section: str | None = None
    in_pip = False
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith((" ", "-")) and stripped.endswith(":"):
            section = stripped[:-1]
            in_pip = False
            continue
        if section == "channels" and stripped.startswith("- "):
            channels.append(stripped[2:].strip())
            continue
        if section != "dependencies" or not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if value == "pip:":
            in_pip = True
            continue
        if in_pip and raw_line.startswith("    - "):
            name = _dependency_name_from_requirement(value)
            if name:
                _append_dependency_spec(
                    pip_dependencies,
                    name=_normalize_requirement_name(name),
                    source="environment.yml pip",
                    file=path,
                    line_number=line_number,
                    raw=value,
                )
            else:
                notes.append(f"{path}:{line_number} contains a pip dependency that was not statically resolved.")
            continue
        in_pip = False
        name = _dependency_name_from_conda(value)
        if not name:
            notes.append(f"{path}:{line_number} contains a conda dependency that was not statically resolved.")
            continue
        _append_dependency_spec(
            conda_dependencies,
            name=_normalize_requirement_name(name),
            source="environment.yml conda",
            file=path,
            line_number=line_number,
            raw=value,
        )
        if name == "python":
            python_versions.append(value)
        if _looks_like_binary_dependency(name):
            binary_hints.append(value)


def _normalize_requirement_name(name: str) -> str:
    return name.strip().split("[", 1)[0].replace("-", "_")


def _dependency_name_from_requirement(value: str) -> str | None:
    match = REQUIREMENT_RE.match(value)
    if not match:
        return None
    return match.group(1)


def _dependency_install_name_from_raw(raw: str, fallback: str) -> str:
    name = _dependency_name_from_requirement(raw)
    if not name:
        return fallback
    return name.strip().split("[", 1)[0]


def _dependency_import_name_from_spec(spec: DependencySpec) -> str:
    return _dependency_import_name_from_raw(spec.raw, spec.name)


def _dependency_import_name_from_raw(raw: str, fallback: str) -> str:
    name = _dependency_name_from_requirement(raw)
    if not name:
        return fallback
    normalized = _normalize_requirement_name(name)
    alias = IMPORT_NAME_ALIASES.get(normalized.lower())
    if alias:
        return alias
    return normalized


def _dependency_name_from_conda(value: str) -> str | None:
    if not value or value.startswith(("-", "{", "[")):
        return None
    return re.split(r"[<>=!~ ]", value, maxsplit=1)[0].strip()


def _looks_like_binary_dependency(name: str) -> bool:
    normalized = name.lower().replace("_", "-")
    binary_terms = {
        "cuda",
        "cudatoolkit",
        "cuda-toolkit",
        "mpi",
        "openmpi",
        "mpich",
        "hdf5",
        "gdal",
        "gcc",
        "gxx",
        "c-compiler",
        "cxx-compiler",
        "fortran-compiler",
        "compilers",
    }
    return normalized in binary_terms or any(term in normalized for term in ("cuda", "mpi", "hdf5", "gdal"))


def _append_dependency_spec(
    specs: list[DependencySpec],
    *,
    name: str,
    source: str,
    file: Path,
    line_number: int,
    raw: str,
) -> None:
    spec = DependencySpec(name=name, source=source, file=file, line_number=line_number, raw=raw)
    if spec not in specs:
        specs.append(spec)


def _unique_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _record_package(
    packages: dict[str, list[PackageHit]],
    package: str | None,
    path: Path,
    line_number: int,
    origin: str,
) -> None:
    if not package:
        return
    hit = PackageHit(package=package, file=path, line_number=line_number, origin=origin)
    existing = packages.setdefault(package, [])
    if hit not in existing:
        existing.append(hit)


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
