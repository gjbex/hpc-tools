from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from test_cli_fixtures import make_profile

from hpc_tools import slurm_contracts
from hpc_tools.config import ConfigError
from hpc_tools.credit_quotes import CreditAmount


class SlurmContractTests(unittest.TestCase):
    @staticmethod
    def _result() -> dict[str, object]:
        return {
            "command": "sam-quote sbatch --account proj job.slurm",
            "executor": "local",
            "execution_command": "sam-quote sbatch --account proj job.slurm",
            "ssh_command": None,
            "returncode": 0,
            "stdout": "2730\n",
            "stderr": "",
            "dry_run": False,
        }

    def test_submit_overrides_are_ordered_and_reject_unknown_options(self) -> None:
        overrides = slurm_contracts.SubmitOverrides.from_values(
            account="proj",
            cluster="wice",
            reservation="pilot",
        )

        self.assertEqual(
            overrides.quote_args("job.slurm"),
            [
                "sbatch",
                "--account",
                "proj",
                "--clusters",
                "wice",
                "--reservation",
                "pilot",
                "job.slurm",
            ],
        )
        self.assertEqual(
            slurm_contracts.normalize_submit_overrides(account="proj")["account"],
            "proj",
        )
        with self.assertRaisesRegex(ConfigError, "unsupported submit override"):
            slurm_contracts.normalize_submit_overrides(unsupported="value")

    def test_submission_shape_token_is_deterministic_and_shape_bound(self) -> None:
        profile = make_profile()
        overrides = slurm_contracts.SubmitOverrides.from_values(
            account="proj",
            cluster="wice",
        )

        shape = slurm_contracts.SubmissionShape.from_submit(
            profile=profile,
            jobscript="job.slurm",
            directory="$VSC_DATA/Projects/demo",
            overrides=overrides,
        )
        same_shape = shape.to_dict()
        changed_shape = slurm_contracts.SubmissionShape.from_submit(
            profile=profile,
            jobscript="job.slurm",
            directory="$VSC_DATA/Projects/demo",
            overrides=slurm_contracts.SubmitOverrides.from_values(
                account="proj",
                cluster="wice",
                partition="batch",
            ),
        ).to_dict()

        self.assertEqual(shape.to_dict()["shape_token"], same_shape["shape_token"])
        self.assertNotEqual(shape.to_dict()["shape_token"], changed_shape["shape_token"])

    def test_evidence_validation_rejects_dry_run_failure_and_tampering(self) -> None:
        profile = make_profile()
        shape = slurm_contracts.submission_shape(
            profile,
            "job.slurm",
            "$VSC_DATA/Projects/demo",
            slurm_contracts.SubmitOverrides.from_values(account="proj", cluster="wice"),
        )
        result = {
            "command": "sam-quote sbatch --account proj job.slurm",
            "ssh_command": "ssh genius sam-quote",
            "returncode": 0,
            "stdout": "123\n",
            "stderr": "",
            "dry_run": False,
        }
        evidence = slurm_contracts.submission_evidence("quote", shape, result)

        slurm_contracts.validate_evidence("quote", evidence, shape)
        with self.assertRaisesRegex(ConfigError, "token is invalid"):
            slurm_contracts.validate_evidence(
                "quote",
                evidence | {"stdout": "changed\n"},
                shape,
            )
        with self.assertRaisesRegex(ConfigError, "dry run"):
            slurm_contracts.validate_evidence(
                "quote",
                slurm_contracts.submission_evidence(
                    "quote",
                    shape,
                    result | {"dry_run": True},
                ),
                shape,
            )
        with self.assertRaisesRegex(ConfigError, "did not succeed"):
            slurm_contracts.validate_evidence(
                "quote",
                slurm_contracts.submission_evidence(
                    "quote",
                    shape,
                    result | {"returncode": 1},
                ),
                shape,
            )

    def test_evidence_records_generic_execution_metadata(self) -> None:
        profile = make_profile()
        shape = slurm_contracts.submission_shape(
            profile,
            "job.slurm",
            "$VSC_DATA/Projects/demo",
            slurm_contracts.SubmitOverrides.from_values(account="proj"),
        )
        result = {
            "command": "sbatch --account proj job.slurm",
            "executor": "local",
            "execution_command": "bash -l -c 'sbatch --account proj job.slurm'",
            "ssh_command": None,
            "returncode": 0,
            "stdout": "Submitted batch job 123\n",
            "stderr": "",
            "dry_run": False,
        }

        evidence = slurm_contracts.submission_evidence("validation", shape, result)

        self.assertEqual(evidence["executor"], "local")
        self.assertEqual(evidence["execution_command"], result["execution_command"])
        self.assertIsNone(evidence["ssh_command"])
        slurm_contracts.validate_evidence(
            "validation",
            evidence,
            shape,
            executor="local",
        )
        with self.assertRaisesRegex(ConfigError, "not the current ssh executor"):
            slurm_contracts.validate_evidence(
                "validation",
                evidence,
                shape,
                executor="ssh",
            )

    def test_credit_quote_and_validation_evidence_form_one_expiring_chain(
        self,
    ) -> None:
        profile = make_profile()
        shape = slurm_contracts.submission_shape(
            profile,
            "job.slurm",
            "$VSC_DATA/Projects/demo",
            slurm_contracts.SubmitOverrides.from_values(account="proj"),
        )
        issued_at = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
        quote = slurm_contracts.submission_evidence(
            "quote",
            shape,
            self._result(),
            quoted_cost=CreditAmount(value=2730, scale=0, unit="credits"),
            quote_ttl_seconds=300,
            now=issued_at,
        )
        validation = slurm_contracts.submission_evidence(
            "validation",
            shape,
            self._result(),
            quote_evidence_token=quote["evidence_token"],
            now=issued_at + timedelta(seconds=1),
        )

        checked_quote = slurm_contracts.validate_evidence(
            "quote",
            quote,
            shape,
            executor="local",
            now=issued_at + timedelta(seconds=2),
            credit_unit="credits",
            credit_scale=0,
            quote_ttl_seconds=300,
        )
        checked_validation = slurm_contracts.validate_evidence(
            "validation",
            validation,
            shape,
            executor="local",
            now=issued_at + timedelta(seconds=2),
            expected_quote_evidence_token=checked_quote.evidence_token,
            not_before=checked_quote.timestamp,
        )

        self.assertEqual(2730, checked_quote.quoted_cost.value)
        self.assertEqual(
            quote["evidence_token"], checked_validation.quote_evidence_token
        )

    def test_credit_evidence_rejects_expiry_dimensions_order_and_restart(self) -> None:
        profile = make_profile()
        shape = slurm_contracts.submission_shape(
            profile,
            "job.slurm",
            "$VSC_DATA/Projects/demo",
            slurm_contracts.SubmitOverrides.from_values(account="proj"),
        )
        issued_at = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
        with mock.patch.object(slurm_contracts, "_EVIDENCE_SECRET", b"a" * 32):
            quote = slurm_contracts.submission_evidence(
                "quote",
                shape,
                self._result(),
                quoted_cost=CreditAmount(value=2730, scale=0, unit="credits"),
                quote_ttl_seconds=300,
                now=issued_at,
            )
            early_validation = slurm_contracts.submission_evidence(
                "validation",
                shape,
                self._result(),
                quote_evidence_token=quote["evidence_token"],
                now=issued_at - timedelta(seconds=1),
            )
            with self.assertRaisesRegex(ConfigError, "has expired"):
                slurm_contracts.validate_evidence(
                    "quote",
                    quote,
                    shape,
                    now=issued_at + timedelta(seconds=300),
                    credit_unit="credits",
                    credit_scale=0,
                    quote_ttl_seconds=300,
                )
            with self.assertRaisesRegex(ConfigError, "timestamp is in the future"):
                slurm_contracts.validate_evidence(
                    "quote",
                    quote,
                    shape,
                    now=issued_at - timedelta(seconds=1),
                    credit_unit="credits",
                    credit_scale=0,
                    quote_ttl_seconds=300,
                )
            with self.assertRaisesRegex(ConfigError, "configured TTL"):
                slurm_contracts.validate_evidence(
                    "quote",
                    quote,
                    shape,
                    now=issued_at,
                    credit_unit="credits",
                    credit_scale=0,
                    quote_ttl_seconds=301,
                )
            with self.assertRaisesRegex(ConfigError, "configured unit"):
                slurm_contracts.validate_evidence(
                    "quote",
                    quote,
                    shape,
                    now=issued_at,
                    credit_unit="service-units",
                    credit_scale=0,
                    quote_ttl_seconds=300,
                )
            with self.assertRaisesRegex(ConfigError, "configured scale"):
                slurm_contracts.validate_evidence(
                    "quote",
                    quote,
                    shape,
                    now=issued_at,
                    credit_unit="credits",
                    credit_scale=2,
                    quote_ttl_seconds=300,
                )
            with self.assertRaisesRegex(ConfigError, "predates"):
                slurm_contracts.validate_evidence(
                    "validation",
                    early_validation,
                    shape,
                    now=issued_at,
                    expected_quote_evidence_token=quote["evidence_token"],
                    not_before=issued_at,
                )
            wrongly_bound = slurm_contracts.submission_evidence(
                "validation",
                shape,
                self._result(),
                quote_evidence_token="f" * 64,
                now=issued_at,
            )
            with self.assertRaisesRegex(ConfigError, "not bound"):
                slurm_contracts.validate_evidence(
                    "validation",
                    wrongly_bound,
                    shape,
                    now=issued_at,
                    expected_quote_evidence_token=quote["evidence_token"],
                    not_before=issued_at,
                )

        with (
            mock.patch.object(slurm_contracts, "_EVIDENCE_SECRET", b"b" * 32),
            self.assertRaisesRegex(ConfigError, "token is invalid"),
        ):
            slurm_contracts.validate_evidence(
                "quote",
                quote,
                shape,
                now=issued_at,
                credit_unit="credits",
                credit_scale=0,
                quote_ttl_seconds=300,
            )


if __name__ == "__main__":
    unittest.main()
