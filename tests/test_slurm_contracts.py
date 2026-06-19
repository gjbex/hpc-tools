from __future__ import annotations

import unittest

from hpc_tools.config import ConfigError
from hpc_tools import slurm_contracts

from test_cli_fixtures import make_profile


class SlurmContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
