from __future__ import annotations

from test_plugin_fixtures import *


class PluginFeatureTests(unittest.TestCase):
    def test_builtin_r_plugin_is_discoverable(self) -> None:
        plugins = plugin_system.load_plugins()
        names = [plugin.name for plugin in plugins]

        self.assertIn("benchmark", names)
        self.assertIn("r", names)
        self.assertIn("python", names)

    def test_benchmark_summarize_and_compare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "baseline.csv").write_text("seconds\n10\n12\n14\n", encoding="utf-8")
            (root / "candidate.csv").write_text("seconds\n5\n6\n7\n", encoding="utf-8")

            baseline = benchmark_support.summarize_target(root / "baseline.csv")
            candidate = benchmark_support.summarize_target(root / "candidate.csv")
            summarize_args = type("Args", (), {"targets": [root], "json": False})()
            compare_args = type(
                "Args",
                (),
                {"baseline": root / "baseline.csv", "candidate": root / "candidate.csv", "candidate_threads": 2, "json": False},
            )()

            summarize_stdout = io.StringIO()
            compare_stdout = io.StringIO()
            with contextlib.redirect_stdout(summarize_stdout):
                summarize_rc = benchmark_support.cmd_benchmark_summarize(summarize_args, None)
            with contextlib.redirect_stdout(compare_stdout):
                compare_rc = benchmark_support.cmd_benchmark_compare(compare_args, None)

        self.assertEqual(baseline.count, 3)
        self.assertEqual(candidate.count, 3)
        self.assertAlmostEqual(baseline.mean, 12.0)
        self.assertAlmostEqual(candidate.mean, 6.0)
        self.assertEqual(summarize_rc, 0)
        self.assertEqual(compare_rc, 0)
        self.assertIn("baseline.csv", summarize_stdout.getvalue())
        self.assertIn("candidate.csv", summarize_stdout.getvalue())
        self.assertIn("SOURCES", summarize_stdout.getvalue())
        self.assertIn("speedup: 2", compare_stdout.getvalue())

    def test_benchmark_json_is_native_and_missing_input_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.csv"
            path.write_text("seconds\n10\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = benchmark_support.cmd_benchmark_summarize(
                    type("Args", (), {"targets": [path], "json": True})(),
                    None,
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(rc, 0)
        self.assertIn("summaries", payload)
        self.assertNotIn("stdout", payload)

        with self.assertRaises(ConfigError):
            benchmark_support.summarize_target(Path("/tmp/does-not-exist.csv"))

    def test_benchmark_compare_rejects_non_positive_threads(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args([
                "benchmark",
                "compare",
                "/tmp/a",
                "/tmp/b",
                "--candidate-threads",
                "0",
            ])

