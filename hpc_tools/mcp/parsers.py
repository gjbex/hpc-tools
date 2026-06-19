from __future__ import annotations

import re
from typing import Any

def _parse_slurm_limits_output(stdout: str) -> tuple[dict[str, Any], list[str]]:
    sections = _split_hash_sections(stdout)
    warnings: list[str] = []
    expected = {
        "controller",
        "partitions",
        "partition-summary",
        "partition-nodes",
        "qos",
        "associations",
    }
    for section in sorted(expected - set(sections)):
        warnings.append(f"missing section: {section}")

    parsed = {
        "controller": _parse_key_value_lines(sections.get("controller", "")),
        "partitions": _parse_scontrol_partitions(sections.get("partitions", "")),
        "partition_summary": _parse_pipe_table(
            sections.get("partition-summary", ""),
            ["partition", "available", "time_limit", "nodes", "cpus", "memory", "gres", "features"],
        ),
        "partition_nodes": _parse_pipe_table(
            sections.get("partition-nodes", ""),
            ["node", "cpus", "memory", "gres", "state"],
        ),
        "qos": _parse_pipe_table(
            sections.get("qos", ""),
            [
                "name",
                "max_jobs_per_user",
                "max_submit_jobs_per_user",
                "max_tres_per_user",
                "group_jobs",
                "group_submit_jobs",
                "group_tres",
                "max_wall",
            ],
        ),
        "associations": _parse_pipe_table(
            sections.get("associations", ""),
            [
                "cluster",
                "account",
                "user",
                "partition",
                "qos",
                "default_qos",
                "max_jobs",
                "max_submit_jobs",
                "max_tres",
                "group_jobs",
                "group_submit_jobs",
                "group_tres",
            ],
        ),
    }
    return parsed, warnings

def _parse_module_spider_output(stdout: str) -> tuple[dict[str, Any], list[str]]:
    modules = sorted(
        module
        for module in set(re.findall(r"\b[A-Za-z][A-Za-z0-9_.+-]*/[A-Za-z0-9][A-Za-z0-9_.:+-]*", stdout))
        if not module.startswith("cluster/")
    )
    contexts = sorted(
        set(
            line.strip()
            for line in stdout.splitlines()
            if line.strip().startswith("cluster/")
        )
    )
    warnings = [] if modules else ["no module names parsed"]
    return {
        "modules": modules,
        "availability_contexts": contexts,
    }, warnings

def _split_hash_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in stdout.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}

def _parse_key_value_lines(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("CLUSTER:"):
            continue
        match = re.match(r"^\s*([^=]+?)\s*=\s*(.*?)\s*$", line)
        if match:
            parsed[match.group(1).strip()] = match.group(2).strip()
    return parsed

def _parse_scontrol_partitions(text: str) -> list[dict[str, Any]]:
    partitions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("CLUSTER:"):
            continue
        if stripped.startswith("PartitionName="):
            if current is not None:
                partitions.append(_normalize_partition(current))
            current = {}
        if current is None:
            continue
        current.update(_parse_inline_key_values(stripped))
    if current is not None:
        partitions.append(_normalize_partition(current))
    return partitions

def _parse_inline_key_values(line: str) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in re.finditer(r"(?P<key>[A-Za-z][A-Za-z0-9]*)=(?P<value>\S+)", line)
    }

def _normalize_partition(partition: dict[str, str]) -> dict[str, Any]:
    normalized = dict(partition)
    for key in ("TotalCPUs", "TotalNodes"):
        if key in normalized:
            normalized[key] = _parse_int_or_original(str(normalized[key]))
    normalized["has_gres"] = bool(normalized.get("TRES") and "gres/" in str(normalized["TRES"]))
    normalized["has_gpu"] = "gres/gpu" in str(normalized.get("TRES", ""))
    return normalized

def _parse_int_or_original(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value

def _parse_pipe_table(text: str, fields: list[str]) -> list[dict[str, str | int | None]]:
    rows: list[dict[str, str | int | None]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("CLUSTER:")
            or stripped.startswith("PARTITION|")
            or stripped.startswith("NODELIST|")
        ):
            continue
        values = stripped.split("|")
        if len(values) != len(fields):
            continue
        row: dict[str, str | int | None] = {}
        for field, value in zip(fields, values):
            row[field] = _normalize_table_value(value)
        rows.append(row)
    return rows

def _normalize_table_value(value: str) -> str | int | None:
    value = value.strip()
    if value in {"", "(null)"}:
        return None
    try:
        return int(value)
    except ValueError:
        return value

