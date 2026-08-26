from __future__ import annotations

from test_skill_fixtures import *


class SkillFeatureTests(SkillFixtures, unittest.TestCase):
    def test_shared_conceptual_references_exist_and_are_routed(self) -> None:
        for filename, required_strings in SHARED_CONCEPTS.items():
            with self.subTest(shared=filename):
                path = ROOT / "skills" / "_shared" / filename
                self.assertTrue(path.exists(), f"missing {path}")
                text = path.read_text(encoding="utf-8")
                for required in required_strings:
                    self.assertIn(required, text)

        expected_refs = {
            "hpc-cluster-onboarding": [
                "hpc-slurm-concepts.md",
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
            ],
            "hpc-slurm-jobs": [
                "hpc-slurm-concepts.md",
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
            ],
            "hpc-slurm-job-arrays": [
                "hpc-slurm-concepts.md",
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
            ],
            "hpc-slurm-benchmark": [
                "hpc-benchmark-methodology.md",
                "hpc-slurm-concepts.md",
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
            ],
            "hpc-filesystem-environment": [
                "hpc-storage-io.md",
            ],
            "hpc-container-workflows": [
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
                "hpc-slurm-concepts.md",
            ],
            "hpc-python-packages": [
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
                "hpc-slurm-concepts.md",
            ],
            "hpc-deploy-build": [
                "hpc-storage-io.md",
                "hpc-slurm-concepts.md",
            ],
            "hpc-r-packages": [
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
                "hpc-slurm-concepts.md",
            ],
            "hpc-cluster-discovery": [
                "hpc-slurm-concepts.md",
                "hpc-storage-io.md",
                "hpc-accounting-safety.md",
            ],
        }
        for skill, refs in expected_refs.items():
            with self.subTest(skill=skill):
                text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("Conceptual References", text)
                for ref in refs:
                    self.assertIn(f"../_shared/{ref}", text)

    def test_cluster_discovery_skill_uses_probe_artifacts(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-discovery" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("install-hardware-probe", text)
        self.assertIn("install-probe --kind hardware", text)
        self.assertIn("install-probe --kind cuda-device-properties", text)
        self.assertNotIn("examples/job-scripts/hardware-probe.slurm", text)
        self.assertNotIn("examples/probe-results", text)
        self.assertIn("summary.env", text)
        self.assertIn("lscpu.txt", text)
        self.assertIn("numactl-hardware.txt", text)
        self.assertIn("intel-mlc-bandwidth.txt", text)
        self.assertIn("CUDA Device-Property Probe", text)
        self.assertIn("cuda-device-properties-<host>-<jobid>", text)
        self.assertIn("device-properties.txt", text)
        self.assertIn("L2 cache", text)
        self.assertIn("shared-memory limits", text)
        self.assertIn("hpc submissions mark-collected", text)
        self.assertIn("hpc submissions mark-analysed", text)
        self.assertIn("hpc submissions close", text)
        self.assertIn("hpc status", text)
        self.assertIn("Do not edit `submissions.sqlite3` directly", text)
        self.assertIn("superseded reason", text)

    def test_cluster_discovery_skill_covers_slurm_limits(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-discovery" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("hpc --profile <profile> slurm-limits --cluster <cluster>", text)
        self.assertIn("MaxSubmitJobsPU", text)
        self.assertIn("--partition <partition> --qos <qos>", text)
        self.assertIn("MaxArraySize", text)
        self.assertIn("--array=0-<N-1>", text)

    def test_slurm_job_skill_covers_dmtcp_for_long_jobs(self) -> None:
        text = (ROOT / "skills" / "hpc-slurm-jobs" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        shared = (ROOT / "skills" / "_shared" / "hpc-slurm-concepts.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Long Jobs and Checkpointing", text)
        self.assertIn("hpc --profile <profile> module-spider DMTCP", text)
        self.assertIn("small\npilot job on the target partition", text)
        self.assertIn("MPI, accelerator, licensed, networked", text)
        self.assertIn("Long Runtime and Checkpointing", shared)
        self.assertIn("DMTCP", shared)

    def test_cluster_onboarding_skill_guides_first_run_collection(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-onboarding" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Verify Codex Plugin and CLI Installation", text)
        self.assertIn("Codex Plugin Installation", text)
        self.assertIn("register_personal_marketplace.py", text)
        self.assertIn("codex plugin add hpc-tools@personal", text)
        self.assertIn("update_plugin_cachebuster.py", text)
        self.assertIn("start a new Codex thread", text)
        self.assertIn("create_basic_plugin.py --force", text)
        self.assertIn("CLI Installation", text)
        self.assertIn("command -v hpc", text)
        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
        self.assertIn("MCP Installation", text)
        self.assertIn("command -v hpc-mcp", text)
        self.assertIn('uv pip install -e ".[mcp]"', text)
        self.assertIn("guarded structured interface", text)
        self.assertIn("Local writes and remote installs require", text)
        self.assertIn("hpc_quote_job", text)
        self.assertIn("hpc_validate_job", text)
        self.assertIn("hpc_submit_job", text)
        self.assertIn("rejects stale or dry-run", text)
        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("hardware_reference", text)
        self.assertIn("Establish a Minimal Profile", text)
        self.assertIn("hpc --profile <profile> doctor", text)
        self.assertIn("hpc --profile <profile> storage inspect .", text)
        self.assertIn("hpc --profile <profile> site-env", text)
        self.assertIn("slurm-limits", text)
        self.assertIn("--cluster <cluster> --partition <partition>", text)
        self.assertIn("--partition <partition> --qos <qos>", text)
        self.assertIn("install-hardware-probe", text)
        self.assertIn("install-probe --kind hardware", text)
        self.assertIn("write-probe --kind hardware", text)
        self.assertIn("install-probe --kind cuda-device-properties", text)
        self.assertIn("cuda-device-properties-<host>-<jobid>", text)
        self.assertIn("CUDA cache sizes", text)
        self.assertIn("hpc submissions mark-collected", text)
        self.assertIn("hpc submissions close", text)
        self.assertIn("do not update the local SQLite\nsubmission database by hand", text)
        self.assertIn("superseded reason", text)
        self.assertIn("Completion Criteria", text)

    def test_routing_documents_mcp_agent_interface(self) -> None:
        text = ROUTING.read_text(encoding="utf-8")

        self.assertIn("MCP Versus CLI", text)
        self.assertIn("Prefer MCP when an agent needs structured", text)
        self.assertIn("The MCP server is the structured agent\ninterface", text)
        self.assertIn("Prefer the CLI when a human is actively operating", text)
        self.assertIn("hpc-mcp", text)
        self.assertIn("confirm-gated", text)
        self.assertIn("hpc_quote_job", text)
        self.assertIn("hpc_validate_job", text)
        self.assertIn("hpc_submit_job", text)
        self.assertIn("stale or dry-run quote/validation evidence", text)
