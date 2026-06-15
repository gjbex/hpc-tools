from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE_SCRIPT = ROOT / "examples" / "job-scripts" / "hardware-probe.slurm"
PARTITION_REPORT = ROOT / "examples" / "references" / "slurm-partition-discovery-report.md"
WICE_HARDWARE_REPORT = ROOT / "examples" / "references" / "wice-probe-hardware-report.md"
SHARED_REMOTE_ACCESS = ROOT / "skills" / "_shared" / "hpc-tools-remote-access.md"
SHARED_CONCEPTS = {
    "hpc-accounting-safety.md": [
        "Quote Before Submit",
        "A quote becomes stale",
        "ask which account to use",
    ],
    "hpc-benchmark-methodology.md": [
        "Benchmark Contract",
        "parallel efficiency",
        "speedup(p) = T1 / Tp",
    ],
    "hpc-slurm-concepts.md": [
        "Partition, QoS, and Submit Limits",
        "MaxSubmitJobsPU",
        "--array=0-<N-1>",
    ],
    "hpc-storage-io.md": [
        "Node-Local Scratch",
        "Shared Filesystem Search Hygiene",
        "VSC_SCRATCH",
    ],
}
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
SUBMISSIONS_DOC = ROOT / "docs" / "submissions.md"
SKILLS = [
    "hpc-cluster-onboarding",
    "hpc-cluster-discovery",
    "hpc-deploy-build",
    "hpc-filesystem-environment",
    "hpc-r-packages",
    "hpc-slurm-jobs",
    "hpc-slurm-job-arrays",
    "hpc-slurm-benchmark",
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
        self.assertIn("cuda-device-properties.slurm", text)
        self.assertIn("device-properties.txt", text)
        self.assertIn("mark-collected", text)
        self.assertIn("hpc --profile <profile> job <jobid> --cluster <cluster>", text)
        self.assertNotIn("squeue -M <cluster> -j <jobid>", text)

    def test_slurm_benchmark_skill_covers_quote_and_efficiency(self) -> None:
        text = (ROOT / "skills" / "hpc-slurm-benchmark" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("parallel efficiency", text)
        self.assertIn("quote the exact job", text)
        self.assertIn("A quote becomes stale", text)
        self.assertIn("pilot-first", text)
        self.assertIn("OMP_NUM_THREADS=1", text)
        self.assertIn("speedup(p) = T1 / Tp", text)
        self.assertIn("transfer compact artifacts locally", text)
        self.assertIn("--validate-first", text)
        self.assertIn("hpc submissions list", text)
        self.assertIn("superseded benchmark attempts", text)
        self.assertIn("CUDA device-property probe fails", text)
        self.assertIn("cmake-build.txt", text)
        self.assertIn("hpc --profile <profile> job <jobid> --cluster <cluster>", text)
        self.assertNotIn("squeue -M <cluster> -j <jobid>", text)

    def test_slurm_job_arrays_skill_covers_atools_resume_and_io_hygiene(self) -> None:
        text = (ROOT / "skills" / "hpc-slurm-job-arrays" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("atools", text)
        self.assertIn("aenv", text)
        self.assertIn("alog", text)
        self.assertIn("arange", text)
        self.assertIn("areduce", text)
        self.assertIn("aload", text)
        self.assertIn("SLURM_ARRAY_TASK_ID", text)
        self.assertIn("SLURM_ARRAY_TASK_STEP", text)
        self.assertIn("--array=1-2000:25%20", text)
        self.assertIn("source <(aenv --data params.csv)", text)
        self.assertIn("subshell", text)
        self.assertIn("zero-based indexing", text)
        self.assertIn("MaxArraySize", text)
        self.assertIn("MaxSubmitJobsPU", text)
        self.assertIn("hpc --profile <profile> slurm-limits --cluster <cluster>", text)
        self.assertIn("hpc slurm-limits", text)
        self.assertIn("--array=0-<N-1>", text)
        self.assertIn("submit-job limits", text)
        self.assertIn("roughly 30 minutes or more", text)
        self.assertIn("--array=1-200%5", text)
        self.assertIn("--validate-first", text)
        self.assertIn("pilot-first", text)
        self.assertIn("hpc submissions list", text)
        self.assertIn("rerun only the necessary task IDs", text)
        self.assertIn("hpc --profile <profile> job <jobid> --cluster <cluster>", text)
        self.assertNotIn("squeue -M <cluster> -j <jobid>", text)

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
        self.assertIn("Do not edit `submissions.jsonl` directly", text)
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

    def test_cluster_onboarding_skill_guides_first_run_collection(self) -> None:
        text = (ROOT / "skills" / "hpc-cluster-onboarding" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Verify Local Installation", text)
        self.assertIn("command -v hpc", text)
        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
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
        self.assertIn("do not update the local JSONL\nsubmission log by hand", text)
        self.assertIn("superseded reason", text)
        self.assertIn("Completion Criteria", text)

    def test_readme_installs_without_repo_dependency(self) -> None:
        text = README.read_text(encoding="utf-8")

        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
        self.assertIn("Use an editable install only when developing", text)
        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("cp -R skills/hpc-cluster-onboarding", text)
        self.assertIn("cp -R skills/hpc-slurm-job-arrays", text)
        self.assertIn("hpc plugins list", text)
        self.assertIn("hpc doctor", text)
        self.assertIn("hpc site-env", text)
        self.assertIn("hpc storage inspect", text)
        self.assertIn("hpc repo status --directory", text)
        self.assertIn("hpc r scan", text)
        self.assertIn("hpc --profile genius r check", text)
        self.assertIn("hpc job 123456 --cluster wice", text)
        self.assertIn("hpc slurm-limits --cluster wice --partition batch", text)
        self.assertIn("hpc clone https://github.com/org/repo.git --branch main --directory", text)
        self.assertIn("hpc submit --validate-first", text)
        self.assertIn("hpc paths", text)
        self.assertIn("docs/submissions.md", text)
        self.assertIn("hpc write-probe --kind hardware", text)
        self.assertIn("hpc install-probe --kind cuda-device-properties", text)
        self.assertIn("hpc_tools/data/cuda-device-properties.slurm", text)
        self.assertIn("hpc_tools/data/cuda/", text)
        self.assertIn("pipx uninstall hpc-tools", text)
        self.assertNotIn("ln -s /home", text)

    def test_agents_guidance_routes_hpc_workflows(self) -> None:
        text = AGENTS.read_text(encoding="utf-8")

        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
        self.assertIn("hpc_tools.plugins", text)
        self.assertIn("not\n  by symlinking", text)
        self.assertIn("hpc paths", text)
        self.assertIn("hpc-cluster-onboarding", text)
        self.assertIn("hpc-cluster-discovery", text)
        self.assertIn("hpc-r-packages", text)
        self.assertIn("hpc-slurm-job-arrays", text)
        self.assertIn("hpc-slurm-benchmark", text)
        self.assertIn("python3 -m unittest discover -s tests", text)

    def test_r_packages_skill_uses_architecture_aware_library_guidance(self) -> None:
        text = (ROOT / "skills" / "hpc-r-packages" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("${VSC_DATA}/Rlibs/${VSC_OS_LOCAL}/${VSC_ARCH_LOCAL}/R-${EBVERSIONR}", text)
        self.assertIn("compiled dependencies", text)
        self.assertIn("same node class", text)
        self.assertIn("exact R module and bundle modules used for verification", text)
        self.assertIn("Do not suggest a generic `R_LIBS_USER` path", text)

    def test_r_packages_skill_checks_bundle_modules_before_installing(self) -> None:
        text = (ROOT / "skills" / "hpc-r-packages" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("R-bundle-CRAN", text)
        self.assertIn("R-bundle-Bioconductor", text)
        self.assertIn("requireNamespace()", text)
        self.assertIn("hpc r scan", text)
        self.assertIn("hpc --profile <profile> r check", text)
        self.assertIn("hpc --profile <profile> r plan-install", text)
        self.assertIn("module-spider R", text)
        self.assertIn("module-spider R-bundle-CRAN", text)
        self.assertIn("module-spider R-bundle-Bioconductor", text)
        self.assertIn("rg -n 'library\\\\(|require\\\\(|requireNamespace\\\\('", text)
        self.assertIn("missing and likely requiring user installation", text)
        self.assertIn("SystemRequirements", text)
        self.assertIn("module-spider JAGS", text)
        self.assertIn("JAGS-related R packages", text)
        self.assertIn("runtime contract", text)

    def test_r_packages_skill_covers_compute_node_install_workflow(self) -> None:
        text = (ROOT / "skills" / "hpc-r-packages" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Compute-Node Install Workflow", text)
        self.assertIn("pilot-first", text)
        self.assertIn("hpc submit --validate-first", text)
        self.assertIn("non-R system dependency modules", text)
        self.assertIn("VSC_ARCH_LOCAL", text)
        self.assertIn(".libPaths()", text)
        self.assertIn("sessionInfo()", text)
        self.assertIn("archive-only", text)
        self.assertIn("archived tarball", text)
        self.assertIn("requireNamespace()", text)

    def test_partition_discovery_report_is_reusable(self) -> None:
        text = PARTITION_REPORT.read_text(encoding="utf-8")

        self.assertIn("Report: wice batch_icelake", text)
        self.assertIn("MaxSubmitJobsPU", text)
        self.assertIn("MaxArraySize", text)
        self.assertIn("hpc --profile <profile> slurm-limits --cluster <cluster>", text)
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

    def test_submissions_doc_covers_action_semantics_and_diagram(self) -> None:
        text = SUBMISSIONS_DOC.read_text(encoding="utf-8")

        self.assertIn("Submission Log Workflow", text)
        self.assertIn("STATE", text)
        self.assertIn("ACTION", text)
        self.assertIn("triage", text)
        self.assertIn("collect", text)
        self.assertIn("analyse", text)
        self.assertIn("closed", text)
        self.assertIn("stateDiagram-v2", text)
        self.assertIn("append-only", text)

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
