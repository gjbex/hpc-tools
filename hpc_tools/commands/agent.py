from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hpc_tools import agent_audit
from hpc_tools.config import Profile


def register(subparsers: Any, handlers: Any) -> None:
    agent_parser = subparsers.add_parser(
        "agent",
        help="Inspect and export restricted-agent audit state",
    )
    agent_subparsers = agent_parser.add_subparsers(
        dest="agent_command",
        metavar="<subcommand>",
        required=True,
    )
    for name, help_text, handler in (
        (
            "audit",
            "Show a read-only joined view of one protected delegation ledger",
            handlers.cmd_agent_audit,
        ),
        (
            "export",
            "Export a protected delegation audit report as JSON",
            handlers.cmd_agent_export,
        ),
    ):
        command = agent_subparsers.add_parser(name, help=help_text)
        command.add_argument("--ledger", type=Path, required=True)
        command.add_argument(
            "--database",
            type=Path,
            help="Submission database; defaults to the hpc-tools config directory",
        )
        command.add_argument(
            "--delegation-id",
            help="Limit the report to one delegation identifier",
        )
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--force", action="store_true")
        command.set_defaults(handler=handler, operation_id=f"agent.{name}")


def cmd_agent_audit(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    report = agent_audit.build_report(
        args.ledger,
        submissions_database=args.database,
        delegation_id=args.delegation_id,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(agent_audit.format_report(report))
    return 0


def cmd_agent_export(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    report = agent_audit.build_report(
        args.ledger,
        submissions_database=args.database,
        delegation_id=args.delegation_id,
    )
    output = agent_audit.write_report(report, args.output, force=args.force)
    result = {"delegations": len(report["delegations"]), "output": str(output)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"Wrote audit report for {result['delegations']} delegation(s) to {output}"
        )
    return 0
