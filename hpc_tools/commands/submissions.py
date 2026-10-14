from __future__ import annotations

from pathlib import Path
from typing import Any

import argparse

from hpc_tools import submissions
from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.config import Profile
from hpc_tools.execution import run_command_capture


def register(subparsers: Any, handlers: Any) -> None:
    submissions_parser = subparsers.add_parser(
        "submissions",
        help="Inspect and update the local Slurm submission database",
    )
    submissions_parser.add_argument(
        "--database",
        type=Path,
        help="Submission SQLite database path; defaults to the hpc-tools config directory",
    )
    submissions_subparsers = submissions_parser.add_subparsers(
        dest="submissions_command",
        metavar="<subcommand>",
        required=True,
    )

    submissions_list_parser = submissions_subparsers.add_parser(
        "list",
        help="List active submissions by replaying stored events",
    )
    submissions_list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include closed submissions",
    )
    submissions_list_parser.set_defaults(
        handler=handlers.cmd_submissions_list,
        operation_id="submissions.list",
    )

    submissions_observe_parser = submissions_subparsers.add_parser(
        "observe",
        help="Query Slurm accounting for active submissions and store observed events",
    )
    submissions_observe_parser.add_argument(
        "run_id",
        nargs="?",
        help="Run ID to observe; defaults to all active runs",
    )
    submissions_observe_parser.set_defaults(
        handler=handlers.cmd_submissions_observe,
        operation_id="submissions.observe",
    )

    submissions_collect_parser = submissions_subparsers.add_parser(
        "mark-collected",
        help="Store a results_collected event for a run",
    )
    submissions_collect_parser.add_argument("run_id", help="Run ID")
    submissions_collect_parser.add_argument(
        "--path",
        required=True,
        help="Local or remote result path",
    )
    submissions_collect_parser.set_defaults(
        handler=handlers.cmd_submissions_mark_collected,
        operation_id="submissions.mark-collected",
    )

    submissions_analyse_parser = submissions_subparsers.add_parser(
        "mark-analysed",
        help="Store an analysed event for a run",
    )
    submissions_analyse_parser.add_argument("run_id", help="Run ID")
    submissions_analyse_parser.add_argument("--path", required=True, help="Report or notebook path")
    submissions_analyse_parser.set_defaults(
        handler=handlers.cmd_submissions_mark_analysed,
        operation_id="submissions.mark-analysed",
    )

    submissions_close_parser = submissions_subparsers.add_parser(
        "close",
        help="Store a closed event for a run",
    )
    submissions_close_parser.add_argument("run_id", help="Run ID")
    submissions_close_parser.add_argument("--reason", help="Reason for closing this run")
    submissions_close_parser.set_defaults(
        handler=handlers.cmd_submissions_close,
        operation_id="submissions.close",
    )

def cmd_submissions_list(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("submissions.list", profile, namespace_arguments(args))
    events = submissions.read_events(args.database)
    records = (
        submissions.records_from_events(events, profile=profile.name)
        if args.all
        else submissions.active_records(events, profile=profile.name)
    )
    print(submissions.format_records(records))
    return 0

def cmd_submissions_observe(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("submissions.observe", profile, namespace_arguments(args))
    events = submissions.read_events(args.database)
    records = submissions.active_records(events, profile=profile.name)
    if args.run_id:
        selected = submissions.require_record_for_profile(
            events,
            run_id=args.run_id,
            profile=profile.name,
        )
        records = [record for record in records if record.run_id == selected.run_id]
    if not records:
        print("No active submissions to observe.")
        return 0

    observed_records = []
    for record in records:
        command = submissions.sacct_observe_command(record.job_id, record.cluster)
        completed = run_command_capture(profile, command, dry_run=args.dry_run)
        if args.dry_run:
            continue
        if completed.returncode != 0:
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            continue
        raw_output = completed.stdout
        state, exit_code, elapsed = submissions.parse_sacct_observation(raw_output, record.job_id)
        submissions.append_event(
            submissions.observed_event(
                record,
                state=state,
                exit_code=exit_code,
                elapsed=elapsed,
                raw_output=raw_output,
            ),
            path=args.database,
        )
        observed_records.append(record)

    if args.dry_run:
        print("Dry run; no observations appended.")
        return 0

    refreshed_events = submissions.read_events(args.database)
    observed_run_ids = {record.run_id for record in observed_records}
    refreshed_records = [
        record
        for record in submissions.records_from_events(
            refreshed_events,
            profile=profile.name,
        )
        if record.run_id in observed_run_ids
    ]
    print(submissions.format_records(refreshed_records))
    return 0

def cmd_submissions_mark_collected(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("submissions.mark-collected", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; results_collected event not appended for {args.run_id}.")
        return 0
    events = submissions.read_events(args.database)
    submissions.require_record_for_profile(events, run_id=args.run_id, profile=profile.name)
    submissions.append_event(
        submissions.mark_event(
            args.run_id,
            "results_collected",
            profile=profile.name,
            path=args.path,
        ),
        path=args.database,
    )
    return 0

def cmd_submissions_mark_analysed(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("submissions.mark-analysed", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; analysed event not appended for {args.run_id}.")
        return 0
    events = submissions.read_events(args.database)
    submissions.require_record_for_profile(events, run_id=args.run_id, profile=profile.name)
    submissions.append_event(
        submissions.mark_event(
            args.run_id,
            "analysed",
            profile=profile.name,
            path=args.path,
        ),
        path=args.database,
    )
    return 0

def cmd_submissions_close(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("submissions.close", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; closed event not appended for {args.run_id}.")
        return 0
    events = submissions.read_events(args.database)
    submissions.require_record_for_profile(events, run_id=args.run_id, profile=profile.name)
    submissions.append_event(
        submissions.mark_event(
            args.run_id,
            "closed",
            profile=profile.name,
            reason=args.reason,
        ),
        path=args.database,
    )
    return 0
