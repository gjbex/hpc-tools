from __future__ import annotations

import re
import tempfile

from hpc_tools.config import load_config
from test_skill_fixtures import *


class SkillFeatureTests(SkillFixtures, unittest.TestCase):
    def test_user_documentation_includes_reference_and_project_information(self) -> None:
        navigation = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("reference.md", navigation)
        self.assertIn("project-information.md", navigation)

        reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
        self.assertIn("## Complete CLI command reference", reference)
        self.assertIn("## Configuration schema", reference)
        self.assertIn("## Submission-database format", reference)
        self.assertIn("## Reference-set manifest format", reference)
        self.assertIn("hpc_quote_job → hpc_validate_job → hpc_submit_job", reference)
        self.assertIn("Unknown keys within `capabilities`", reference)
        self.assertIn("spacing or headings as a stable machine API", reference)

    def test_documented_profile_toml_uses_the_accepted_capability_schema(self) -> None:
        documents = [README, ROOT / "capabilities.md", *(ROOT / "docs").glob("*.md")]
        checked = 0
        for document in documents:
            text = document.read_text(encoding="utf-8")
            for index, block in enumerate(
                re.findall(r"```toml\n(.*?)\n```", text, flags=re.DOTALL),
                start=1,
            ):
                if not re.search(r"^\s*\[profiles\.", block, flags=re.MULTILINE):
                    continue
                with self.subTest(document=document.name, block=index):
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "config.toml"
                        path.write_text(block, encoding="utf-8")
                        load_config(str(path))
                checked += 1
        self.assertGreaterEqual(checked, 15)

        project_information = (ROOT / "docs" / "project-information.md").read_text(encoding="utf-8")
        self.assertIn("## Current limitations and deliberate non-features", project_information)
        self.assertIn("no published operating-system or Slurm-version support matrix", project_information)
        self.assertIn("does not currently publish a formal backward-compatibility policy", project_information)
        self.assertIn("no published `SECURITY.md`", project_information)
        self.assertIn("contains no `LICENSE` file", project_information)

    def test_user_documentation_includes_agent_recipes_and_troubleshooting(self) -> None:
        navigation = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        for page in ("codex.md", "mcp.md", "recipes.md", "troubleshooting.md"):
            self.assertIn(page, navigation)

        codex = (ROOT / "docs" / "codex.md").read_text(encoding="utf-8")
        self.assertIn("does not store", codex)
        self.assertIn("default Slurm account", codex)
        self.assertIn("scientific-computing-skills", codex)

        mcp = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
        self.assertIn("hpc_quote_job → hpc_validate_job → hpc_submit_job", mcp)
        self.assertIn("currently has no maximum-age check", mcp)
        self.assertIn("not a hash of its contents", mcp)
        self.assertIn("confirm=true", mcp)
        self.assertIn("dry_run=false", mcp)

        recipes = (ROOT / "docs" / "recipes.md").read_text(encoding="utf-8")
        self.assertIn("## Execute a resumable parameter sweep", recipes)
        self.assertIn("## Resume unfinished work after a restart", recipes)

        troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        self.assertIn("## SSH works interactively but not through hpc-tools", troubleshooting)
        self.assertIn("## MCP cannot start or expose tools", troubleshooting)

    def test_pages_deployment_publishes_only_the_mkdocs_site(self) -> None:
        workflows = ROOT / ".github" / "workflows"
        deployment_workflows = []
        for path in workflows.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if "actions/deploy-pages@" in text:
                deployment_workflows.append(path.name)

        self.assertEqual(deployment_workflows, ["docs-deploy.yml"])

        deployment = (workflows / "docs-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("mkdocs build --strict", deployment)
        self.assertIn("path: site", deployment)

    def test_readme_installs_without_repo_dependency(self) -> None:
        text = README.read_text(encoding="utf-8")

        self.assertIn("pipx install hpc-tools", text)
        self.assertIn("pipx install .", text)
        self.assertIn("Use an editable install only when developing", text)
        self.assertIn("~/.config/hpc-tools/profiles/<profile>/", text)
        self.assertIn("cp -R skills/hpc-cluster-onboarding", text)
        self.assertIn("cp -R skills/hpc-slurm-job-arrays", text)
        self.assertIn("hpc plugins list", text)
        self.assertIn("hpc plugins info benchmark", text)
        self.assertIn("hpc-mcp", text)
        self.assertIn('uv pip install -e ".[mcp]"', text)
        self.assertIn("Run the server with", text)
        self.assertIn("guarded MCP interface", text)
        self.assertIn("plugin manifest points at `.mcp.json`", text)
        self.assertIn("install the Python package first", text)
        self.assertIn("confirm-gated write and install tools", text)
        self.assertIn("hpc_references_create", text)
        self.assertIn("hpc_install_container", text)
        self.assertIn("hpc_quote_job", text)
        self.assertIn("hpc_validate_job", text)
        self.assertIn("hpc_submit_job", text)
        self.assertIn("Stale or dry-run evidence is rejected", text)
        self.assertIn("hpc://profiles/{profile}/hardware", text)
        self.assertIn("active hpc-tools config tree", text)
        self.assertIn("hpc_status", text)
        self.assertIn("hpc_slurm_limits", text)
        self.assertIn("hpc_module_spider", text)
        self.assertIn("hpc doctor", text)
        self.assertIn("hpc site-env", text)
        self.assertIn("hpc storage inspect", text)
        self.assertIn("hpc repo status --directory", text)
        self.assertIn("hpc benchmark summarize", text)
        self.assertIn("hpc benchmark compare", text)
        self.assertIn("hpc cxx scan", text)
        self.assertIn("hpc cxx fetchcontent", text)
        self.assertIn("hpc r scan", text)
        self.assertIn("hpc python scan", text)
        self.assertIn("hpc python inspect-deps", text)
        self.assertIn("Apptainer container", text)
        self.assertIn("hpc write-container --kind generic", text)
        self.assertIn("hpc status", text)
        self.assertIn("hpc --profile genius r check", text)
        self.assertIn("hpc --profile genius python check", text)
        self.assertIn("hpc job 123456 --cluster wice", text)
        self.assertIn("hpc slurm-limits --cluster wice --partition batch", text)
        self.assertIn("hpc clone https://github.com/org/repo.git --branch main --directory", text)
        self.assertIn("hpc submit --validate-first", text)
        self.assertIn("hpc paths", text)
        self.assertIn("hpc status", text)
        self.assertIn("docs/submissions.md", text)
        self.assertIn("hpc write-probe --kind hardware", text)
        self.assertIn("hpc install-probe --kind cuda-device-properties", text)
        self.assertIn("hpc_tools/data/cuda-device-properties.slurm", text)
        self.assertIn("hpc_tools/data/cuda/", text)
        self.assertIn("pipx uninstall hpc-tools", text)
        self.assertNotIn("ln -s /home", text)

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

    def test_project_information_documents_submission_database_schema(self) -> None:
        text = (ROOT / "docs" / "project-information.md").read_text(encoding="utf-8")

        self.assertIn("### Submission database schema", text)
        self.assertIn("CREATE TABLE submission_events", text)
        self.assertIn("CREATE INDEX submission_events_by_run", text)
        self.assertIn("PRAGMA user_version = 1", text)
        self.assertIn("PRAGMA journal_mode = DELETE", text)
        self.assertIn("PRAGMA synchronous = FULL", text)
        self.assertIn("mode `0600`", text)
        delegation_text = (
            ROOT / "docs" / "delegation-development.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## Responsibility boundary", delegation_text)
        self.assertIn("## Delegation manifest", delegation_text)
        self.assertIn("## Reservation and budget semantics", delegation_text)
        self.assertIn("## Ledger schema", delegation_text)
        self.assertIn("submission_operations", delegation_text)
        self.assertIn("job_ownership", delegation_text)
        self.assertIn("lifecycle_operations", delegation_text)
        self.assertIn("## Restricted lifecycle authorization", delegation_text)
        mcp_text = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
        self.assertIn("hpc_job_accounting", mcp_text)
        self.assertIn("only ledger-owned active jobs", mcp_text)

    def test_submissions_doc_covers_action_semantics_and_diagram(self) -> None:
        text = SUBMISSIONS_DOC.read_text(encoding="utf-8")

        self.assertIn("Submission Database Workflow", text)
        self.assertIn("STATE", text)
        self.assertIn("ACTION", text)
        self.assertIn("triage", text)
        self.assertIn("collect", text)
        self.assertIn("analyse", text)
        self.assertIn("closed", text)
        self.assertIn("stateDiagram-v2", text)
        self.assertIn("append-only", text)

    def test_plugins_doc_mentions_container_fallback_for_large_stacks(self) -> None:
        text = (ROOT / "docs" / "plugins.md").read_text(encoding="utf-8")

        self.assertIn("Apptainer", text)
        self.assertIn("benchmark", text)
        self.assertIn("hpc benchmark summarize", text)
        self.assertIn("hpc benchmark compare", text)
        self.assertIn("hpc cxx scan", text)
        self.assertIn("hpc cxx fetchcontent", text)
        self.assertIn("HPC-sensitive dependencies", text)
        self.assertIn("batch-job startup load matters more than the", text)
        self.assertIn("instead of extending the same shared-filesystem install again", text)
