from __future__ import annotations

from test_plugin_fixtures import *


class PluginFeatureTests(unittest.TestCase):
    def test_cxx_scan_detects_cmake_and_header_dependency_hints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CMakeLists.txt").write_text(
                """cmake_minimum_required(VERSION 3.24)
project(demo LANGUAGES CXX)
find_package(MPI REQUIRED)
find_package(HDF5 CONFIG REQUIRED)
find_package(CLI11 CONFIG QUIET)
""",
                encoding="utf-8",
            )
            (root / "main.cpp").write_text(
                "#include <CLI/CLI.hpp>\n#include <nlohmann/json.hpp>\n",
                encoding="utf-8",
            )

            result = cxx_support.scan_target(root)

        dependencies = {finding.name: finding for finding in result.dependencies}
        self.assertIn("MPI", dependencies)
        self.assertIn("HDF5", dependencies)
        self.assertIn("CLI11", dependencies)
        self.assertIn("nlohmann_json", dependencies)
        self.assertTrue(dependencies["MPI"].hpc_sensitive)
        self.assertTrue(dependencies["HDF5"].hpc_sensitive)
        self.assertTrue(dependencies["CLI11"].fetchcontent_candidate)
        self.assertTrue(dependencies["nlohmann_json"].fetchcontent_candidate)
        self.assertTrue(any("HPC-sensitive" in note for note in result.notes))

    def test_cxx_scan_command_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CMakeLists.txt").write_text("find_package(OpenMP REQUIRED)\n", encoding="utf-8")
            args = type("Args", (), {"target": root, "json": True})()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cxx_support.cmd_cxx_scan(args, None)

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["dependencies"][0]["name"], "OpenMP")
        self.assertTrue(payload["dependencies"][0]["hpc_sensitive"])

    def test_cxx_fetchcontent_renders_pinned_cli11_snippet(self) -> None:
        package = cxx_support.fetchcontent_package("CLI11")
        snippet = cxx_support.render_fetchcontent_snippet(
            package,
            project_option_prefix="DEMO",
            default_on=False,
        )

        self.assertIn("option(DEMO_FETCH_CLI11", snippet)
        self.assertIn("OFF)", snippet)
        self.assertIn("find_package(CLI11 CONFIG QUIET)", snippet)
        self.assertIn("GIT_REPOSITORY https://github.com/CLIUtils/CLI11.git", snippet)
        self.assertIn("GIT_TAG v2.4.2", snippet)
        self.assertIn("target_link_libraries(<target> PRIVATE CLI11::CLI11)", snippet)

    def test_cxx_fetchcontent_command_rejects_unknown_package(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unsupported FetchContent package"):
            cxx_support.fetchcontent_package("PETSc")
