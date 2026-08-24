from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import html
import re
import shlex
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from hpc_tools import slurm
from hpc_tools import slurm_contracts
from hpc_tools import submissions
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import run_command, run_command_capture


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

def cmd_queue(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.queue_command:
        raise ConfigError(f"profile '{profile.name}' does not define queue_command")
    return run_command(
        profile,
        slurm.queue_state_command(profile.queue_command),
        dry_run=args.dry_run,
    )

def cmd_balance(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_balance_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_balance_command")
    return run_command(profile, profile.sam_balance_command, dry_run=args.dry_run)

def cmd_statement(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_statement_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_statement_command")
    command = _statement_command(
        profile.sam_statement_command,
        account=args.account,
        start=args.start,
        end=args.end,
    )
    return run_command(profile, command, dry_run=args.dry_run)

def cmd_quote(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_quote_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_quote_command")
    command = _quote_command(profile.sam_quote_command, args.quote_args)
    return run_command(profile, command, dry_run=args.dry_run)

def cmd_status(args: argparse.Namespace, profile: Profile) -> int:
    report = build_status_report(profile, dry_run=args.dry_run)

    for index, section in enumerate(report["sections"]):
        if index:
            print()
        print(f"== {section['title']} ==")
        lines = section["lines"]
        if lines:
            for line in lines:
                print(line)
        else:
            print("No data.")

    return 0 if report["failures"] == 0 else 1

def build_status_report(profile: Profile, *, dry_run: bool = False) -> dict[str, object]:
    failures = 0
    sections: list[dict[str, object]] = []

    if profile.status_url:
        try:
            status_text = _fetch_status_page(profile.status_url)
        except ConfigError as error:
            sections.append(
                {
                    "title": "status page",
                    "ok": False,
                    "source": profile.status_url,
                    "lines": [f"status page unavailable: {error}"],
                }
            )
            failures += 1
        else:
            sections.append(
                {
                    "title": "status page",
                    "ok": True,
                    "source": profile.status_url,
                    "lines": status_text.splitlines(),
                }
            )
    else:
        sections.append(
            {
                "title": "status page",
                "ok": False,
                "source": None,
                "lines": [f"profile '{profile.name}' does not define status_url"],
            }
        )
        failures += 1

    if profile.quota_command:
        quota_result = run_command_capture(profile, profile.quota_command, dry_run=dry_run)
        if quota_result.returncode != 0:
            failures += 1
            sections.append(
                {
                    "title": "quota",
                    "ok": False,
                    "command": profile.quota_command,
                    "returncode": quota_result.returncode,
                    "stderr": quota_result.stderr,
                    "lines": [f"quota check failed with return code {quota_result.returncode}"],
                }
            )
        else:
            quota_text = quota_result.stdout.strip()
            sections.append(
                {
                    "title": "quota",
                    "ok": True,
                    "command": profile.quota_command,
                    "returncode": quota_result.returncode,
                    "stderr": quota_result.stderr,
                    "lines": quota_text.splitlines() if quota_text else [],
                }
            )
    else:
        sections.append(
            {
                "title": "quota",
                "ok": False,
                "command": None,
                "lines": [f"profile '{profile.name}' does not define quota_command"],
            }
        )
        failures += 1

    if profile.sam_balance_command:
        balance_result = run_command_capture(profile, profile.sam_balance_command, dry_run=dry_run)
        if balance_result.returncode != 0:
            failures += 1
            sections.append(
                {
                    "title": "balance",
                    "ok": False,
                    "command": profile.sam_balance_command,
                    "returncode": balance_result.returncode,
                    "stderr": balance_result.stderr,
                    "lines": [f"balance check failed with return code {balance_result.returncode}"],
                }
            )
        else:
            balance_text = balance_result.stdout.strip()
            sections.append(
                {
                    "title": "balance",
                    "ok": True,
                    "command": profile.sam_balance_command,
                    "returncode": balance_result.returncode,
                    "stderr": balance_result.stderr,
                    "lines": balance_text.splitlines() if balance_text else [],
                }
            )
    else:
        sections.append(
            {
                "title": "balance",
                "ok": False,
                "command": None,
                "lines": [f"profile '{profile.name}' does not define sam_balance_command"],
            }
        )
        failures += 1

    records = submissions.active_records(submissions.read_events())
    sections.append(
        {
            "title": "submissions",
            "ok": True,
            "lines": submissions.format_records(records).splitlines(),
        }
    )

    return {
        "profile": profile.name,
        "dry_run": dry_run,
        "failures": failures,
        "ok": failures == 0,
        "sections": sections,
        "submissions": [asdict(record) for record in records],
    }

def cmd_jobs(args: argparse.Namespace, profile: Profile) -> int:
    return run_command(profile, slurm.squeue_user_command(args.cluster), dry_run=args.dry_run)

def cmd_job(args: argparse.Namespace, profile: Profile) -> int:
    return run_command(profile, slurm.squeue_job_command(args.jobid, args.cluster), dry_run=args.dry_run)

def cmd_submit(args: argparse.Namespace, profile: Profile) -> int:
    overrides = _submit_overrides(args)
    command = slurm.submit_command(
        args.jobscript,
        directory=args.directory,
        test_only=args.test_only,
        overrides=overrides,
    )
    validation_command = slurm.submit_command(
        args.jobscript,
        directory=args.directory,
        test_only=True,
        overrides=overrides,
    )
    if args.dry_run:
        if args.validate_first and not args.test_only:
            run_command(profile, validation_command, dry_run=True)
        return run_command(profile, command, dry_run=True)
    if args.test_only:
        return run_command(profile, command, dry_run=False)

    if args.validate_first:
        validation = run_command_capture(profile, validation_command)
        if validation.stdout:
            print(validation.stdout, end="")
        if validation.stderr:
            print(validation.stderr, end="", file=sys.stderr)
        if validation.returncode != 0:
            return validation.returncode

    completed = run_command_capture(profile, command)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode == 0:
        _log_submission(
            profile=profile,
            args=args,
            command=command,
            overrides=overrides,
            sbatch_output=completed.stdout + completed.stderr,
        )
    return completed.returncode

def _add_submit_override_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", "-A", help="Override sbatch --account")
    parser.add_argument("--array", help="Override sbatch --array")
    parser.add_argument("--cluster", "-M", help="Override sbatch --clusters")
    parser.add_argument("--dependency", help="Add sbatch --dependency")
    parser.add_argument("--error", help="Override sbatch --error")
    parser.add_argument("--export", dest="export", help="Override sbatch --export")
    parser.add_argument("--job-name", help="Override sbatch --job-name")
    parser.add_argument("--output", help="Override sbatch --output")
    parser.add_argument("--partition", "-p", help="Override sbatch --partition")
    parser.add_argument("--reservation", help="Override sbatch --reservation")
    parser.add_argument("--time", "-t", help="Override sbatch --time")

    parser.add_argument("--nodes", "-N", help="Override sbatch --nodes")
    parser.add_argument("--ntasks", "-n", help="Override sbatch --ntasks")
    parser.add_argument("--ntasks-per-node", help="Override sbatch --ntasks-per-node")
    parser.add_argument("--cpus-per-task", "-c", help="Override sbatch --cpus-per-task")
    parser.add_argument("--mem", help="Override sbatch --mem")
    parser.add_argument("--mem-per-cpu", help="Override sbatch --mem-per-cpu")

    parser.add_argument("--gres", help="Override sbatch --gres")
    parser.add_argument("--gpus", help="Override sbatch --gpus")
    parser.add_argument("--gpus-per-node", help="Override sbatch --gpus-per-node")
    parser.add_argument("--gpus-per-task", help="Override sbatch --gpus-per-task")
    parser.add_argument("--gpu-bind", help="Override sbatch --gpu-bind")

def _submit_overrides(args: argparse.Namespace) -> dict[str, str | None]:
    return slurm_contracts.namespace_submit_overrides(args)

def _log_submission(
    *,
    profile: Profile,
    args: argparse.Namespace,
    command: str,
    overrides: dict[str, str | None],
    sbatch_output: str,
) -> None:
    try:
        job_id, cluster = submissions.parse_sbatch_submission(sbatch_output)
    except ValueError as error:
        print(f"hpc: warning: {error}; submission was not logged", file=sys.stderr)
        return
    event = submissions.submitted_event(
        profile=profile.name,
        job_id=job_id,
        cluster=cluster or args.cluster or profile.default_cluster,
        remote_directory=args.directory,
        jobscript=args.jobscript,
        submit_command=command,
        overrides=overrides,
    )
    submissions.append_event(event)

def cmd_sacct(args: argparse.Namespace, profile: Profile) -> int:
    cluster = args.cluster or profile.default_cluster
    return run_command(profile, slurm.sacct_command(args.jobid, cluster), dry_run=args.dry_run)

def cmd_slurm_limits(args: argparse.Namespace, profile: Profile) -> int:
    cluster = args.cluster or profile.default_cluster
    return run_command(
        profile,
        slurm.slurm_limits_command(
            cluster=cluster,
            partition=args.partition,
            qos=args.qos,
        ),
        dry_run=args.dry_run,
    )

def _fetch_status_page(url: str) -> str:
    try:
        with urlopen(url, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except (URLError, TimeoutError, OSError) as error:
        raise ConfigError(f"failed to fetch status page {url}: {error}") from error

    text = _html_to_text(body)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return f"{url} (no text content found)"
    return "\n".join(lines[:20])

def _html_to_text(document: str) -> str:
    document = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", document)
    document = re.sub(r"(?i)<br\s*/?>", "\n", document)
    document = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", document)
    document = re.sub(r"<[^>]+>", " ", document)
    document = html.unescape(document)
    document = re.sub(r"[ \t\r\f\v]+", " ", document)
    document = re.sub(r"\n+", "\n", document)
    return document.strip()

def _statement_command(
    base_command: str,
    *,
    account: str,
    start: str | None = None,
    end: str | None = None,
) -> str:
    parts = [base_command, "--account", shlex.quote(account)]
    if start:
        _validate_date(start, "start")
        parts.extend(["--start", shlex.quote(start)])
    if end:
        _validate_date(end, "end")
        parts.extend(["--end", shlex.quote(end)])
    return " ".join(parts)

def _quote_command(base_command: str, quote_args: list[str]) -> str:
    if not quote_args:
        raise ConfigError("quote requires a submit command: sbatch, srun, or salloc")

    submit_command = quote_args[0]
    if submit_command not in {"sbatch", "srun", "salloc"}:
        raise ConfigError("quote first argument must be one of: sbatch, srun, salloc")

    if not _quote_args_have_account(quote_args[1:]):
        raise ConfigError("quote requires a Slurm account option: -A <account> or --account <account>")

    return " ".join([base_command, *(shlex.quote(part) for part in quote_args)])

def _quote_args_have_account(args: list[str]) -> bool:
    for index, arg in enumerate(args):
        if arg in {"-A", "--account"}:
            return index + 1 < len(args) and bool(args[index + 1])
        if arg.startswith("--account=") and arg != "--account=":
            return True
        if arg.startswith("-A") and arg != "-A":
            return True
    return False

def _validate_date(value: str, name: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ConfigError(f"{name} date must use YYYY-mm-dd format: {value}") from error
