from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE_SCRIPT = ROOT / "examples" / "job-scripts" / "hardware-probe.slurm"
PARTITION_REPORT = ROOT / "examples" / "references" / "slurm-partition-discovery-report.md"
WICE_HARDWARE_REPORT = ROOT / "examples" / "references" / "wice-probe-hardware-report.md"
SHARED_REMOTE_ACCESS = ROOT / "skills" / "_shared" / "hpc-tools-remote-access.md"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
SKILLS = [
    "hpc-cluster-onboarding",
    "hpc-cluster-discovery",
    "hpc-deploy-build",
    "hpc-filesystem-environment",
    "hpc-slurm-jobs",
]


class SkillTests(unittest.TestCase):
    def test_skills_have_required_frontmatter(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                path = ROOT / "skills" / skill / "SKILL.md"
                self.assertTrue(path.exists(), f"missing {path}")
                frontmatter = self._frontmatter(path)
                self.assertEqual(frontmatter.get("name"), skill)
                self.assertIn("description", frontmatter)
                self.assertTrue(frontmatter["description"])

    def test_domain_skills_reference_shared_remote_access(self) -> None:
        self.assertTrue(SHARED_REMOTE_ACCESS.exists(), f"missing {SHARED_REMOTE_ACCESS}")
        shared = SHARED_REMOTE_ACCESS.read_text(encoding="utf-8")
        self.assertIn("hpc --profile <profile> run '<command>'", shared)
        self.assertIn("--dry-run", shared)
        self.assertIn("login-gate", shared)

        for skill in SKILLS:
            with self.subTest(skill=skill):
                text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("../_shared/hpc-tools-remote-access.md", text)

    def test_skills_do_not_hardcode_site_specific_commands_or_paths(self) -> None:
        forbidden = [
            "ssh genius",
            "$VSC_DATA",
            "myquota",
            "slurm_queuestate",
            "wice",
            "mindwell",
        ]
        for skill in SKILLS:
            with self.subTest(skill=skill):
                text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                for pattern in forbidden:
                    self.assertNotIn(pattern, text)

    def test_slurm_skill_marks_account_directive_optional(self) -> None:
        text = (ROOT / "skills" / "hpc-slurm-jobs" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("do not assume `#SBATCH --account=...` is required", text)
        self.assertIn("omit unless the site requires an account", text)

    def test_storage_reference_warns_about_nfs_for_parallel_io(self) -> None:
        text = (ROOT / "examples" / "references" / "kuleuven-tier2-storage.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Use SCRATCH filesystems for jobs with parallel I/O", text)
        self.assertIn("NFS-mounted", text)
        self.assertIn("GPFS", text)
        self.assertIn("Local scratch is node-local SSD or NVMe storage", text)
        self.assertIn("stage input data into local scratch", text)
        self.assertIn("VSC_SCRATCH_NODE", text)
        self.assertIn("not reserved or managed by the scheduler", text)
        self.assertIn("each job gets its own directory", text)
        self.assertIn("traps or periodic checkpoint/stage-out", text)

    def test_hardware_reference_uses_usable_local_scratch_capacities(self) -> None:
        text = (ROOT / "examples" / "references" / "kuleuven-tier2-hardware.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("600 GB usable on a 960 GB", text)
        self.assertIn("approximately 3500 GB usable on a 3840 GB", text)

    def test_hardware_probe_collects_cache_and_topology_information(self) -> None:
        text = PROBE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("lscpu --cache", text)
        self.assertIn("/sys/devices/system/cpu/cpu*/cache/index*", text)
        self.assertIn("shared_cpu_list", text)
        self.assertIn("numactl --hardware", text)
        self.assertIn("lstopo-no-graphics", text)
        self.assertIn("mlc --bandwidth_matrix", text)
        self.assertIn("mlc --latency_matrix", text)
        self.assertIn("#SBATCH --time=00:20:00", text)
        self.assertIn("#SBATCH --exclusive", text)
        self.assertIn("--cpus-per-task value equal to the full node core count", text)
        self.assertIn("MLC measurements can take several minutes", text)

    def test_cluster_discovery_skill_uses_probe_artifacts(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-discovery" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("examples/job-scripts/hardware-probe.slurm", text)
        self.assertNotIn("examples/probe-results", text)
        self.assertIn("summary.env", text)
        self.assertIn("lscpu.txt", text)
        self.assertIn("numactl-hardware.txt", text)
        self.assertIn("intel-mlc-bandwidth.txt", text)

    def test_cluster_discovery_skill_covers_slurm_limits(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-discovery" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("scontrol -M <cluster> show partition <partition>", text)
        self.assertIn("MaxSubmitJobsPU", text)
        self.assertIn("sacctmgr -n -P show assoc", text)
        self.assertIn("MaxArraySize", text)
        self.assertIn("--array=0-<N-1>", text)

    def test_cluster_onboarding_skill_guides_first_run_collection(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-onboarding" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Verify Local Installation", text)
        self.assertIn("command -v hpc", text)
        self.assertIn("python3 -m pip install --user .", text)
        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("hardware_reference", text)
        self.assertIn("Establish a Minimal Profile", text)
        self.assertIn("sinfo -a", text)
        self.assertIn("scontrol show partition", text)
        self.assertIn("sacctmgr -n -P show assoc", text)
        self.assertIn("examples/job-scripts/hardware-probe.slurm", text)
        self.assertIn("Completion Criteria", text)

    def test_readme_installs_without_repo_dependency(self) -> None:
        text = README.read_text(encoding="utf-8")

        self.assertIn("python3 -m pip install --user .", text)
        self.assertIn("Use an editable install only when developing", text)
        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("cp -R skills/hpc-cluster-onboarding", text)
        self.assertNotIn("ln -s /home", text)

    def test_agents_guidance_routes_hpc_workflows(self) -> None:
        text = AGENTS.read_text(encoding="utf-8")

        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("python3 -m pip install --user .", text)
        self.assertIn("not\n  by symlinking", text)
        self.assertIn("hpc-cluster-onboarding", text)
        self.assertIn("hpc-cluster-discovery", text)
        self.assertIn("python3 -m unittest discover -s tests", text)

    def test_partition_discovery_report_is_reusable(self) -> None:
        text = PARTITION_REPORT.read_text(encoding="utf-8")

        self.assertIn("Report: wice batch_icelake", text)
        self.assertIn("MaxSubmitJobsPU", text)
        self.assertIn("MaxArraySize", text)
        self.assertIn("hpc --profile <profile> run", text)
        self.assertIn("Interpretation Checklist", text)

    def test_wice_hardware_report_summarizes_probe_results(self) -> None:
        text = WICE_HARDWARE_REPORT.read_text(encoding="utf-8")

        self.assertIn("wICE Probe Hardware Report", text)
        self.assertIn("batch_icelake", text)
        self.assertIn("bigmem", text)
        self.assertIn("hugemem", text)
        self.assertIn("Intel Xeon Platinum 8360Y", text)
        self.assertIn("NUMA", text)
        self.assertIn("600 GB", text)

    def _frontmatter(self, path: Path) -> dict[str, str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "---")
        closing = lines.index("---", 1)
        fields = {}
        for line in lines[1:closing]:
            key, separator, value = line.partition(":")
            self.assertEqual(separator, ":", f"invalid frontmatter line in {path}: {line}")
            fields[key.strip()] = value.strip()
        return fields


if __name__ == "__main__":
    unittest.main()
