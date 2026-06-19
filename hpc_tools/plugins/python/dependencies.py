from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from packaging.requirements import InvalidRequirement, Requirement
import yaml

from hpc_tools.config import _load_toml

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
        _scan_pyproject_dependencies(pyproject, packages, notes)

def _requirement_files(directory: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in ("requirements.txt", "requirements-*.txt"):
        for path in sorted(directory.glob(pattern)):
            if path.is_file() and path not in paths:
                paths.append(path)
    return paths

def _scan_requirements(path: Path, packages: dict[str, list[PackageHit]], notes: list[str]) -> None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = _strip_requirement_comment(line)
        if not stripped or stripped.startswith(("-", "git+", "http://", "https://")):
            continue
        requirement = _parse_requirement(stripped, path, line_number, notes)
        if requirement:
            _record_package(
                packages,
                _dependency_import_name_from_raw(stripped, _normalize_requirement_name(requirement.name)),
                path,
                line_number,
                "requirements",
            )

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
        stripped = _strip_requirement_comment(line)
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
        requirement = _parse_requirement(stripped, resolved, line_number, notes)
        if requirement:
            _append_dependency_spec(
                requirements,
                name=_normalize_requirement_name(requirement.name),
                source="requirements",
                file=resolved,
                line_number=line_number,
                raw=stripped,
            )

def _scan_pyproject_dependencies(path: Path, packages: dict[str, list[PackageHit]], notes: list[str]) -> None:
    for raw, line_number, source in _iter_pyproject_dependency_strings(path, notes):
        requirement = _parse_requirement(raw, path, line_number, notes)
        if not requirement:
            continue
        _record_package(
            packages,
            _dependency_import_name_from_raw(raw, _normalize_requirement_name(requirement.name)),
            path,
            line_number,
            source,
        )

def _inspect_pyproject_dependencies(
    path: Path,
    dependencies: list[DependencySpec],
    notes: list[str],
) -> None:
    for raw, line_number, source in _iter_pyproject_dependency_strings(path, notes):
        requirement = _parse_requirement(raw, path, line_number, notes)
        if not requirement:
            continue
        _append_dependency_spec(
            dependencies,
            name=_normalize_requirement_name(requirement.name),
            source=source,
            file=path,
            line_number=line_number,
            raw=raw,
        )

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
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        notes.append(f"Could not parse {path}: {error}")
        return
    if data is None:
        return
    if not isinstance(data, dict):
        notes.append(f"{path} must contain a YAML mapping at the top level.")
        return

    raw_channels = data.get("channels", [])
    if raw_channels is None:
        raw_channels = []
    if isinstance(raw_channels, list):
        channels.extend(str(channel) for channel in raw_channels if channel is not None)
    else:
        notes.append(f"{path}: channels must be a list.")

    raw_dependencies = data.get("dependencies", [])
    if raw_dependencies is None:
        raw_dependencies = []
    if not isinstance(raw_dependencies, list):
        notes.append(f"{path}: dependencies must be a list.")
        return

    for entry in raw_dependencies:
        if isinstance(entry, str):
            line_number = _line_number_containing(path, entry)
            name = _dependency_name_from_conda(entry)
            if not name:
                notes.append(f"{path}:{line_number} contains a conda dependency that was not statically resolved.")
                continue
            _append_dependency_spec(
                conda_dependencies,
                name=_normalize_requirement_name(name),
                source="environment.yml conda",
                file=path,
                line_number=line_number,
                raw=entry,
            )
            if name == "python":
                python_versions.append(entry)
            if _looks_like_binary_dependency(name):
                binary_hints.append(entry)
            continue

        if isinstance(entry, dict) and "pip" in entry:
            pip_entries = entry["pip"]
            if not isinstance(pip_entries, list):
                notes.append(f"{path}: environment.yml pip dependencies must be a list.")
                continue
            for value in pip_entries:
                line_number = _line_number_containing(path, str(value))
                if not isinstance(value, str):
                    notes.append(f"{path}:{line_number} contains a non-string pip dependency.")
                    continue
                requirement = _parse_requirement(value, path, line_number, notes)
                if not requirement:
                    continue
                _append_dependency_spec(
                    pip_dependencies,
                    name=_normalize_requirement_name(requirement.name),
                    source="environment.yml pip",
                    file=path,
                    line_number=line_number,
                    raw=value,
                )
            continue

        notes.append(f"{path} contains an environment dependency that was not statically resolved: {entry!r}")

def _strip_requirement_comment(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    for marker in (" #", "\t#"):
        index = stripped.find(marker)
        if index != -1:
            return stripped[:index].strip()
    return stripped

def _parse_requirement(
    value: str,
    path: Path,
    line_number: int,
    notes: list[str],
) -> Requirement | None:
    try:
        return Requirement(value)
    except InvalidRequirement:
        notes.append(f"{path}:{line_number} contains a requirement that was not statically resolved.")
        return None

def _iter_pyproject_dependency_strings(
    path: Path,
    notes: list[str],
) -> list[tuple[str, int, str]]:
    try:
        data = _load_toml(path)
    except ConfigError as error:
        notes.append(str(error))
        return []
    project = data.get("project")
    if project is None:
        return []
    if not isinstance(project, dict):
        notes.append(f"{path}: [project] must be a table.")
        return []

    dependencies: list[tuple[str, int, str]] = []
    raw_dependencies = project.get("dependencies", [])
    if raw_dependencies is None:
        raw_dependencies = []
    if isinstance(raw_dependencies, list) and all(isinstance(item, str) for item in raw_dependencies):
        dependencies.extend(
            (raw, _line_number_containing(path, raw), "pyproject dependencies")
            for raw in raw_dependencies
        )
    elif raw_dependencies:
        notes.append(f"{path}: project.dependencies must be a list of strings.")

    optional = project.get("optional-dependencies", {})
    if optional is None:
        optional = {}
    if isinstance(optional, dict):
        for extra, values in optional.items():
            if isinstance(values, list) and all(isinstance(item, str) for item in values):
                dependencies.extend(
                    (raw, _line_number_containing(path, raw), f"pyproject optional-dependencies.{extra}")
                    for raw in values
                )
            else:
                notes.append(f"{path}: project.optional-dependencies.{extra} must be a list of strings.")
    elif optional:
        notes.append(f"{path}: project.optional-dependencies must be a table.")

    return dependencies

def _line_number_containing(path: Path, needle: str) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="latin-1").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if needle in line:
            return line_number
    return 1

def _normalize_requirement_name(name: str) -> str:
    return name.strip().split("[", 1)[0].replace("-", "_")

def _dependency_name_from_requirement(value: str) -> str | None:
    try:
        requirement = Requirement(value)
    except InvalidRequirement:
        return None
    return requirement.name

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

def resolve_package_list(scan: ScanResult, explicit_packages: list[str] | None) -> list[str]:
    packages = sorted(scan.packages)
    if explicit_packages:
        packages = sorted(set(packages) | set(explicit_packages))
    return packages
