from __future__ import annotations

from test_skill_fixtures import *


class SkillFeatureTests(SkillFixtures, unittest.TestCase):
    def test_plugin_manifest_declares_mcp_server_companion(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        mcp_config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(
            mcp_config["mcpServers"]["hpc-tools"],
            {"command": "hpc-mcp", "args": []},
        )

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
        self.assertIn("hpc --profile <profile> capabilities", shared)
        self.assertIn("remote-shell.execute", shared)
        self.assertIn("automatic workaround for a denial", shared)
        self.assertIn("--dry-run", shared)
        self.assertIn("login-gate", shared)

        for skill in SKILLS:
            with self.subTest(skill=skill):
                text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("../_shared/hpc-tools-remote-access.md", text)

    def test_agents_guidance_routes_hpc_workflows(self) -> None:
        text = AGENTS.read_text(encoding="utf-8")

        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
        self.assertIn("hpc_tools.plugins", text)
        self.assertIn("hpc-mcp", text)
        self.assertIn("structured agent interface", text)
        self.assertIn(".mcp.json", text)
        self.assertIn("Python package's `hpc-mcp` console script", text)
        self.assertIn("confirm-gated local writes", text)
        self.assertIn("hpc_quote_job", text)
        self.assertIn("hpc_submit_job", text)
        self.assertIn("profile-reference, reference-set", text)
        self.assertIn("not\n  by symlinking", text)
        self.assertIn("hpc paths", text)
        self.assertIn("hpc-cluster-onboarding", text)
        self.assertIn("hpc-tools Codex\n  plugin", text)
        self.assertIn("local `hpc` CLI verification", text)
        self.assertIn("hpc-cluster-discovery", text)
        self.assertIn("hpc-r-packages", text)
        self.assertIn("hpc-python-packages", text)
        self.assertIn("hpc-container-workflows", text)
        self.assertIn("hpc-slurm-job-arrays", text)
        self.assertIn("hpc-slurm-benchmark", text)
        self.assertIn("uv run --locked --no-sync python -m unittest discover -s tests", text)
