from __future__ import annotations

import argparse
from typing import Any


def register(subparsers: Any, profile: Any, handlers: Any) -> None:
    register_status(subparsers, profile, handlers)
    register_limits(subparsers, handlers)
    register_accounting(subparsers, profile, handlers)
    register_lifecycle(subparsers, profile, handlers)


def register_status(subparsers: Any, profile: Any, handlers: Any) -> None:
    if profile is None or profile.status_url:
        status_parser = subparsers.add_parser(
            "status",
            help="Show site status, quota, balance, and local submissions",
        )
        status_parser.set_defaults(handler=handlers.cmd_status)


def register_accounting(subparsers: Any, profile: Any, handlers: Any) -> None:
    if profile is None or profile.sam_quote_command:
        quote_parser = subparsers.add_parser("quote", help="Estimate Slurm credits for a job")
        quote_parser.add_argument(
            "quote_args",
            nargs=argparse.REMAINDER,
            help="sam-quote submit command and Slurm options, e.g. srun -M wice -p gpu_a100 -A account",
        )
        quote_parser.set_defaults(handler=handlers.cmd_quote)

    if profile is None or profile.sam_balance_command:
        balance_parser = subparsers.add_parser("balance", help="Show Slurm account credit balances")
        balance_parser.set_defaults(handler=handlers.cmd_balance)

    if profile is None or profile.sam_statement_command:
        statement_parser = subparsers.add_parser("statement", help="Show Slurm account credit transactions")
        statement_parser.add_argument("--account", required=True, help="Slurm account name")
        statement_parser.add_argument("--start", help="Start date in YYYY-mm-dd format")
        statement_parser.add_argument("--end", help="End date in YYYY-mm-dd format")
        statement_parser.set_defaults(handler=handlers.cmd_statement)


def register_lifecycle(subparsers: Any, profile: Any, handlers: Any) -> None:
    submit_parser = subparsers.add_parser("submit", help="Submit a Slurm job script")
    submit_parser.add_argument("jobscript", help="Job script path relative to --directory")
    submit_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory from which to run sbatch",
    )
    submit_parser.add_argument(
        "--test-only",
        action="store_true",
        help="Run sbatch --test-only instead of submitting",
    )
    submit_parser.add_argument(
        "--validate-first",
        action="store_true",
        help="Run sbatch --test-only with the same options before submitting",
    )
    handlers.add_submit_override_arguments(submit_parser)
    submit_parser.set_defaults(handler=handlers.cmd_submit)

    jobs_parser = subparsers.add_parser("jobs", help="Show current user's Slurm jobs")
    jobs_parser.add_argument(
        "--cluster",
        "-M",
        default="all",
        help="Slurm cluster name; defaults to all visible clusters",
    )
    jobs_parser.set_defaults(handler=handlers.cmd_jobs)

    job_parser = subparsers.add_parser("job", help="Show status for one Slurm job")
    job_parser.add_argument("jobid", help="Slurm job ID")
    job_parser.add_argument(
        "--cluster",
        "-M",
        default="all",
        help="Slurm cluster name; defaults to all visible clusters",
    )
    job_parser.set_defaults(handler=handlers.cmd_job)

    if profile is None or profile.queue_command:
        queue_parser = subparsers.add_parser("queue", help="Show remote Slurm queue occupancy")
        queue_parser.set_defaults(handler=handlers.cmd_queue)

    sacct_parser = subparsers.add_parser("sacct", help="Show Slurm accounting for a job")
    sacct_parser.add_argument("jobid", help="Slurm job ID")
    sacct_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    sacct_parser.set_defaults(handler=handlers.cmd_sacct)


def register_limits(subparsers: Any, handlers: Any) -> None:
    limits_parser = subparsers.add_parser(
        "slurm-limits",
        help="Show Slurm partition, controller, QoS, and association limits",
    )
    limits_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    limits_parser.add_argument("--partition", "-p", help="Slurm partition name")
    limits_parser.add_argument("--qos", help="Limit QoS output to one QoS name")
    limits_parser.set_defaults(handler=handlers.cmd_slurm_limits)
