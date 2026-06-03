from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = [
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
