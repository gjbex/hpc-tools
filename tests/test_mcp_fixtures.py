from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from hpc_tools import mcp_server


class McpFixtures:
    def _write_config(self, root: Path) -> Path:
        profile_dir = root / "hpc-tools" / "profiles" / "genius"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "hardware.md").write_text("# hardware\n", encoding="utf-8")
        (profile_dir / "slurm.md").write_text("# slurm\n", encoding="utf-8")
        (profile_dir / "storage.md").write_text("# storage\n", encoding="utf-8")

        config_path = root / "hpc-tools" / "config.toml"
        config_path.write_text(
            textwrap.dedent(
                f"""
                default_profile = "genius"

                [profiles.genius]
                ssh_target = "genius"
                ssh_options = ["-x"]
                hardware_reference = "{profile_dir / 'hardware.md'}"
                hardware_url = "https://example.org/hardware"
                slurm_reference = "{profile_dir / 'slurm.md'}"
                slurm_url = "https://example.org/slurm"
                storage_reference = "{profile_dir / 'storage.md'}"
                storage_url = "https://example.org/storage"
                status_url = "https://status.example.org/"
                quota_command = "myquota"
                sam_balance_command = "sam-balance"
                sam_quote_command = "sam-quote"
                default_cluster = "wice"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config_path

    def _write_delegation_manifest(self, root: Path) -> Path:
        path = root / "delegation.toml"
        path.write_text(
            textwrap.dedent(
                """
                format_version = 1
                id = "delegate-1"
                issuer = "operator"
                profile = "genius"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"
                [allowed]
                accounts = ["proj"]
                clusters = ["wice"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = []
                script_sha256 = []
                roots = ["/work/delegate-1"]
                [budget]
                max_submissions = 2
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        return path

    def _write_reference_set(self, root: Path, name: str) -> Path:
        reference_dir = root / "hpc-tools" / "reference-sets" / name
        reference_dir.mkdir(parents=True, exist_ok=True)
        (reference_dir / "hardware.md").write_text("# hardware set\n", encoding="utf-8")
        (reference_dir / "slurm.md").write_text("# slurm set\n", encoding="utf-8")
        (reference_dir / "storage.md").write_text("# storage set\n", encoding="utf-8")
        (reference_dir / "manifest.toml").write_text(
            textwrap.dedent(
                """
                format_version = "1"
                created_at = "2026-06-17T12:00:00+02:00"
                source_profile = "genius"

                [files]
                hardware_reference = "hardware.md"
                slurm_reference = "slurm.md"
                storage_reference = "storage.md"

                [sources]
                hardware_url = "https://example.org/hardware"
                slurm_url = "https://example.org/slurm"
                storage_url = "https://example.org/storage"
                status_url = "https://status.example.org/"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return reference_dir


__all__ = [name for name in globals() if not name.startswith("__")]
