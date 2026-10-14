from __future__ import annotations

from test_skill_fixtures import *


class SkillFeatureTests(SkillFixtures, unittest.TestCase):
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
        self.assertIn("hpc benchmark summarize", text)
        self.assertIn("hpc benchmark compare", text)
        self.assertIn("--validate-first", text)
        self.assertIn("hpc --profile <profile> submissions list", text)
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
        self.assertIn("hpc --profile <profile> submissions list", text)
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

    def test_container_workflows_skill_covers_hpccm_regeneration_and_job_builds(self) -> None:
        text = (ROOT / "skills" / "hpc-container-workflows" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("hpccm", text)
        self.assertIn("must be regenerated before each build", text)
        self.assertIn("Apptainer definition-file workflows", text)
        self.assertIn("hpc write-container --kind generic", text)
        self.assertIn("hpc install-container --kind generic", text)
        self.assertIn("build in a Slurm job", text)
        self.assertIn("pilot job first", text)

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
        self.assertIn("Container Fallback", text)
        self.assertIn("Apptainer container", text)

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

    def test_python_packages_skill_uses_venv_layered_on_site_modules(self) -> None:
        text = (ROOT / "skills" / "hpc-python-packages" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("hpc python scan", text)
        self.assertIn("hpc python inspect-deps", text)
        self.assertIn("docs.vscentrum.be/compute/software/installing_software/python_package_management.html", text)
        self.assertIn("hpc --profile <profile> python check", text)
        self.assertIn("hpc --profile <profile> python plan-install", text)
        self.assertIn("`hpc python plan-install` consumes the same dependency-file inspection", text)
        self.assertIn("Conda dependencies from `environment.yml` are reported as notes", text)
        self.assertIn("module-spider Python", text)
        self.assertIn("Python-bundle-PyPI", text)
        self.assertIn("SciPy-bundle", text)
        self.assertIn("python3 -m pip list -v", text)
        self.assertIn("Requirements Files", text)
        self.assertIn("channels, Python version pins, and likely binary/runtime dependencies", text)
        self.assertIn("treat it as the dependency source of\ntruth", text)
        self.assertIn("do not blindly turn it into\n`pip install -r requirements.txt`", text)
        self.assertIn("install only the packages still missing into the venv", text)
        self.assertIn("splitting requirements into site-provided dependencies", text)
        self.assertIn("Conda Environment Files", text)
        self.assertIn("do not automatically run `conda env create -f\nenvironment.yml`", text)
        self.assertIn("nested `pip:` entries", text)
        self.assertIn("Use conda or micromamba only when the YAML depends on conda-specific packages", text)
        self.assertIn("install into project/data storage rather\nthan home", text)
        self.assertIn("Package/Import Name Mismatches", text)
        self.assertIn("`scikit-learn` -> `sklearn`", text)
        self.assertIn("Use the package name for pip install planning", text)
        self.assertIn("--package <import-name>", text)
        self.assertIn("importlib.util.find_spec()", text)
        self.assertIn("--system-site-packages", text)
        self.assertIn("mmh3", text)
        self.assertIn("Avoid `pip install --user`", text)
        self.assertIn("--no-cache-dir", text)
        self.assertIn("--no-build-isolation", text)
        self.assertIn("runtime contract", text)
        self.assertIn("Venv Location", text)
        self.assertIn("create the venv inside\nthat project tree", text)
        self.assertIn("ask the user where the venv should live", text)
        self.assertIn("Do not guess between home, scratch, data, and project storage", text)
        self.assertIn("Do not put project-specific venvs under `~/.config/hpc-tools`", text)
        self.assertIn("Architecture-Specific Environments", text)
        self.assertIn("${VSC_ARCH_LOCAL}", text)
        self.assertIn("create a separate\nvenv for each architecture", text)
        self.assertIn("optionally a\n`modules.txt` file", text)
        self.assertIn("use those files as evidence for the module stack and pip\ndependencies", text)
        self.assertIn("`uv` module", text)
        self.assertIn("Runtime Job Snippet", text)
        self.assertIn("Load modules before activating the venv", text)
        self.assertIn("Compute-Node Install Workflow", text)
        self.assertIn("install involves many\npackages", text)
        self.assertIn("Login nodes often have process runtime limits", text)
        self.assertIn("affects other users", text)
        self.assertIn("Keep\nlogin-node installs for small, quick, pure-Python additions only", text)
        self.assertIn("pilot-first", text)
        self.assertIn("quote the pilot job", text)
        self.assertIn("Native Extension Build Requirements", text)
        self.assertIn("module-spider <dependency>", text)
        self.assertIn("Load compiler, CMake, CUDA, MPI, HDF5, GDAL", text)
        self.assertIn("Container Fallback", text)
        self.assertIn("Apptainer", text)
        self.assertIn("Reproducibility Capture", text)
        self.assertIn("python -m pip freeze", text)
        self.assertIn("sys.path", text)
