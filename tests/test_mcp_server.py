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


class McpServerTests(unittest.TestCase):
    def test_mcp_tool_and_resource_registries_are_stable(self) -> None:
        self.assertEqual(
            mcp_server.TOOL_NAMES,
            (
                "hpc_profiles_list",
                "hpc_paths",
                "hpc_profile_show",
                "hpc_hardware_context",
                "hpc_hardware_sources",
                "hpc_references_list",
                "hpc_references_show",
                "hpc_plugins_list",
                "hpc_submissions_list",
                "hpc_jobs",
                "hpc_job",
                "hpc_slurm_limits",
                "hpc_module_spider",
                "hpc_storage_inspect",
                "hpc_site_env",
                "hpc_references_create",
                "hpc_references_import",
                "hpc_references_attach",
                "hpc_submissions_mark_collected",
                "hpc_submissions_mark_analysed",
                "hpc_submissions_close",
                "hpc_write_probe",
                "hpc_install_probe",
                "hpc_write_container",
                "hpc_install_container",
                "hpc_quote_job",
                "hpc_validate_job",
                "hpc_submit_job",
            ),
        )
        self.assertEqual(
            mcp_server.RESOURCE_URIS,
            (
                "hpc://paths",
                "hpc://config",
                "hpc://submissions/active",
                "hpc://submissions/all",
            ),
        )
        self.assertEqual(
            mcp_server.RESOURCE_TEMPLATES,
            (
                "hpc://profiles/{profile}",
                "hpc://profiles/{profile}/hardware",
                "hpc://profiles/{profile}/slurm",
                "hpc://profiles/{profile}/storage",
                "hpc://reference-sets/{name}",
            ),
        )

    def test_mcp_tool_schemas_are_stable_for_guarded_submission(self) -> None:
        expected = {
            "hpc_quote_job": [
                "jobscript",
                "directory",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "profile",
                "config",
                "dry_run",
            ],
            "hpc_validate_job": [
                "jobscript",
                "directory",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "profile",
                "config",
                "dry_run",
            ],
            "hpc_submit_job": [
                "jobscript",
                "directory",
                "quote_evidence",
                "validation_evidence",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "profile",
                "config",
                "dry_run",
                "confirm",
            ],
        }

        for name, parameter_names in expected.items():
            with self.subTest(name=name):
                signature = inspect.signature(getattr(mcp_server, name))
                self.assertEqual(list(signature.parameters), parameter_names)
                self.assertNotIn("overrides", signature.parameters)

    def test_guarded_tools_include_evidence_gated_slurm_submit_workflow(self) -> None:
        names = set(mcp_server.TOOL_NAMES)

        self.assertIn("hpc_profiles_list", names)
        self.assertIn("hpc_paths", names)
        self.assertIn("hpc_jobs", names)
        self.assertIn("hpc_slurm_limits", names)
        self.assertIn("hpc_module_spider", names)
        self.assertIn("hpc_storage_inspect", names)
        self.assertIn("hpc_references_create", names)
        self.assertIn("hpc_submissions_close", names)
        self.assertIn("hpc_write_probe", names)
        self.assertIn("hpc_install_probe", names)
        self.assertIn("hpc_write_container", names)
        self.assertIn("hpc_install_container", names)
        self.assertIn("hpc_quote_job", names)
        self.assertIn("hpc_validate_job", names)
        self.assertIn("hpc_submit_job", names)

    def test_read_only_resources_are_listed_without_write_resources(self) -> None:
        uris = set(mcp_server.RESOURCE_URIS)
        templates = set(mcp_server.RESOURCE_TEMPLATES)

        self.assertIn("hpc://paths", uris)
        self.assertIn("hpc://config", uris)
        self.assertIn("hpc://submissions/active", uris)
        self.assertIn("hpc://profiles/{profile}/hardware", templates)
        self.assertIn("hpc://reference-sets/{name}", templates)
        self.assertNotIn("hpc://submit", uris)
        self.assertNotIn("hpc://profiles/{profile}/install-probe", templates)

    def test_profiles_list_uses_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_profiles_list(config=str(config_path))

        self.assertEqual(result["default_profile"], "genius")
        self.assertEqual(result["profiles"][0]["name"], "genius")
        self.assertEqual(result["profiles"][0]["ssh_target"], "genius")

    def test_profile_show_resolves_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_profile_show(config=str(config_path))

        self.assertEqual(result["name"], "genius")
        self.assertEqual(result["ssh_target"], "genius")
        self.assertEqual(result["default_cluster"], "wice")

    def test_remote_read_tool_dry_run_returns_structured_ssh_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_jobs(config=str(config_path), cluster="wice", dry_run=True)

        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["dry_run"])
        self.assertIn("squeue -M wice", result["command"])
        self.assertIn("ssh -x genius", result["ssh_command"])

    def test_remote_read_tool_captures_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="JOBID\n123\n", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=completed) as remote:
                result = mcp_server.hpc_job(config=str(config_path), jobid="123", cluster="wice")

        self.assertEqual(result["stdout"], "JOBID\n123\n")
        self.assertEqual(result["stderr"], "")
        self.assertFalse(result["dry_run"])
        self.assertIn("squeue -M wice -j 123", result["command"])
        remote.assert_called_once()

    def test_module_spider_tool_searches_remote_lmod_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(
                returncode=0,
                stdout="DMTCP/3.0.0-GCCcore-12.3.0\n",
                stderr="",
            )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=completed) as remote:
                result = mcp_server.hpc_module_spider(
                    config=str(config_path),
                    name="DMTCP; rm -rf /",
                )

        self.assertEqual(result["stdout"], "DMTCP/3.0.0-GCCcore-12.3.0\n")
        self.assertIn("module spider 'DMTCP; rm -rf /' 2>&1", result["command"])
        self.assertFalse(result["dry_run"])
        remote.assert_called_once()

    def test_resource_config_reads_active_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                text = mcp_server.resource_config()

        self.assertIn('default_profile = "genius"', text)
        self.assertIn("[profiles.genius]", text)

    def test_resource_profile_returns_json_from_active_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                result = json.loads(mcp_server.resource_profile("genius"))

        self.assertEqual(result["name"], "genius")
        self.assertEqual(result["ssh_target"], "genius")

    def test_profile_reference_resources_read_active_config_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                hardware = mcp_server.resource_profile_hardware("genius")
                slurm = mcp_server.resource_profile_slurm("genius")
                storage = mcp_server.resource_profile_storage("genius")

        self.assertEqual(hardware, "# hardware\n")
        self.assertEqual(slurm, "# slurm\n")
        self.assertEqual(storage, "# storage\n")

    def test_reference_set_resource_reads_default_reference_sets_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_config(root)
            self._write_reference_set(root, "baseline")

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=False):
                result = json.loads(mcp_server.resource_reference_set("baseline"))

        self.assertEqual(result["name"], "baseline")
        self.assertTrue(result["hardware_reference"].endswith("hardware.md"))

    def test_local_mcp_tools_work_without_profile_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "submissions.jsonl"

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                paths = mcp_server.hpc_paths()
                references = mcp_server.hpc_references_list()
                plugins = mcp_server.hpc_plugins_list()
                submissions = mcp_server.hpc_submissions_list(log=str(log_path))
                probe = mcp_server.hpc_write_probe(output="-")
                container = mcp_server.hpc_write_container(output=str(root / "bundle"))

        self.assertTrue(paths["config"].endswith("hpc-tools/config.toml"))
        self.assertEqual(references["reference_sets"], [])
        self.assertIn("plugins", plugins)
        self.assertEqual(submissions["submissions"], [])
        self.assertIn("#SBATCH --job-name=hardware-probe", probe["contents"])
        self.assertIn("create_apptainer_container.slurm", container["files"])
        self.assertFalse(log_path.exists())
        self.assertFalse((root / "bundle").exists())

    def test_profile_required_tools_reject_missing_or_unknown_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root / "missing")}, clear=True):
                with self.assertRaisesRegex(ValueError, "configuration file not found"):
                    mcp_server.hpc_jobs(dry_run=True)

            with self.assertRaisesRegex(ValueError, "unknown profile"):
                mcp_server.hpc_jobs(profile="missing", config=str(config_path), dry_run=True)

    def test_read_only_tools_do_not_write_local_or_remote_state_when_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            log_path = root / "hpc-tools" / "submissions.jsonl"

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ), mock.patch("hpc_tools.mcp_server.run_remote_capture") as remote:
                jobs = mcp_server.hpc_jobs(cluster="wice", dry_run=True)
                hardware_sources = mcp_server.hpc_hardware_sources()
                active = mcp_server.hpc_submissions_list()

        self.assertTrue(jobs["dry_run"])
        self.assertEqual(hardware_sources["profile"], "genius")
        self.assertEqual(active["submissions"], [])
        self.assertFalse(log_path.exists())
        remote.assert_not_called()

    def test_references_create_requires_confirm_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                preview = mcp_server.hpc_references_create("baseline")
                self.assertTrue(preview["confirm_required"])
                self.assertFalse((root / "hpc-tools" / "reference-sets" / "baseline").exists())

                result = mcp_server.hpc_references_create("baseline", confirm=True)

        self.assertTrue(result["created"])
        self.assertEqual(result["reference_set"]["name"], "baseline")
        self.assertFalse(result["confirm_required"])

    def test_references_attach_requires_confirm_before_config_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            self._write_reference_set(root, "baseline")

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                preview = mcp_server.hpc_references_attach("baseline")
                self.assertTrue(preview["confirm_required"])
                self.assertNotIn("reference_set", config_path.read_text(encoding="utf-8"))

                result = mcp_server.hpc_references_attach("baseline", confirm=True)

                self.assertTrue(result["attached"])
                self.assertIn('reference_set = "baseline"', config_path.read_text(encoding="utf-8"))

    def test_submissions_close_requires_confirm_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "submissions.jsonl"

            preview = mcp_server.hpc_submissions_close(
                "run-1",
                reason="done",
                log=str(log_path),
            )
            self.assertTrue(preview["confirm_required"])
            self.assertFalse(log_path.exists())

            result = mcp_server.hpc_submissions_close(
                "run-1",
                reason="done",
                log=str(log_path),
                confirm=True,
            )

            self.assertTrue(result["appended"])
            self.assertIn('"event": "closed"', log_path.read_text(encoding="utf-8"))

    def test_write_probe_requires_confirm_before_writing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"

            preview = mcp_server.hpc_write_probe(output=str(output), account="proj")
            self.assertTrue(preview["confirm_required"])
            self.assertIn("#SBATCH --account=proj", preview["contents"])
            self.assertFalse(output.exists())

            result = mcp_server.hpc_write_probe(
                output=str(output),
                account="proj",
                confirm=True,
            )

            self.assertTrue(result["written"])
            self.assertIn("#SBATCH --account=proj", output.read_text(encoding="utf-8"))

    def test_write_container_requires_confirm_before_writing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"

            preview = mcp_server.hpc_write_container(output=str(output))
            self.assertTrue(preview["confirm_required"])
            self.assertIn("create_apptainer_container.slurm", preview["files"])
            self.assertFalse(output.exists())

            result = mcp_server.hpc_write_container(output=str(output), confirm=True)

            self.assertTrue(result["written"])
            self.assertTrue((output / "create_apptainer_container.slurm").exists())

    def test_install_probe_preview_does_not_execute_without_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            with mock.patch("hpc_tools.mcp_server.run_remote_capture") as remote:
                result = mcp_server.hpc_install_probe(
                    config=str(config_path),
                    directory="$VSC_DATA/probes",
                    account="proj",
                    dry_run=False,
                )

        self.assertTrue(result["confirm_required"])
        self.assertFalse(result["executed"])
        self.assertIn("cat > hardware-probe.slurm", result["command"])
        remote.assert_not_called()

    def test_install_container_executes_only_with_confirm_and_not_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=completed) as remote:
                result = mcp_server.hpc_install_container(
                    config=str(config_path),
                    directory="$VSC_DATA/containers",
                    confirm=True,
                    dry_run=False,
                )

        self.assertTrue(result["executed"])
        self.assertFalse(result["dry_run"])
        self.assertIn("cat > create_apptainer_container.slurm", result["command"])
        remote.assert_called_once()

    def test_quote_job_returns_shape_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=completed):
                result = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                    time="00:30:00",
                )

        evidence = result["quote_evidence"]
        self.assertTrue(evidence["ok"])
        self.assertFalse(evidence["dry_run"])
        self.assertEqual(evidence["account"], "proj")
        self.assertEqual(evidence["shape_token"], result["resource_shape"]["shape_token"])
        self.assertIn("sam-quote sbatch", result["command"])
        self.assertIn("--account proj", result["command"])

    def test_validate_job_returns_shape_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="sbatch: Job 1 to start later\n", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=completed):
                result = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )

        evidence = result["validation_evidence"]
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["shape_token"], result["resource_shape"]["shape_token"])
        self.assertIn("sbatch --test-only", result["command"])

    def test_submit_job_rejects_stale_quote_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )

            with self.assertRaisesRegex(ValueError, "stale"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="other",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

    def test_submit_job_refuses_missing_account_quote_validation_or_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with self.assertRaisesRegex(ValueError, "requires an account"):
                mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with self.assertRaisesRegex(ValueError, "expected quote evidence"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence={},
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

            with self.assertRaisesRegex(ValueError, "expected validation evidence"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence={},
                    confirm=True,
                    dry_run=False,
                )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture") as remote:
                preview = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    dry_run=False,
                    confirm=False,
                )

        self.assertTrue(preview["confirm_required"])
        self.assertFalse(preview["executed"])
        remote.assert_not_called()

    def test_submit_job_rejects_dry_run_or_tampered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            dry_quote = mcp_server.hpc_quote_job(
                config=str(config_path),
                directory="$VSC_DATA/Projects/demo",
                jobscript="job.slurm",
                account="proj",
                cluster="wice",
                dry_run=True,
            )
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")
            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=validate_completed):
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with self.assertRaisesRegex(ValueError, "dry run"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=dry_quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

            tampered_quote = dict(validation["validation_evidence"]) | {"type": "quote"}
            with self.assertRaisesRegex(ValueError, "token is invalid"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=tampered_quote,
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

    def test_submit_job_requires_confirm_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture") as remote:
                preview = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                )

        self.assertTrue(preview["confirm_required"])
        self.assertFalse(preview["executed"])
        self.assertIn("sbatch --account proj --clusters wice job.slurm", preview["command"])
        remote.assert_not_called()

    def test_submit_job_executes_and_logs_with_matching_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")
            submit_completed = mock.Mock(
                returncode=0,
                stdout="Submitted batch job 60351238 on cluster wice\n",
                stderr="",
            )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                )

            with mock.patch("hpc_tools.mcp_server.run_remote_capture", return_value=submit_completed), \
                    mock.patch("hpc_tools.mcp_server.submissions.append_event") as append_event:
                result = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

        self.assertTrue(result["executed"])
        self.assertTrue(result["logged"])
        self.assertEqual(result["submission_event"]["job_id"], "60351238")
        append_event.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_fastmcp_server_lists_and_calls_tools_and_resources(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                self._write_reference_set(root, "baseline")

                with mock.patch.dict(
                    "os.environ",
                    {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                    clear=False,
                ):
                    server = mcp_server.create_server()
                    listed = await server.list_tools()
                    names = {tool.name for tool in listed}

                    self.assertEqual(set(mcp_server.TOOL_NAMES), names)
                    self.assertIn("hpc_submit_job", names)

                    content, structured = await server.call_tool("hpc_paths", {})
                    self.assertEqual(len(content), 1)
                    self.assertIn("hardware_probe_template", content[0].text)
                    self.assertIn("hardware_probe_template", structured)

                    listed_resources = await server.list_resources()
                    resource_uris = {str(resource.uri) for resource in listed_resources}
                    self.assertEqual(set(mcp_server.RESOURCE_URIS), resource_uris)

                    listed_templates = await server.list_resource_templates()
                    template_uris = {template.uriTemplate for template in listed_templates}
                    self.assertEqual(set(mcp_server.RESOURCE_TEMPLATES), template_uris)

                    read = await server.read_resource("hpc://profiles/genius/hardware")
                    self.assertEqual(read[0].content, "# hardware\n")

                    read = await server.read_resource("hpc://reference-sets/baseline")
                    self.assertIn('"name": "baseline"', read[0].content)

        asyncio.run(exercise_server())

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
                sam_quote_command = "sam-quote"
                default_cluster = "wice"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config_path

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


if __name__ == "__main__":
    unittest.main()
