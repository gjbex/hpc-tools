from __future__ import annotations

from dataclasses import dataclass
from email.parser import Parser
import json
from pathlib import Path
import re

PACKAGE_CALL_RE = re.compile(
    r"\b(?:library|require|requireNamespace)\(\s*(?:[\"']?([A-Za-z][A-Za-z0-9._]*)[\"']?)"
)
PACKAGE_OPERATOR_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9._]*):::{0,2}[A-Za-z][A-Za-z0-9._]*")
SOURCE_CALL_RE = re.compile(r"\bsource\(\s*[\"']([^\"']+)[\"']")
BASE_PACKAGES = {
    "base", "compiler", "datasets", "graphics", "grDevices", "grid", "methods",
    "parallel", "splines", "stats", "stats4", "tcltk", "tools", "utils",
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

def resolve_package_list(scan: ScanResult, explicit_packages: list[str] | None) -> list[str]:
    packages = sorted(scan.packages)
    if explicit_packages:
        packages = sorted(set(packages) | set(explicit_packages))
    return packages
