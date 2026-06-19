from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex

from hpc_tools.config import ConfigError, Profile
from hpc_tools.plugins.r.dependencies import resolve_package_list, scan_target
from hpc_tools.ssh import run_remote_capture

STATUS_LINE_RE = re.compile(r"^(?P<package>[A-Za-z][A-Za-z0-9._]*)\t(?P<status>OK|MISSING)$")

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
    packages = resolve_package_list(scan, explicit_packages)
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

