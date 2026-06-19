from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shlex
from pathlib import Path

from hpc_tools.config import ConfigError, Profile
from hpc_tools.plugins.python.dependencies import resolve_package_list, scan_target
from hpc_tools.ssh import run_remote_capture

STATUS_LINE_RE = re.compile(r"^(?P<package>[A-Za-z0-9_.-]+)\t(?P<status>OK|MISSING)$")

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

def check_packages(
    profile: Profile,
    *,
    target: Path,
    explicit_packages: list[str] | None,
    modules: list[str],
    dry_run: bool = False,
) -> CheckResult:
    scan = scan_target(target)
    packages = resolve_package_list(scan, explicit_packages)
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

