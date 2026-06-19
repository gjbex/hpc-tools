from __future__ import annotations

import json
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
ROUTING = ROOT / "ROUTING.md"
SUBMISSIONS_DOC = ROOT / "docs" / "submissions.md"
SKILLS = [
    "hpc-container-workflows",
    "hpc-cluster-onboarding",
    "hpc-cluster-discovery",
    "hpc-deploy-build",
    "hpc-filesystem-environment",
    "hpc-python-packages",
    "hpc-r-packages",
    "hpc-slurm-jobs",
    "hpc-slurm-job-arrays",
    "hpc-slurm-benchmark",
]


class SkillFixtures:
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


__all__ = [name for name in globals() if not name.startswith("__")]
