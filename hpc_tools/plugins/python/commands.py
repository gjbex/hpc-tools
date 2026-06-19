from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from hpc_tools import slurm
from hpc_tools.config import ConfigError, Profile
from hpc_tools.plugins.python.dependencies import (
    DependencyInspection,
    DependencySpec,
    ScanResult,
    _dependency_file_import_names,
    _dependency_file_install_name_map,
    _dependency_plan_notes,
    inspect_dependencies,
    resolve_package_list,
    scan_target,
)
from hpc_tools.plugins.python.install_plan import (
    _log_submission,
    _remote_script_path,
    build_quote_args,
    build_quote_command,
    build_stage_script_command,
    render_install_script,
)
from hpc_tools.plugins.python.remote_verify import check_packages, parse_verify_output
from hpc_tools.ssh import run_remote_capture

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

