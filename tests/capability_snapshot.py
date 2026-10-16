"""Snapshot the current public surface without executing command handlers.

WP1 test support only: this is synchronized inventory input, not a
backward-compatibility contract or runtime policy implementation.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
from pathlib import Path
import tempfile
from unittest import mock

from hpc_tools import agent_cleanup, cli, mcp_bridge, mcp_server, restricted_launch
from hpc_tools.mcp import server as server_module


def parser_schema(parser: argparse.ArgumentParser) -> dict:
    """Capture grammar, not unstable formatted help or argparse internals."""
    arguments = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        arguments.append({
            "dest": action.dest,
            "options": action.option_strings,
            # Positional ``Action.required`` changed for REMAINDER between
            # supported CPython releases. Record the public grammar instead of
            # that implementation detail: optionals honor ``required`` while
            # positionals are required unless their nargs makes them optional.
            "required": (
                action.required
                if action.option_strings
                else action.nargs not in ("?", "*", argparse.REMAINDER)
            ),
            "nargs": action.nargs,
            "default": action.default,
            "choices": list(action.choices) if action.choices is not None else None,
            "type": getattr(action.type, "__name__", None),
        })
    handler = parser.get_default("handler")
    return {
        "arguments": arguments,
        "handler": f"{handler.__module__}:{handler.__name__}" if handler else None,
    }


def parser_tree(parser: argparse.ArgumentParser, prefix: str = "") -> dict:
    result = {prefix: parser_schema(parser)}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                result.update(parser_tree(child, f"{prefix} {name}".strip()))
    return result


def builtin_cli_tree(profile=None) -> dict:
    # User-installed entry points must not change the repository baseline or
    # execute import-time plugin code while collecting it.
    with mock.patch("hpc_tools.plugin_system._iter_plugin_entry_points", return_value=[]):
        return parser_tree(cli.build_parser(profile))


def pre_policy_no_config_examples() -> dict[str, bool]:
    """Characterize current bypasses that later policy work may remove."""
    examples = {
        "no-command": [],
        "root-help": ["--help"],
        "profile-command-help": ["--profile", "fixture", "jobs", "--help"],
        "paths": ["paths"],
        "write-probe-stdout": ["write-probe", "hardware"],
        "write-probe-profile": ["--profile", "fixture", "write-probe", "hardware"],
        "write-probe-mail": ["write-probe", "hardware", "--mail-notifications"],
        "submissions-list": ["submissions", "list"],
        "submissions-observe": ["submissions", "observe", "123"],
        "submissions-mark": ["submissions", "mark-collected", "run-1"],
        "references-import": ["references", "import", "archive.tar.gz"],
        "references-create": ["references", "create", "fixture"],
        "plugins-list": ["plugins", "list"],
        "agent-audit": ["agent", "audit"],
        "benchmark-summarize": ["benchmark", "summarize", "result.json"],
        "cxx-scan": ["cxx", "scan", "."],
        "python-scan": ["python", "scan", "."],
        "python-check": ["python", "check", "requirements.txt"],
        "r-scan": ["r", "scan", "."],
        "r-check": ["r", "check", "script.R"],
        "doctor": ["doctor"],
    }
    with mock.patch("hpc_tools.plugin_system._iter_plugin_entry_points", return_value=[]):
        return {
            name: cli._should_parse_without_config(argv)
            for name, argv in examples.items()
        }


def entry_parser(main) -> argparse.ArgumentParser:
    class CapturedParser(Exception):
        pass

    captured = []

    def stop(parser, *args, **kwargs):
        captured.append(parser)
        raise CapturedParser

    with mock.patch.object(argparse.ArgumentParser, "parse_args", stop):
        try:
            main([])
        except CapturedParser:
            return captured[0]
    raise AssertionError("entry point did not construct an argparse parser")


def callable_schema(function) -> list[dict]:
    return signature_schema(inspect.signature(function))


def signature_schema(signature: inspect.Signature) -> list[dict]:
    return [{
        "name": parameter.name,
        "kind": parameter.kind.name,
        "annotation": str(parameter.annotation),
        "required": parameter.default is inspect.Parameter.empty,
        "default": None if parameter.default is inspect.Parameter.empty else parameter.default,
    } for parameter in signature.parameters.values()]


def current_surface_snapshot() -> dict:
    consoles = {
        "hpc": "hpc_tools.cli:main",
        "hpc-mcp": "hpc_tools.mcp_server:main",
        "hpc-mcp-bridge": "hpc_tools.mcp_bridge:main",
        "hpc-mcp-relay": "hpc_tools.mcp_bridge:relay_main",
        "hpc-agent-launch": "hpc_tools.restricted_launch:main",
        "hpc-agent-reap": "hpc_tools.agent_cleanup:main",
    }
    relay_tree = parser_tree(entry_parser(mcp_bridge.relay_main))
    return {
        "format_version": 1,
        "snapshot_semantics": (
            "current capability-transition surface; update intentionally with implementation, "
            "inventory, documentation, examples, and tests"
        ),
        "cli": builtin_cli_tree(),
        "pre_policy_no_config_examples": pre_policy_no_config_examples(),
        "console_entry_points": consoles,
        "console_parsers": {
            "hpc-mcp": parser_tree(entry_parser(server_module.main)),
            "hpc-mcp-bridge": parser_tree(entry_parser(mcp_bridge.main)),
            "hpc-mcp-relay": {"connect": relay_tree["connect"]},
            "hpc-agent-launch": parser_tree(entry_parser(restricted_launch.main)),
            "hpc-agent-reap": parser_tree(entry_parser(agent_cleanup.main)),
        },
        "mcp_full": {
            name: signature_schema(server_module._bound_tool_signature(
                getattr(mcp_server, name),
            ))
            for name in mcp_server.FULL_TOOL_NAMES
        },
        "mcp_slurm_job": {
            name: signature_schema(server_module._bound_tool_signature(
                getattr(mcp_server, name), delegated=True,
            ))
            for name in mcp_server.SLURM_JOB_TOOL_NAMES
        },
        "resources": {
            "full": list(mcp_server.FULL_RESOURCE_URIS),
            "full_templates": list(mcp_server.FULL_RESOURCE_TEMPLATES),
            "slurm_job": list(mcp_server.SLURM_JOB_RESOURCE_URIS),
            "slurm_job_templates": list(mcp_server.SLURM_JOB_RESOURCE_TEMPLATES),
        },
    }


def full_mcp_input_schemas() -> dict:
    """Collect actual FastMCP discovery, without calling tools or resources."""
    async def collect():
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "hpc-tools" / "config.toml"
            config.parent.mkdir(parents=True)
            reference = root / "hpc-tools" / "reference-sets" / "snapshot"
            reference.mkdir(parents=True)
            for name in ("hardware.md", "slurm.md", "storage.md"):
                (reference / name).write_text(f"# {name}\n", encoding="utf-8")
            (reference / "manifest.toml").write_text(
                """format_version = "1"
[files]
hardware_reference = "hardware.md"
slurm_reference = "slurm.md"
storage_reference = "storage.md"
""",
                encoding="utf-8",
            )
            config.write_text(
                """default_profile = "snapshot"

[profiles.snapshot]
ssh_target = "snapshot"
projects_dir = "/work"
status_url = "https://example.invalid/status"
quota_command = "quota"
queue_command = "queue"
sam_balance_command = "balance"
sam_statement_command = "statement"
sam_quote_command = "quote"
hardware_reference = "/tmp/hardware.md"
slurm_reference = "/tmp/slurm.md"
storage_reference = "/tmp/storage.md"
reference_set = "snapshot"

[profiles.snapshot.capabilities]
version = 1
max_level = "job-lifecycle"
scopes = ["accounting.read", "config.read.raw", "delegation-ledger.read", "job.validate", "local-state.write", "remote-filesystem.list", "remote-filesystem.read", "remote-install.write", "remote-workspace.delete", "remote-workspace.write", "submission-record.write"]

[profiles.snapshot.capabilities.remote_roots]
list = ["/work"]
read = ["/work"]
write = ["/work"]
delete = ["/work"]
install = ["/work"]
""",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"HPC_TOOLS_CONFIG": str(config), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                server = mcp_server.create_server(preset="full")
                return {tool.name: tool.inputSchema for tool in await server.list_tools()}

    return asyncio.run(collect())
