from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from hpc_tools import slurm
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import run_command_capture
from hpc_tools.plugins.r.dependencies import ScanResult, resolve_package_list, scan_target
from hpc_tools.plugins.r.install_plan import (
    DEFAULT_LIBRARY_ROOT_TEMPLATE,
    _log_submission,
    _remote_script_path,
    build_quote_args,
    build_quote_command,
    build_stage_script_command,
    render_install_script,
)
from hpc_tools.plugins.r.remote_verify import check_packages, parse_verify_output

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
        scan_parser.set_defaults(handler=cmd_r_scan, operation_id="r.scan")

        check_parser = r_subparsers.add_parser(
            "check",
            help="Check whether packages are available under a chosen remote R module stack",
        )
        _add_target_and_package_args(check_parser)
        _add_module_args(check_parser)
        check_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        check_parser.set_defaults(handler=cmd_r_check, operation_id="r.check")

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
        plan_parser.set_defaults(
            handler=cmd_r_plan_install,
            operation_id="r.plan-install",
        )

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
        submit_parser.set_defaults(
            handler=cmd_r_submit_install,
            operation_id="r.submit-install",
        )

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
        verify_parser.set_defaults(
            handler=cmd_r_verify_install,
            operation_id="r.verify-install",
        )

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
    completed = run_command_capture(profile, command, dry_run=args.dry_run)
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
    stage = run_command_capture(profile, stage_command, dry_run=args.dry_run)
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
        quoted = run_command_capture(profile, quote_command, dry_run=args.dry_run)
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
            run_command_capture(profile, validation_command, dry_run=True)
        run_command_capture(profile, submit_command, dry_run=True)
        return 0

    if not args.no_validate_first:
        validation = run_command_capture(profile, validation_command)
        if validation.stdout:
            print(validation.stdout, end="")
        if validation.stderr:
            print(validation.stderr, end="", file=sys.stderr)
        if validation.returncode != 0:
            return validation.returncode

    completed = run_command_capture(profile, submit_command)
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

def _parse_mapping_args(values: list[str], option_name: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        key, separator, entry = value.partition("=")
        if not separator or not key or not entry:
            raise ConfigError(f"{option_name} entries must use NAME=VALUE syntax: {value}")
        mapping[key] = entry
    return mapping
