from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import textwrap
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timezone
from pathlib import Path
from unittest import mock

from hpc_tools import delegation
from hpc_tools.capabilities import (
    POLICY_VERSION,
    CapabilityLevel,
    CapabilityPolicy,
    RemoteRootGrants,
)
from hpc_tools.credit_quotes import STRUCTURED_QUOTE_FORMAT_V1, CreditAmount


class DelegationTests(unittest.TestCase):
    @staticmethod
    def _capability_policy(
        level: CapabilityLevel,
        *,
        scopes: tuple[str, ...] = (),
    ) -> CapabilityPolicy:
        return CapabilityPolicy(
            version=POLICY_VERSION,
            max_level=level,
            scopes=scopes,
            remote_roots=RemoteRootGrants(),
        )

    def _manifest(self, root: Path, **changes: str) -> Path:
        values = {
            "id": "delegate-1",
            "profile": "genius",
            "parent_job_id": "9001",
            "expires_at": "2099-01-01T00:00:00Z",
        } | changes
        path = root / "delegation.toml"
        path.write_text(
            textwrap.dedent(
                f"""
                format_version = 4
                id = "{values['id']}"
                issuer = "operator@example.org"
                profile = "{values['profile']}"
                parent_job_id = "{values['parent_job_id']}"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "{values['expires_at']}"

                [network]
                mode = "model-only"

                [allowed]
                accounts = ["proj"]
                clusters = ["wice"]
                partitions = ["batch"]
                qos = ["normal"]
                reservations = []
                containers = ["/images/worker.sif"]
                script_sha256 = []
                roots = ["/work/delegate-1"]

                [per_job_limits]
                nodes = 2
                tasks = 8
                wall_seconds = 3600
                array_tasks = 10

                [budget]
                max_submissions = 2
                max_active_jobs = 1
                max_total_nodes = 3
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        return path

    def _manifest_template(
        self,
        root: Path,
        *,
        lifetime_seconds: int = 3600,
    ) -> Path:
        path = root / "delegation-template.toml"
        path.write_text(
            textwrap.dedent(
                f"""
                template_version = 1
                id_prefix = "delegate"
                issuer = "operator@example.org"
                profile = "genius"
                lifetime_seconds = {lifetime_seconds}

                [network]
                mode = "model-only"

                [allowed]
                accounts = ["proj"]
                clusters = ["wice"]
                partitions = ["batch"]
                qos = ["normal"]
                reservations = []
                containers = ["/images/worker.sif"]
                script_sha256 = []
                roots = ["/work/delegate"]

                [per_job_limits]
                nodes = 2
                tasks = 8
                wall_seconds = 3600

                [budget]
                max_submissions = 2
                max_active_jobs = 1
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def _shape(self, **overrides: str) -> dict[str, object]:
        values = {
            "account": "proj",
            "cluster": "wice",
            "partition": "batch",
            "qos": "normal",
            "nodes": "1",
            "ntasks": "4",
            "time": "00:30:00",
        } | overrides
        return {
            "profile": "genius",
            "jobscript": "job.slurm",
            "directory": "/work/delegate-1/run",
            "overrides": values,
            "shape_token": "test-token",
        }

    @staticmethod
    def _add_credit_budget(path: Path, table: str | None = None) -> None:
        content = table or """
            [credit_budget]
            unit = "credits"
            scale = 0
            maximum_total = 20000
            maximum_per_job = 5000
            quote_ttl_seconds = 300
        """
        path.write_text(
            path.read_text(encoding="utf-8")
            + textwrap.dedent(content).strip()
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _quoted_credit(
        value: int,
        *,
        token: str = "a" * 64,
        expires_at: datetime | None = None,
    ) -> delegation.QuotedCreditReservation:
        return delegation.QuotedCreditReservation(
            cost=CreditAmount(value=value, scale=0, unit="credits"),
            evidence_token=token,
            expires_at=expires_at
            or datetime(2098, 1, 1, tzinfo=UTC),
        )

    def test_manifest_binds_profile_parent_expiry_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            manifest = delegation.load_manifest(
                path,
                expected_profile="genius",
                expected_parent_job_id="9001",
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            self.assertEqual("delegate-1", manifest.identifier)
            self.assertEqual(
                delegation.AgentNetworkMode.MODEL_ONLY,
                manifest.network.mode,
            )
            with self.assertRaisesRegex(delegation.DelegationError, "profile"):
                delegation.load_manifest(path, expected_profile="other")
            with self.assertRaisesRegex(delegation.DelegationError, "parent"):
                delegation.load_manifest(
                    path, expected_profile="genius", expected_parent_job_id="9002"
                )
            path.chmod(0o666)
            with self.assertRaisesRegex(delegation.DelegationError, "writable"):
                delegation.load_manifest(path, expected_profile="genius")

    def test_manifest_template_materialization_is_deterministic_and_job_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = self._manifest_template(root)
            output = root / "materialized.toml"
            now = datetime(2026, 10, 27, 12, 34, 56, 999999, tzinfo=UTC)

            first, evidence, first_payload = delegation.prepare_manifest_template(
                template,
                output,
                expected_profile="genius",
                parent_job_id="9001",
                now=now,
            )
            second, _, second_payload = delegation.prepare_manifest_template(
                template,
                output,
                expected_profile="genius",
                parent_job_id="9001",
                now=now,
            )

            self.assertEqual(first_payload, second_payload)
            self.assertEqual("delegate-9001", first.identifier)
            self.assertEqual("2026-10-27T12:34:56+00:00", first.issued_at)
            self.assertEqual("2026-10-27T13:34:56+00:00", first.expires_at)
            self.assertEqual(first.digest, second.digest)
            self.assertEqual(first.digest, evidence.manifest_sha256)
            self.assertEqual(
                hashlib.sha256(template.read_bytes()).hexdigest(),
                evidence.template_sha256,
            )
            self.assertFalse(output.exists())

    def test_manifest_template_publishes_privately_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = self._manifest_template(root)
            output = root / "materialized.toml"
            manifest, evidence = delegation.materialize_manifest_template(
                template,
                output,
                expected_profile="genius",
                parent_job_id="9001",
                now=datetime(2026, 10, 27, tzinfo=UTC),
            )

            self.assertEqual(output, manifest.source_path)
            self.assertEqual(0o600, output.stat().st_mode & 0o777)
            self.assertEqual(
                hashlib.sha256(output.read_bytes()).hexdigest(),
                evidence.manifest_sha256,
            )
            with self.assertRaisesRegex(delegation.DelegationError, "already exists"):
                delegation.materialize_manifest_template(
                    template,
                    output,
                    expected_profile="genius",
                    parent_job_id="9001",
                )

            symlink = root / "symlink.toml"
            symlink.symlink_to(output)
            with self.assertRaisesRegex(delegation.DelegationError, "symlink|exists"):
                delegation.materialize_manifest_template(
                    template,
                    symlink,
                    expected_profile="genius",
                    parent_job_id="9001",
                )

    def test_manifest_template_requeue_verification_prevents_authority_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = self._manifest_template(root, lifetime_seconds=3600)
            output = root / "materialized.toml"
            delegation.materialize_manifest_template(
                template,
                output,
                expected_profile="genius",
                parent_job_id="9001",
                now=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
            )

            verified, evidence = delegation.verify_materialized_manifest(
                template,
                output,
                expected_profile="genius",
                parent_job_id="9001",
                now=datetime(2026, 10, 27, 12, 30, tzinfo=UTC),
            )
            self.assertEqual("delegate-9001", verified.identifier)
            self.assertEqual(verified.digest, evidence.manifest_sha256)

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "max_submissions = 2", "max_submissions = 3"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "does not match"):
                delegation.verify_materialized_manifest(
                    template,
                    output,
                    expected_profile="genius",
                    parent_job_id="9001",
                )

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "max_submissions = 3", "max_submissions = 2"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "expired"):
                delegation.verify_materialized_manifest(
                    template,
                    output,
                    expected_profile="genius",
                    parent_job_id="9001",
                    now=datetime(2026, 10, 27, 13, 0, 1, tzinfo=UTC),
                )

    def test_manifest_template_rejects_dynamic_unknown_and_unbounded_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = self._manifest_template(root)
            for addition, pattern in (
                ('parent_job_id = "9001"\n', "unsupported"),
                ("unexpected = true\n", "unsupported"),
            ):
                with self.subTest(addition=addition):
                    template.write_text(
                        addition + template.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(delegation.DelegationError, pattern):
                        delegation.load_manifest_template(template)
                    template = self._manifest_template(root)

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "lifetime_seconds = 3600", "lifetime_seconds = 0"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "lifetime_seconds"):
                delegation.load_manifest_template(template)

    def test_manifest_v4_parses_optional_fixed_point_credit_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            without_credit = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            self.assertIsNone(without_credit.credit_budget)
            self.assertEqual(
                {"configured": False},
                without_credit.public_summary()["credit_budget"],
            )

            path = self._manifest(root)
            self._add_credit_budget(path)
            manifest = delegation.load_manifest(path, expected_profile="genius")

        self.assertEqual(
            {
                "unit": "credits",
                "scale": 0,
                "maximum_total": 20000,
                "maximum_per_job": 5000,
                "quote_ttl_seconds": 300,
            },
            manifest.credit_budget.public_summary(),
        )

    def test_credit_budget_inclusive_numeric_boundaries_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._manifest(Path(directory))
            self._add_credit_budget(
                path,
                """
                [credit_budget]
                unit = "credit.minor"
                scale = 9
                maximum_total = 9223372036854775807
                maximum_per_job = 9223372036854775807
                quote_ttl_seconds = 86400
                """,
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")

        self.assertEqual(9, manifest.credit_budget.scale)
        self.assertEqual(2**63 - 1, manifest.credit_budget.maximum_total)
        self.assertEqual(86400, manifest.credit_budget.quote_ttl_seconds)

    def test_credit_budget_rejects_invalid_or_inconsistent_policy(self) -> None:
        cases = {
            "missing field": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 20000
                """,
                "missing field.*quote_ttl_seconds",
            ),
            "unknown field": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 20000
                quote_ttl_seconds = 300
                reset_seconds = 60
                """,
                "unsupported credit_budget.*reset_seconds",
            ),
            "boolean total": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = true
                quote_ttl_seconds = 300
                """,
                "maximum_total must be an integer",
            ),
            "invalid unit": (
                """
                [credit_budget]
                unit = "Credits"
                scale = 0
                maximum_total = 20000
                quote_ttl_seconds = 300
                """,
                "normalized lowercase ASCII",
            ),
            "scale overflow": (
                """
                [credit_budget]
                unit = "credits"
                scale = 10
                maximum_total = 20000
                quote_ttl_seconds = 300
                """,
                "credit_budget.scale",
            ),
            "zero total": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 0
                quote_ttl_seconds = 300
                """,
                "credit_budget.maximum_total",
            ),
            "total overflow": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 9223372036854775808
                quote_ttl_seconds = 300
                """,
                "credit_budget.maximum_total",
            ),
            "per job exceeds total": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 100
                maximum_per_job = 101
                quote_ttl_seconds = 300
                """,
                "maximum_per_job must not exceed maximum_total",
            ),
            "ttl overflow": (
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 20000
                quote_ttl_seconds = 86401
                """,
                "credit_budget.quote_ttl_seconds",
            ),
        }
        for name, (table, message) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self._manifest(Path(directory))
                self._add_credit_budget(path, table)
                with self.assertRaisesRegex(delegation.DelegationError, message):
                    delegation.load_manifest(path, expected_profile="genius")

    def test_manifest_v3_is_rejected_without_implicit_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._manifest(Path(directory))
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "format_version = 4", "format_version = 3"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                delegation.DelegationError, "version 3.*expected 4"
            ):
                delegation.load_manifest(path, expected_profile="genius")

    def test_manifest_maps_each_explicit_network_mode(self) -> None:
        expected = {
            "model-only": "disabled",
            "model-indexed-search": "indexed",
            "model-live-search": "live",
        }
        for selected, web_search in expected.items():
            with (
                self.subTest(mode=selected),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = self._manifest(Path(directory))
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        'mode = "model-only"', f'mode = "{selected}"'
                    ),
                    encoding="utf-8",
                )
                manifest = delegation.load_manifest(
                    path, expected_profile="genius"
                )

                self.assertEqual(selected, manifest.network.mode.value)
                self.assertEqual(
                    {
                        "mode": selected,
                        "web_search": web_search,
                        "command_network_access": False,
                    },
                    manifest.public_summary()["network"],
                )

    def test_manifest_network_policy_fails_closed(self) -> None:
        cases = {
            "absent": (
                '[network]\nmode = "model-only"\n\n',
                "",
                "network must be a table",
            ),
            "unknown mode": (
                'mode = "model-only"',
                'mode = "unrestricted"',
                "network.mode must be one of",
            ),
            "wrong type": ('mode = "model-only"', "mode = true", "network.mode"),
            "unknown key": (
                'mode = "model-only"',
                'mode = "model-only"\nproxy_url = "secret"',
                "unsupported network field",
            ),
            "duplicate mode": (
                'mode = "model-only"',
                'mode = "model-only"\nmode = "model-only"',
                "invalid delegation manifest",
            ),
        }
        for name, (source, replacement, message) in cases.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = self._manifest(Path(directory))
                content = path.read_text(encoding="utf-8")
                content = content.replace(source, replacement)
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(delegation.DelegationError, message):
                    delegation.load_manifest(path, expected_profile="genius")

    def test_credit_controller_startup_requires_and_captures_quote_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = self._manifest(root)
            self._add_credit_budget(manifest_path)
            config_path = root / "config.toml"
            config_path.write_text("# credit fixture\n", encoding="utf-8")
            ledger_path = root / "ledger.sqlite3"
            arguments = {
                "manifest_path": manifest_path,
                "profile": "genius",
                "ledger_path": ledger_path,
                "parent_job_id": "9001",
                "profile_policy": self._capability_policy(
                    CapabilityLevel.JOB_LIFECYCLE
                ),
                "config_path": config_path,
                "config_sha256": "a" * 64,
            }

            with self.assertRaisesRegex(
                delegation.DelegationError, "requires profile sam_quote_command"
            ):
                delegation.load_runtime(**arguments)
            self.assertFalse(ledger_path.exists())

            arguments["sam_quote_command"] = "site-quote"
            with self.assertRaisesRegex(
                delegation.DelegationError, "requires profile sam_quote_format"
            ):
                delegation.load_runtime(**arguments)
            self.assertFalse(ledger_path.exists())

            arguments["sam_quote_format"] = STRUCTURED_QUOTE_FORMAT_V1
            runtime = delegation.load_runtime(**arguments)

        self.assertEqual(
            runtime.manifest.credit_budget,
            runtime.controller_authority.credit_budget,
        )
        self.assertEqual(
            STRUCTURED_QUOTE_FORMAT_V1,
            runtime.controller_authority.quote_format,
        )
        self.assertEqual("a" * 64, runtime.controller_authority.config_sha256)
        authority_summary = runtime.controller_authority.public_summary()
        self.assertNotIn("config_path", authority_summary)
        self.assertNotIn("sam_quote_command", authority_summary)
        self.assertEqual(
            20000,
            authority_summary["credit_budget"]["maximum_total"],
        )

    def test_controller_start_requires_job_lifecycle_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text("# fixture\n", encoding="utf-8")
            ledger_path = root / "ledger.sqlite3"

            with self.assertRaisesRegex(
                delegation.DelegationError,
                "agent.controller.start.*job-lifecycle",
            ):
                delegation.load_runtime(
                    self._manifest(root),
                    profile="genius",
                    ledger_path=ledger_path,
                    parent_job_id="9001",
                    profile_policy=self._capability_policy(
                        CapabilityLevel.JOB_INSPECTION
                    ),
                    config_path=config_path,
                    config_sha256="0" * 64,
                )

            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            self.assertIsNone(
                delegation.DelegationLedger(ledger_path).controller_authority_or_none(
                    manifest
                )
            )

    def test_controller_authority_is_captured_once_and_survives_narrowing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text("# initial\n", encoding="utf-8")
            ledger_path = root / "ledger.sqlite3"
            initial = self._capability_policy(
                CapabilityLevel.JOB_LIFECYCLE,
                scopes=("job.validate",),
            )
            runtime = delegation.load_runtime(
                self._manifest(root),
                profile="genius",
                ledger_path=ledger_path,
                parent_job_id="9001",
                profile_policy=initial,
                config_path=config_path,
                config_sha256="1" * 64,
            )

            widened = self._capability_policy(
                CapabilityLevel.JOB_LIFECYCLE,
                scopes=("accounting.read", "job.validate"),
            )
            captured_again = delegation.DelegationLedger(
                ledger_path
            ).capture_controller_authority(
                runtime.manifest,
                policy=widened,
                config_path=root / "replacement.toml",
                config_sha256="2" * 64,
            )
            restarted = delegation.load_runtime(
                runtime.manifest.source_path,
                profile="genius",
                ledger_path=ledger_path,
                parent_job_id="9001",
                profile_policy=self._capability_policy(
                    CapabilityLevel.JOB_INSPECTION
                ),
                config_path=root / "narrowed.toml",
                config_sha256="3" * 64,
            )

            self.assertEqual(("job.validate",), captured_again.policy.scopes)
            self.assertEqual(
                runtime.controller_authority,
                restarted.controller_authority,
            )
            self.assertEqual(str(config_path), captured_again.config_path)

    def test_lifecycle_policy_has_strict_defaults_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            manifest = delegation.load_manifest(path, expected_profile="genius")
            self.assertEqual(
                {
                    "on_cancel": "cancel",
                    "on_timeout": "requeue-or-cancel",
                    "on_failure": "cancel",
                    "on_normal_exit_with_active_jobs": "cancel",
                    "max_requeues": 3,
                    "warning_seconds": 600,
                },
                manifest.lifecycle.public_summary(),
            )

            path.write_text(
                path.read_text(encoding="utf-8")
                + '\n[lifecycle]\non_cancel = "leave-running"\nmax_requeues = 0\n',
                encoding="utf-8",
            )
            explicit = delegation.load_manifest(path, expected_profile="genius")
            self.assertEqual("leave-running", explicit.lifecycle.on_cancel)
            self.assertEqual(0, explicit.lifecycle.max_requeues)

            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'on_cancel = "leave-running"', 'on_cancel = "ignore"'
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "on_cancel"):
                delegation.load_manifest(path, expected_profile="genius")

    def test_controller_requeue_blocks_submission_until_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            self.assertEqual(1, ledger.controller_summary(manifest)["generation"])

            ledger.begin_draining(manifest, reason="SIGUSR1")
            self.assertEqual(0, ledger.inflight_submission_count(manifest))
            with self.assertRaisesRegex(delegation.DelegationError, "draining"):
                ledger.reserve_submission(
                    manifest, idempotency_key="blocked-1", shape=self._shape()
                )
            ledger.request_requeue(manifest)
            ledger.record_requeue_result(manifest, accepted=True, detail="accepted")
            restarted = ledger.begin_controller(manifest, restart_count=1)
            self.assertEqual("reconciling", restarted["state"])
            self.assertEqual(2, restarted["generation"])
            with self.assertRaisesRegex(delegation.DelegationError, "reconciling"):
                ledger.reserve_submission(
                    manifest, idempotency_key="blocked-2", shape=self._shape()
                )
            ledger.complete_reconciliation(manifest)
            accepted = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertEqual("reserved", accepted["status"])

    def test_drain_exposes_submission_reserved_before_it_started(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            ledger.begin_draining(manifest, reason="SIGUSR1")
            self.assertEqual(1, ledger.inflight_submission_count(manifest))
            ledger.release_reservation(
                manifest, idempotency_key="request-1", reason="submission stopped"
            )
            self.assertEqual(0, ledger.inflight_submission_count(manifest))

    def test_concurrent_drain_and_submission_have_one_serialized_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            barrier = threading.Barrier(2)

            def reserve() -> str:
                barrier.wait()
                try:
                    ledger.reserve_submission(
                        manifest, idempotency_key="request-1", shape=self._shape()
                    )
                except delegation.DelegationError:
                    return "rejected"
                return "reserved"

            def drain() -> str:
                barrier.wait()
                ledger.begin_draining(manifest, reason="SIGUSR1")
                return "draining"

            with ThreadPoolExecutor(max_workers=2) as pool:
                reserve_future = pool.submit(reserve)
                drain_future = pool.submit(drain)
                reserve_result = reserve_future.result()
                self.assertEqual("draining", drain_future.result())

            self.assertIn(reserve_result, {"reserved", "rejected"})
            self.assertEqual(
                1 if reserve_result == "reserved" else 0,
                ledger.inflight_submission_count(manifest),
            )
            self.assertEqual("draining", ledger.controller_summary(manifest)["state"])

    def test_controller_requeue_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n[lifecycle]\nmax_requeues = 0\n",
                encoding="utf-8",
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.begin_draining(manifest, reason="SIGUSR1")
            with self.assertRaisesRegex(delegation.DelegationError, "limit"):
                ledger.request_requeue(manifest)

    def test_restart_recovers_when_requeue_acceptance_was_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.begin_draining(manifest, reason="SIGUSR1")
            ledger.request_requeue(manifest)

            restarted = ledger.begin_controller(manifest, restart_count=1)

            self.assertEqual("reconciling", restarted["state"])
            self.assertTrue(restarted["reconciliation_required"])

    def test_pre_network_ledger_schema_is_rejected_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute("PRAGMA user_version=4")
            ledger_path.chmod(0o600)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            with self.assertRaisesRegex(delegation.DelegationError, "schema version 4"):
                delegation.DelegationLedger(ledger_path).register(manifest)

    def test_expired_malformed_and_misspelled_manifests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expired = self._manifest(root, expires_at="2026-01-02T00:00:00Z")
            with self.assertRaisesRegex(delegation.DelegationError, "expired"):
                delegation.load_manifest(
                    expired,
                    expected_profile="genius",
                    now=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )

            malformed = root / "delegation.toml"
            malformed.write_text("this is not = valid = TOML\n", encoding="utf-8")
            with self.assertRaisesRegex(delegation.DelegationError, "invalid"):
                delegation.load_manifest(malformed, expected_profile="genius")

            misspelled = self._manifest(root)
            misspelled.write_text(
                misspelled.read_text(encoding="utf-8").replace(
                    "max_submissions = 2", "max_submissons = 2"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "max_submissons"):
                delegation.load_manifest(misspelled, expected_profile="genius")

    def test_policy_only_narrows_scheduler_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = delegation.load_manifest(
                self._manifest(Path(directory)), expected_profile="genius"
            )
            delegation.authorize_shape(manifest, self._shape())
            with self.assertRaisesRegex(delegation.DelegationError, "account"):
                delegation.authorize_shape(manifest, self._shape(account="other"))
            with self.assertRaisesRegex(delegation.DelegationError, "nodes"):
                delegation.authorize_shape(manifest, self._shape(nodes="3"))
            outside = self._shape()
            outside["directory"] = "/work/other"
            with self.assertRaisesRegex(delegation.DelegationError, "roots"):
                delegation.authorize_shape(manifest, outside)

    def test_all_scheduler_and_payload_policy_dimensions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            approved_digest = "a" * 64
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "script_sha256 = []",
                    f'script_sha256 = ["{approved_digest}"]',
                ),
                encoding="utf-8",
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            shape = self._shape()
            shape["boundary"] = {
                "container": "/images/worker.sif",
                "script_sha256": approved_digest,
            }
            delegation.authorize_shape(manifest, shape)

            cases = {
                "account": ("overrides", "account", "other"),
                "cluster": ("overrides", "cluster", "other"),
                "partition": ("overrides", "partition", "other"),
                "qos": ("overrides", "qos", "other"),
                "container": ("boundary", "container", "/images/other.sif"),
                "script_sha256": ("boundary", "script_sha256", "b" * 64),
                "nodes": ("overrides", "nodes", "3"),
            }
            for label, (section, field, value) in cases.items():
                with self.subTest(label=label):
                    denied = {
                        **shape,
                        "overrides": dict(shape["overrides"]),
                        "boundary": dict(shape["boundary"]),
                    }
                    denied[section][field] = value
                    with self.assertRaises(delegation.DelegationError):
                        delegation.authorize_shape(manifest, denied)

            outside = {
                **shape,
                "directory": "/work/other",
                "overrides": dict(shape["overrides"]),
                "boundary": dict(shape["boundary"]),
            }
            with self.assertRaisesRegex(delegation.DelegationError, "roots"):
                delegation.authorize_shape(manifest, outside)

    def test_ledger_enforces_idempotency_budget_ownership_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            first = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertFalse(first["idempotent_replay"])
            with self.assertRaisesRegex(
                delegation.SubmissionDenied, "active-job"
            ) as denied:
                ledger.reserve_submission(
                    manifest, idempotency_key="request-2", shape=self._shape()
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.ACTIVE_JOBS,
                denied.exception.code,
            )
            replay = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertTrue(replay["idempotent_replay"])
            changed = self._shape(nodes="2")
            with self.assertRaisesRegex(delegation.DelegationError, "different request"):
                ledger.reserve_submission(
                    manifest, idempotency_key="request-1", shape=changed
                )
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            self.assertTrue(ledger.owns_job("delegate-1", "12345", "wice"))
            self.assertFalse(ledger.owns_job("delegate-1", "99999", "wice"))
            ledger.reconcile_job(
                manifest, job_id="12345", cluster="wice", state="COMPLETED"
            )
            second = ledger.reserve_submission(
                manifest,
                idempotency_key="request-2",
                shape=self._shape(nodes="2"),
            )
            self.assertEqual("reserved", second["status"])
            summary = ledger.summary(manifest)
            self.assertEqual(2, summary["used_submissions"])
            self.assertEqual(1, summary["active_jobs"])
            self.assertEqual(0, summary["remaining"]["max_total_nodes"])

    def test_failed_reservation_releases_budget_and_rejection_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            ledger.release_reservation(
                manifest, idempotency_key="request-1", reason="sbatch failed"
            )
            ledger.reserve_submission(
                manifest, idempotency_key="request-2", shape=self._shape()
            )
            with self.assertRaises(delegation.DelegationError):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="request-3",
                    shape=self._shape(account="other"),
                )
            with closing(sqlite3.connect(ledger_path)) as connection:
                decisions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT decision FROM delegation_audit ORDER BY sequence"
                    )
                ]
            self.assertIn("rejected", decisions)

    def test_credit_ledger_enforces_per_job_total_replay_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            self._add_credit_budget(
                path,
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 5000
                maximum_per_job = 3000
                quote_ttl_seconds = 300
                """,
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)

            with self.assertRaisesRegex(
                delegation.SubmissionDenied,
                "requires a quoted-credit reservation",
            ) as missing:
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="missing-credit",
                    shape=self._shape(),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.QUOTE_FORMAT,
                missing.exception.code,
            )
            with self.assertRaisesRegex(
                delegation.SubmissionDenied, "per-job quoted-credit"
            ) as denied:
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="too-expensive",
                    shape=self._shape(),
                    quoted_credit=self._quoted_credit(3001),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.PER_JOB_CREDIT,
                denied.exception.code,
            )

            first_credit = self._quoted_credit(3000)
            first = ledger.reserve_submission(
                manifest,
                idempotency_key="request-1",
                shape=self._shape(),
                quoted_credit=first_credit,
            )
            replay = ledger.reserve_submission(
                manifest,
                idempotency_key="request-1",
                shape=self._shape(),
                quoted_credit=first_credit,
            )
            self.assertFalse(first["idempotent_replay"])
            self.assertTrue(replay["idempotent_replay"])
            with self.assertRaisesRegex(
                delegation.DelegationError, "identity was already reserved"
            ):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="reused-quote",
                    shape=self._shape(),
                    quoted_credit=first_credit,
                )
            for changed_credit in (
                self._quoted_credit(3000, token="b" * 64),
                self._quoted_credit(2999),
            ):
                with self.assertRaisesRegex(
                    delegation.DelegationError, "different request"
                ):
                    ledger.reserve_submission(
                        manifest,
                        idempotency_key="request-1",
                        shape=self._shape(),
                        quoted_credit=changed_credit,
                    )

            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            ledger.reconcile_job(
                manifest,
                job_id="12345",
                cluster="wice",
                state="COMPLETED",
            )
            ledger.reserve_submission(
                manifest,
                idempotency_key="request-2",
                shape=self._shape(nodes="2"),
                quoted_credit=self._quoted_credit(2000, token="c" * 64),
            )
            with self.assertRaisesRegex(
                delegation.SubmissionDenied, "total quoted-credit"
            ) as denied:
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="over-total",
                    shape=self._shape(),
                    quoted_credit=self._quoted_credit(1, token="d" * 64),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.TOTAL_CREDITS,
                denied.exception.code,
            )
            ledger.release_reservation(
                manifest,
                idempotency_key="request-2",
                reason="definite pre-acceptance failure",
            )
            replacement = ledger.reserve_submission(
                manifest,
                idempotency_key="replacement",
                shape=self._shape(nodes="2"),
                quoted_credit=self._quoted_credit(2000, token="e" * 64),
            )
            summary = ledger.summary(manifest)

            with closing(sqlite3.connect(ledger_path)) as connection:
                stored = connection.execute(
                    """SELECT quoted_cost_value,quoted_cost_scale,
                              quoted_cost_unit,quote_evidence_token,quote_expires_at
                       FROM submission_operations
                       WHERE idempotency_key='request-1'"""
                ).fetchone()

        self.assertEqual("reserved", replacement["status"])
        self.assertEqual(3000, stored[0])
        self.assertEqual(0, stored[1])
        self.assertEqual("credits", stored[2])
        self.assertEqual("a" * 64, stored[3])
        self.assertEqual("2098-01-01T00:00:00+00:00", stored[4])
        self.assertEqual(
            {"value": 5000, "scale": 0, "unit": "credits"},
            summary["quoted_credit"]["consumed_quoted_maximum"],
        )
        self.assertEqual(
            {"value": 0, "scale": 0, "unit": "credits"},
            summary["quoted_credit"]["remaining_quoted_maximum"],
        )

    def test_credit_count_budget_remains_independent_of_zero_cost_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "max_submissions = 2", "max_submissions = 1"
                ),
                encoding="utf-8",
            )
            self._add_credit_budget(
                path,
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 100
                quote_ttl_seconds = 300
                """,
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest,
                idempotency_key="request-1",
                shape=self._shape(),
                quoted_credit=self._quoted_credit(0),
            )
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            ledger.reconcile_job(
                manifest,
                job_id="12345",
                cluster="wice",
                state="COMPLETED",
            )

            with self.assertRaisesRegex(
                delegation.SubmissionDenied, "submission budget"
            ) as denied:
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="request-2",
                    shape=self._shape(),
                    quoted_credit=self._quoted_credit(0, token="b" * 64),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.SUBMISSION_COUNT,
                denied.exception.code,
            )

    def test_uncertain_credit_remains_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            self._add_credit_budget(
                path,
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 5000
                quote_ttl_seconds = 300
                """,
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest,
                idempotency_key="uncertain",
                shape=self._shape(),
                quoted_credit=self._quoted_credit(3000),
            )
            ledger.release_reservation(
                manifest,
                idempotency_key="uncertain",
                reason="scheduler acceptance is unknown",
                uncertain=True,
            )

            with self.assertRaisesRegex(
                delegation.DelegationError, "total quoted-credit"
            ):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="would-overspend",
                    shape=self._shape(),
                    quoted_credit=self._quoted_credit(2001, token="b" * 64),
                )

    def test_expired_credit_is_rejected_without_a_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            self._add_credit_budget(path)
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            now = datetime(2026, 10, 16, 12, 5, tzinfo=UTC)
            with (
                mock.patch("hpc_tools.delegation._utc_now", return_value=now),
                self.assertRaisesRegex(
                    delegation.SubmissionDenied, "has expired"
                ) as denied,
            ):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="expired",
                    shape=self._shape(),
                    quoted_credit=self._quoted_credit(
                        1,
                        expires_at=now,
                    ),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.QUOTE_EXPIRED,
                denied.exception.code,
            )
            with closing(sqlite3.connect(ledger_path)) as connection:
                operations = connection.execute(
                    "SELECT COUNT(*) FROM submission_operations"
                ).fetchone()[0]

        self.assertEqual(0, operations)

    def test_concurrent_credit_reservations_cannot_overspend_final_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "max_active_jobs = 1", "max_active_jobs = 2"
                ),
                encoding="utf-8",
            )
            self._add_credit_budget(
                path,
                """
                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 5000
                maximum_per_job = 3000
                quote_ttl_seconds = 300
                """,
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)

            def reserve(index: int) -> str:
                try:
                    ledger.reserve_submission(
                        manifest,
                        idempotency_key=f"request-{index}",
                        shape=self._shape(),
                        quoted_credit=self._quoted_credit(
                            3000,
                            token=f"{index}" * 64,
                        ),
                    )
                except delegation.DelegationError:
                    return "rejected"
                return "accepted"

            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions = list(pool.map(reserve, (1, 2)))
            with closing(sqlite3.connect(ledger_path)) as connection:
                consumed = connection.execute(
                    """SELECT COUNT(*),SUM(quoted_cost_value)
                       FROM submission_operations WHERE status != 'failed'"""
                ).fetchone()

        self.assertEqual(["accepted", "rejected"], sorted(decisions))
        self.assertEqual((1, 3000), consumed)

    def test_array_elements_consume_cumulative_node_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            with self.assertRaisesRegex(
                delegation.SubmissionDenied, "aggregate nodes"
            ) as denied:
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="array-1",
                    shape=self._shape(array="0-3"),
                )
            self.assertEqual(
                delegation.SubmissionDenialCode.RESOURCES,
                denied.exception.code,
            )
            self.assertEqual("nodes", denied.exception.resource)

    def test_concurrent_first_use_and_reservations_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"

            with ThreadPoolExecutor(max_workers=2) as pool:
                registrations = [
                    pool.submit(
                        delegation.DelegationLedger(ledger_path).register,
                        manifest,
                    )
                    for _ in range(2)
                ]
                for future in registrations:
                    future.result()

            ledger = delegation.DelegationLedger(ledger_path)
            def reserve(key: str) -> str:
                try:
                    ledger.reserve_submission(
                        manifest, idempotency_key=key, shape=self._shape()
                    )
                except delegation.DelegationError:
                    return "rejected"
                return "accepted"

            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions = list(pool.map(reserve, ("request-1", "request-2")))
            self.assertEqual(["accepted", "rejected"], sorted(decisions))

    def test_concurrent_count_and_resource_limits_are_atomic(self) -> None:
        cases = {
            "count": {
                "max_submissions = 2": "max_submissions = 1",
                "max_active_jobs = 1": "max_active_jobs = 2",
            },
            "resources": {
                "max_active_jobs = 1": "max_active_jobs = 2",
                "max_total_nodes = 3": "max_total_nodes = 1",
            },
        }
        for label, replacements in cases.items():
            with self.subTest(limit=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self._manifest(root)
                content = path.read_text(encoding="utf-8")
                for old, new in replacements.items():
                    content = content.replace(old, new)
                path.write_text(content, encoding="utf-8")
                manifest = delegation.load_manifest(
                    path,
                    expected_profile="genius",
                )
                ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
                ledger.register(manifest)
                barrier = threading.Barrier(2)

                def reserve(index: int) -> str:
                    barrier.wait()
                    try:
                        ledger.reserve_submission(
                            manifest,
                            idempotency_key=f"request-{index}",
                            shape=self._shape(),
                        )
                    except delegation.DelegationError:
                        return "rejected"
                    return "accepted"

                with ThreadPoolExecutor(max_workers=2) as pool:
                    decisions = list(pool.map(reserve, (1, 2)))

                self.assertEqual(["accepted", "rejected"], sorted(decisions))
                summary = ledger.summary(manifest)
                self.assertEqual(1, summary["used_submissions"])
                self.assertEqual(1, summary["requested_resources"]["nodes"])

    def test_concurrent_duplicate_key_submits_once_and_budget_stays_capped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)

            def reserve() -> dict[str, object]:
                return ledger.reserve_submission(
                    manifest, idempotency_key="same-request", shape=self._shape()
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: reserve(), range(2)))
            self.assertEqual(
                [False, True],
                sorted(result["idempotent_replay"] for result in results),
            )
            summary = ledger.summary(manifest)
            self.assertEqual(1, summary["used_submissions"])
            self.assertEqual(1, summary["active_jobs"])
            with self.assertRaisesRegex(delegation.DelegationError, "active-job"):
                ledger.reserve_submission(
                    manifest, idempotency_key="another-request", shape=self._shape()
                )

    def test_accepted_submission_recovery_retains_ownership_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_submission_audit
                       BEFORE INSERT ON delegation_audit
                       WHEN NEW.operation = 'record_submission'
                       BEGIN SELECT RAISE(FAIL, 'audit unavailable'); END"""
                )
                connection.commit()

            with self.assertRaisesRegex(delegation.DelegationError, "audit unavailable"):
                ledger.record_submission(
                    manifest,
                    idempotency_key="request-1",
                    job_id="12345",
                    cluster="wice",
                )
            ledger.record_accepted_submission_uncertain(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
                reason="audit unavailable",
            )

            self.assertTrue(ledger.owns_job("delegate-1", "12345", "wice"))
            replay = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertEqual("uncertain", replay["status"])
            self.assertEqual(1, ledger.summary(manifest)["active_jobs"])
            ledger.reconcile_job(
                manifest, job_id="12345", cluster="wice", state="COMPLETED"
            )
            self.assertEqual(0, ledger.summary(manifest)["active_jobs"])

    def test_accepted_cancellation_recovery_is_not_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            ledger.reserve_lifecycle_operation(
                manifest,
                idempotency_key="cancel-1",
                operation="cancel",
                job_id="12345",
                cluster="wice",
            )
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_lifecycle_audit
                       BEFORE INSERT ON delegation_audit
                       WHEN NEW.operation = 'lifecycle_result'
                       BEGIN SELECT RAISE(FAIL, 'audit unavailable'); END"""
                )
                connection.commit()

            result = {"returncode": 0, "jobid": "12345"}
            with self.assertRaisesRegex(delegation.DelegationError, "audit unavailable"):
                ledger.record_lifecycle_result(
                    manifest,
                    idempotency_key="cancel-1",
                    succeeded=True,
                    result=result,
                )
            ledger.record_accepted_lifecycle_uncertain(
                manifest,
                idempotency_key="cancel-1",
                result=result,
                reason="audit unavailable",
            )
            replay = ledger.reserve_lifecycle_operation(
                manifest,
                idempotency_key="cancel-1",
                operation="cancel",
                job_id="12345",
                cluster="wice",
            )
            self.assertEqual("uncertain", replay["status"])
            self.assertEqual(0, replay["result"]["returncode"])

    def test_revocation_blocks_further_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.revoke(manifest.identifier, reason="operator request")
            with self.assertRaisesRegex(delegation.DelegationError, "revoked"):
                ledger.summary(manifest)


if __name__ == "__main__":
    unittest.main()
