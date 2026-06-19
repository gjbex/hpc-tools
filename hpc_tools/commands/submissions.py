from __future__ import annotations

from pathlib import Path
from typing import Any


def register(subparsers: Any, handlers: Any) -> None:
    submissions_parser = subparsers.add_parser(
        "submissions",
        help="Inspect and update the local Slurm submission event log",
    )
    submissions_parser.add_argument(
        "--log",
        type=Path,
        help="Submission JSONL log path; defaults to the hpc-tools config directory",
    )
    submissions_subparsers = submissions_parser.add_subparsers(
        dest="submissions_command",
        metavar="<subcommand>",
        required=True,
    )

    submissions_list_parser = submissions_subparsers.add_parser(
        "list",
        help="List active submissions by replaying the event log",
    )
    submissions_list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include closed submissions",
    )
    submissions_list_parser.set_defaults(handler=handlers.cmd_submissions_list)

    submissions_observe_parser = submissions_subparsers.add_parser(
        "observe",
        help="Query Slurm accounting for active submissions and append observed events",
    )
    submissions_observe_parser.add_argument(
        "run_id",
        nargs="?",
        help="Run ID to observe; defaults to all active runs",
    )
    submissions_observe_parser.set_defaults(handler=handlers.cmd_submissions_observe)

    submissions_collect_parser = submissions_subparsers.add_parser(
        "mark-collected",
        help="Append a results_collected event for a run",
    )
    submissions_collect_parser.add_argument("run_id", help="Run ID")
    submissions_collect_parser.add_argument(
        "--path",
        required=True,
        help="Local or remote result path",
    )
    submissions_collect_parser.set_defaults(handler=handlers.cmd_submissions_mark_collected)

    submissions_analyse_parser = submissions_subparsers.add_parser(
        "mark-analysed",
        help="Append an analysed event for a run",
    )
    submissions_analyse_parser.add_argument("run_id", help="Run ID")
    submissions_analyse_parser.add_argument("--path", required=True, help="Report or notebook path")
    submissions_analyse_parser.set_defaults(handler=handlers.cmd_submissions_mark_analysed)

    submissions_close_parser = submissions_subparsers.add_parser(
        "close",
        help="Append a closed event for a run",
    )
    submissions_close_parser.add_argument("run_id", help="Run ID")
    submissions_close_parser.add_argument("--reason", help="Reason for closing this run")
    submissions_close_parser.set_defaults(handler=handlers.cmd_submissions_close)
