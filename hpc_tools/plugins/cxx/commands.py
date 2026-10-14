from __future__ import annotations

import argparse
import json
from pathlib import Path

from hpc_tools.config import Profile
from hpc_tools.plugin_system import PLUGIN_CONTRACT_VERSION, builtin_operations
from hpc_tools.plugins.cxx.dependencies import (
    CxxScanResult,
    fetchcontent_package,
    render_fetchcontent_snippet,
    result_to_dict,
    scan_target,
)


class CxxSupportPlugin:
    name = "cxx"
    description = "C/C++ CMake dependency scanning and FetchContent helpers."
    contract_version = PLUGIN_CONTRACT_VERSION
    operations = builtin_operations("cxx.scan", "cxx.fetchcontent")

    def register(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        profile: Profile | None,
    ) -> None:
        del profile
        parser = subparsers.add_parser(
            "cxx",
            help="C/C++ build helpers provided by the bundled C++ plugin",
        )
        cxx_subparsers = parser.add_subparsers(dest="cxx_command", metavar="<subcommand>", required=True)

        scan_parser = cxx_subparsers.add_parser(
            "scan",
            help="Scan CMake and C/C++ sources for dependency hints",
        )
        scan_parser.add_argument("target", type=Path, help="C/C++ project directory or build/source file")
        scan_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        scan_parser.set_defaults(handler=cmd_cxx_scan, operation_id="cxx.scan")

        fetch_parser = cxx_subparsers.add_parser(
            "fetchcontent",
            help="Render a pinned CMake FetchContent snippet for a small C++ dependency",
        )
        fetch_parser.add_argument(
            "package",
            help="Package name, for example CLI11, Catch2, doctest, fmt, nlohmann_json, or spdlog",
        )
        fetch_parser.add_argument(
            "--project-option-prefix",
            default="MYPROJECT",
            help="Prefix for the generated CMake option name",
        )
        fetch_parser.add_argument(
            "--default-off",
            action="store_true",
            help="Generate the fetch option with default OFF instead of ON",
        )
        fetch_parser.set_defaults(
            handler=cmd_cxx_fetchcontent,
            operation_id="cxx.fetchcontent",
        )

    def requires_profile(self, argv: list[str]) -> bool:
        del argv
        return False


def get_plugin() -> CxxSupportPlugin:
    return CxxSupportPlugin()


def cmd_cxx_scan(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    result = scan_target(args.target)
    if args.json:
        print(json.dumps(result_to_dict(result), indent=2, sort_keys=True))
        return 0
    print(format_scan_result(result))
    return 0


def cmd_cxx_fetchcontent(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    package = fetchcontent_package(args.package)
    print(
        render_fetchcontent_snippet(
            package,
            project_option_prefix=args.project_option_prefix,
            default_on=not args.default_off,
        ),
        end="",
    )
    return 0


def format_scan_result(result: CxxScanResult) -> str:
    lines = [
        f"Target: {result.target}",
        f"Build files: {len(result.build_files)}",
        f"Source files: {len(result.source_files)}",
        "",
        "Dependencies:",
    ]
    if not result.dependencies:
        lines.append("- none detected")
    for finding in result.dependencies:
        markers = []
        if finding.hpc_sensitive:
            markers.append("HPC-sensitive")
        if finding.fetchcontent_candidate:
            markers.append("FetchContent candidate")
        suffix = f" ({', '.join(markers)})" if markers else ""
        lines.append(f"- {finding.name}: {finding.source} in {finding.file}{suffix}")
    if result.notes:
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines)
