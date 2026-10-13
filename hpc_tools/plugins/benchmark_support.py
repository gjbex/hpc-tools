from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
from typing import Any

from hpc_tools.config import ConfigError, Profile


MEASUREMENT_KEYS = ("seconds", "time", "duration", "runtime", "elapsed", "walltime")
MEASUREMENT_NAME_HINTS = (
    "time",
    "runtime",
    "duration",
    "elapsed",
    "wallclock",
    "wall",
    "latency",
    "seconds",
    "second",
    "sec",
    "ms",
    "min",
    "hour",
)
DIMENSION_NAME_HINTS = (
    "thread",
    "worker",
    "rank",
    "replica",
    "run",
    "trial",
    "iteration",
    "iter",
    "sample",
    "size",
    "problem",
    "node",
    "core",
    "count",
    "batch",
    "step",
    "epoch",
    "process",
    "proc",
)


@dataclass(frozen=True)
class BenchmarkSummary:
    target: str
    source_files: list[str]
    measurement_key: str
    count: int
    mean: float
    minimum: float
    maximum: float
    stdev: float


@dataclass(frozen=True)
class BenchmarkComparison:
    baseline: BenchmarkSummary
    candidate: BenchmarkSummary
    speedup: float
    efficiency: float | None
    candidate_threads: int | None


class BenchmarkSupportPlugin:
    name = "benchmark"
    description = "Benchmark result summarization and comparison helpers."

    def register(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        profile: Profile | None,
    ) -> None:
        del profile
        parser = subparsers.add_parser(
            "benchmark",
            help="Benchmark result summarization and comparison helpers",
        )
        benchmark_subparsers = parser.add_subparsers(
            dest="benchmark_command",
            metavar="<subcommand>",
            required=True,
        )

        summarize_parser = benchmark_subparsers.add_parser(
            "summarize",
            help="Summarize numeric timing data from CSV, JSON, or JSONL benchmark artifacts",
        )
        summarize_parser.add_argument(
            "targets",
            nargs="+",
            type=Path,
            help="Benchmark file or directory to summarize",
        )
        summarize_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        summarize_parser.set_defaults(
            handler=cmd_benchmark_summarize,
            operation_id="benchmark.summarize",
        )

        compare_parser = benchmark_subparsers.add_parser(
            "compare",
            help="Compare a baseline benchmark against a candidate benchmark",
        )
        compare_parser.add_argument("baseline", type=Path, help="Baseline benchmark file or directory")
        compare_parser.add_argument("candidate", type=Path, help="Candidate benchmark file or directory")
        compare_parser.add_argument(
            "--candidate-threads",
            type=_positive_int,
            help="Active thread count for the candidate run; used for efficiency",
        )
        compare_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        compare_parser.set_defaults(
            handler=cmd_benchmark_compare,
            operation_id="benchmark.compare",
        )

    def requires_profile(self, argv: list[str]) -> bool:
        del argv
        return False


def get_plugin() -> BenchmarkSupportPlugin:
    return BenchmarkSupportPlugin()


def cmd_benchmark_summarize(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    summaries = []
    for target in args.targets:
        summaries.extend(_summaries_for_target(target))
    if args.json:
        print(
            json.dumps(
                {"summaries": [summary_to_dict(summary) for summary in summaries]},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(format_summaries(summaries))
    return 0


def cmd_benchmark_compare(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    baseline = summarize_target(args.baseline)
    candidate = summarize_target(args.candidate)
    speedup = baseline.mean / candidate.mean if candidate.mean else float("inf")
    efficiency = speedup / args.candidate_threads if args.candidate_threads else None
    comparison = BenchmarkComparison(
        baseline=baseline,
        candidate=candidate,
        speedup=speedup,
        efficiency=efficiency,
        candidate_threads=args.candidate_threads,
    )
    if args.json:
        print(json.dumps(comparison_to_dict(comparison), indent=2, sort_keys=True))
        return 0
    print(format_comparison(comparison))
    return 0


def _summaries_for_target(target: Path) -> list[BenchmarkSummary]:
    if target.is_dir():
        source_files = _collect_source_files(target)
        return [summarize_target(source_file) for source_file in source_files]
    return [summarize_target(target)]


def summarize_target(target: Path) -> BenchmarkSummary:
    try:
        source_files = _collect_source_files(target)
        records: list[dict[str, Any]] = []
        for source_file in source_files:
            records.extend(_read_records(source_file))
        measurement_key = _discover_measurement_key(records)
        measurements = _collect_measurements(records, measurement_key)
        if not measurements:
            raise ConfigError(f"no numeric benchmark measurements found in {target}")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        raise ConfigError(str(error)) from error
    stdev = statistics.stdev(measurements) if len(measurements) > 1 else 0.0
    return BenchmarkSummary(
        target=str(target),
        source_files=[str(path) for path in source_files],
        measurement_key=measurement_key,
        count=len(measurements),
        mean=statistics.mean(measurements),
        minimum=min(measurements),
        maximum=max(measurements),
        stdev=stdev,
    )


def format_summaries(summaries: list[BenchmarkSummary]) -> str:
    if not summaries:
        return "No benchmark data."
    lines = [
        "TARGET  MEASURE  COUNT  MEAN  MIN  MAX  STDEV  SOURCES",
        "------  -------  -----  ----  ---  ---  -----  -------",
    ]
    for summary in summaries:
        lines.append(
            "  ".join(
                [
                    summary.target,
                    summary.measurement_key,
                    str(summary.count),
                    _fmt(summary.mean),
                    _fmt(summary.minimum),
                    _fmt(summary.maximum),
                    _fmt(summary.stdev),
                    str(len(summary.source_files)),
                ]
            )
        )
    return "\n".join(lines)


def format_comparison(comparison: BenchmarkComparison) -> str:
    lines = [
        "== baseline ==",
        f"target: {comparison.baseline.target}",
        f"measure: {comparison.baseline.measurement_key}",
        f"mean: {_fmt(comparison.baseline.mean)}",
        "",
        "== candidate ==",
        f"target: {comparison.candidate.target}",
        f"measure: {comparison.candidate.measurement_key}",
        f"mean: {_fmt(comparison.candidate.mean)}",
        "",
        "== comparison ==",
        f"speedup: {_fmt(comparison.speedup)}",
    ]
    if comparison.efficiency is not None:
        lines.append(f"efficiency: {_fmt(comparison.efficiency)}")
        lines.append(f"candidate_threads: {comparison.candidate_threads}")
    return "\n".join(lines)


def summary_to_dict(summary: BenchmarkSummary) -> dict[str, Any]:
    return {
        "target": summary.target,
        "source_files": summary.source_files,
        "measurement_key": summary.measurement_key,
        "count": summary.count,
        "mean": summary.mean,
        "minimum": summary.minimum,
        "maximum": summary.maximum,
        "stdev": summary.stdev,
    }


def comparison_to_dict(comparison: BenchmarkComparison) -> dict[str, Any]:
    return {
        "baseline": summary_to_dict(comparison.baseline),
        "candidate": summary_to_dict(comparison.candidate),
        "speedup": comparison.speedup,
        "efficiency": comparison.efficiency,
        "candidate_threads": comparison.candidate_threads,
    }


def _collect_source_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.exists():
        raise FileNotFoundError(target)
    files = [
        path
        for path in sorted(target.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".jsonl"}
    ]
    if not files:
        raise ValueError(f"no benchmark data files found under {target}")
    return files


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid positive integer value: {value}") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"candidate_threads must be a positive integer: {value}")
    return parsed


def _read_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                records.append(payload)
        return records
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ("runs", "results", "records", "samples"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
            return [payload]
    raise ValueError(f"unsupported benchmark data file: {path}")


def _discover_measurement_key(records: list[dict[str, Any]]) -> str:
    if not records:
        raise ValueError("empty benchmark data")
    keys = list(records[0])
    for preferred in MEASUREMENT_KEYS:
        for key in keys:
            if key.lower() == preferred:
                return key
    scored_candidates: list[tuple[int, str]] = []
    for key in keys:
        lower = key.lower()
        numeric_values = [value for value in (_parse_float(record.get(key)) for record in records) if value is not None]
        if not numeric_values:
            continue
        score = len(numeric_values)
        if any(hint in lower for hint in MEASUREMENT_NAME_HINTS):
            score += 20
        if any(hint in lower for hint in DIMENSION_NAME_HINTS):
            score -= 15
        if lower in {"label", "name", "config", "variant"}:
            score -= 20
        scored_candidates.append((score, key))

    if not scored_candidates:
        raise ValueError("could not determine the benchmark measurement column")

    scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score = scored_candidates[0][0]
    best_candidates = [key for score, key in scored_candidates if score == best_score]
    if len(best_candidates) > 1:
        raise ValueError(
            "could not determine the benchmark measurement column; "
            f"candidates were {', '.join(best_candidates)}"
        )
    if best_score <= 0:
        raise ValueError("could not determine the benchmark measurement column")
    return best_candidates[0]


def _collect_measurements(records: list[dict[str, Any]], measurement_key: str) -> list[float]:
    measurements = []
    for record in records:
        value = _parse_float(record.get(measurement_key))
        if value is not None:
            measurements.append(value)
    return measurements


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _fmt(value: float) -> str:
    return f"{value:.6g}"
