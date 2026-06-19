from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from hpc_tools.config import ConfigError


CXX_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".ipp",
}
BUILD_FILE_NAMES = {
    "CMakeLists.txt",
    "CMakePresets.json",
    "Makefile",
    "makefile",
    "meson.build",
    "compile_commands.json",
}
HPC_SENSITIVE_PACKAGES = {
    "BLAS",
    "CUDA",
    "CUDAToolkit",
    "FFTW",
    "HDF5",
    "Kokkos",
    "LAPACK",
    "MPI",
    "NetCDF",
    "OpenMP",
    "PETSc",
    "Trilinos",
}
HEADER_PACKAGE_HINTS = {
    "CLI/CLI.hpp": "CLI11",
    "catch2/catch_test_macros.hpp": "Catch2",
    "catch2/catch.hpp": "Catch2",
    "doctest/doctest.h": "doctest",
    "fmt/core.h": "fmt",
    "fmt/format.h": "fmt",
    "gtest/gtest.h": "GTest",
    "nlohmann/json.hpp": "nlohmann_json",
    "spdlog/spdlog.h": "spdlog",
}
FETCHCONTENT_PACKAGES = {
    "CLI11": (
        "https://github.com/CLIUtils/CLI11.git",
        "v2.4.2",
        "CLI11::CLI11",
        "MYPROJECT_FETCH_CLI11",
    ),
    "Catch2": (
        "https://github.com/catchorg/Catch2.git",
        "v3.7.1",
        "Catch2::Catch2WithMain",
        "MYPROJECT_FETCH_CATCH2",
    ),
    "doctest": (
        "https://github.com/doctest/doctest.git",
        "v2.4.11",
        "doctest::doctest",
        "MYPROJECT_FETCH_DOCTEST",
    ),
    "fmt": (
        "https://github.com/fmtlib/fmt.git",
        "11.0.2",
        "fmt::fmt",
        "MYPROJECT_FETCH_FMT",
    ),
    "nlohmann_json": (
        "https://github.com/nlohmann/json.git",
        "v3.11.3",
        "nlohmann_json::nlohmann_json",
        "MYPROJECT_FETCH_NLOHMANN_JSON",
    ),
    "spdlog": (
        "https://github.com/gabime/spdlog.git",
        "v1.14.1",
        "spdlog::spdlog",
        "MYPROJECT_FETCH_SPDLOG",
    ),
}


@dataclass(frozen=True)
class DependencyFinding:
    name: str
    source: str
    file: str
    hpc_sensitive: bool
    fetchcontent_candidate: bool


@dataclass(frozen=True)
class CxxScanResult:
    target: Path
    build_files: list[Path]
    source_files: list[Path]
    dependencies: list[DependencyFinding]
    notes: list[str]


@dataclass(frozen=True)
class FetchContentPackage:
    name: str
    repository: str
    tag: str
    target: str
    option: str


def scan_target(target: Path) -> CxxScanResult:
    root = target.expanduser()
    if not root.exists():
        raise ConfigError(f"target does not exist: {target}")
    build_files, source_files = _collect_files(root)
    findings = []
    for path in build_files:
        if path.name == "CMakeLists.txt":
            findings.extend(_scan_cmake_file(path))
    for path in source_files:
        findings.extend(_scan_source_file(path))
    findings = _deduplicate_findings(findings)
    notes = _notes_for_result(build_files, findings)
    return CxxScanResult(
        target=root.resolve(),
        build_files=build_files,
        source_files=source_files,
        dependencies=findings,
        notes=notes,
    )


def fetchcontent_package(name: str) -> FetchContentPackage:
    package_name = _canonical_fetchcontent_name(name)
    try:
        repository, tag, target, option = FETCHCONTENT_PACKAGES[package_name]
    except KeyError as error:
        supported = ", ".join(sorted(FETCHCONTENT_PACKAGES))
        raise ConfigError(f"unsupported FetchContent package '{name}'. Supported packages: {supported}") from error
    return FetchContentPackage(package_name, repository, tag, target, option)


def render_fetchcontent_snippet(
    package: FetchContentPackage,
    *,
    project_option_prefix: str = "MYPROJECT",
    default_on: bool = True,
) -> str:
    option_name = (
        package.option
        if project_option_prefix == "MYPROJECT"
        else f"{project_option_prefix}_FETCH_{_option_suffix(package.name)}"
    )
    default = "ON" if default_on else "OFF"
    return f"""option({option_name} "Fetch {package.name} if it is not installed" {default})

find_package({package.name} CONFIG QUIET)

if(NOT {package.name}_FOUND AND {option_name})
  include(FetchContent)
  FetchContent_Declare(
    {package.name}
    GIT_REPOSITORY {package.repository}
    GIT_TAG {package.tag}
  )
  FetchContent_MakeAvailable({package.name})
endif()

if(NOT {package.name}_FOUND AND NOT TARGET {package.target})
  message(FATAL_ERROR "{package.name} not found. Install it, set FETCHCONTENT_SOURCE_DIR_{package.name}, or enable {option_name}.")
endif()

target_link_libraries(<target> PRIVATE {package.target})
"""


def result_to_dict(result: CxxScanResult) -> dict[str, object]:
    return {
        "target": str(result.target),
        "build_files": [str(path) for path in result.build_files],
        "source_files": [str(path) for path in result.source_files],
        "dependencies": [
            {
                "name": finding.name,
                "source": finding.source,
                "file": finding.file,
                "hpc_sensitive": finding.hpc_sensitive,
                "fetchcontent_candidate": finding.fetchcontent_candidate,
            }
            for finding in result.dependencies
        ],
        "notes": result.notes,
    }


def _collect_files(target: Path) -> tuple[list[Path], list[Path]]:
    if target.is_file():
        build_files = [target] if target.name in BUILD_FILE_NAMES else []
        source_files = [target] if target.suffix in CXX_SUFFIXES else []
        return build_files, source_files

    build_files: list[Path] = []
    source_files: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file() or _skip_path(path):
            continue
        if path.name in BUILD_FILE_NAMES:
            build_files.append(path)
        if path.suffix in CXX_SUFFIXES:
            source_files.append(path)
    return sorted(build_files), sorted(source_files)


def _scan_cmake_file(path: Path) -> list[DependencyFinding]:
    text = _strip_cmake_comments(path.read_text(encoding="utf-8", errors="replace"))
    findings = []
    for match in re.finditer(r"\bfind_package\s*\(\s*([A-Za-z_][A-Za-z0-9_:+.-]*)", text, re.IGNORECASE):
        findings.append(_finding(match.group(1), "find_package", path))
    for match in re.finditer(r"\bFetchContent_Declare\s*\(\s*([A-Za-z_][A-Za-z0-9_:+.-]*)", text, re.IGNORECASE):
        findings.append(_finding(match.group(1), "FetchContent", path))
    return findings


def _scan_source_file(path: Path) -> list[DependencyFinding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for match in re.finditer(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", text, re.MULTILINE):
        header = match.group(1)
        package = HEADER_PACKAGE_HINTS.get(header)
        if package:
            findings.append(_finding(package, f"include:{header}", path))
    return findings


def _finding(name: str, source: str, path: Path) -> DependencyFinding:
    canonical = _canonical_dependency_name(name)
    return DependencyFinding(
        name=canonical,
        source=source,
        file=str(path),
        hpc_sensitive=canonical in HPC_SENSITIVE_PACKAGES,
        fetchcontent_candidate=canonical in FETCHCONTENT_PACKAGES and canonical not in HPC_SENSITIVE_PACKAGES,
    )


def _deduplicate_findings(findings: list[DependencyFinding]) -> list[DependencyFinding]:
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for finding in findings:
        key = (finding.name, finding.source, finding.file)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return sorted(unique, key=lambda item: (item.name.lower(), item.file, item.source))


def _notes_for_result(build_files: list[Path], findings: list[DependencyFinding]) -> list[str]:
    notes = []
    if not any(path.name == "CMakeLists.txt" for path in build_files):
        notes.append("No CMakeLists.txt found; CMake-oriented advice may not apply.")
    if any(finding.hpc_sensitive for finding in findings):
        notes.append("HPC-sensitive dependencies should usually come from modules, Spack, or site packages rather than FetchContent.")
    if any(finding.fetchcontent_candidate for finding in findings):
        notes.append("Small FetchContent candidates should be pinned and overridable for network-restricted cluster builds.")
    return notes


def _canonical_fetchcontent_name(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_")
    aliases = {
        "cli11": "CLI11",
        "catch2": "Catch2",
        "doctest": "doctest",
        "fmt": "fmt",
        "nlohmann_json": "nlohmann_json",
        "json": "nlohmann_json",
        "spdlog": "spdlog",
    }
    return aliases.get(normalized, name.strip())


def _canonical_dependency_name(name: str) -> str:
    aliases = {
        "CUDAToolkit": "CUDAToolkit",
        "NLOHMANN_JSON": "nlohmann_json",
        "nlohmann_json": "nlohmann_json",
        "OpenMP": "OpenMP",
    }
    return aliases.get(name, aliases.get(name.strip(), name.strip()))


def _option_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).upper()


def _strip_cmake_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def _skip_path(path: Path) -> bool:
    ignored = {".git", ".venv", "venv", "build", "_build", "cmake-build-debug", "cmake-build-release"}
    return any(part in ignored for part in path.parts)
