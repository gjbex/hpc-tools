from __future__ import annotations

from test_cli_fixtures import *


class CliCoreTests(unittest.TestCase):
    def test_storage_inspect_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect", "$VSC_DATA/Projects/demo"])

        self.assertIs(args.handler, cmd_storage_inspect)
        self.assertEqual(args.path, "$VSC_DATA/Projects/demo")
        with mock.patch(
            "hpc_tools.commands.remote.list_remote_directory",
            return_value=(args.path, (), False),
        ) as listing:
            result = cmd_storage_inspect(args, make_profile())

        self.assertEqual(result, 0)
        listing.assert_called_once()

    def test_storage_inspect_defaults_to_profile_projects_directory(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect"])

        self.assertIsNone(args.path)
        with mock.patch(
            "hpc_tools.commands.remote.list_remote_directory",
            return_value=("$VSC_DATA/Projects", (), False),
        ) as listing:
            self.assertEqual(cmd_storage_inspect(args, make_profile()), 0)
        self.assertEqual(listing.call_args.args[1], "$VSC_DATA/Projects")

    def test_module_spider_parser_and_command_quotes_name(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["module-spider", "DMTCP; rm -rf /"])

        self.assertEqual(args.name, "DMTCP; rm -rf /")
        self.assertEqual(_module_spider_command(args.name), "module spider 'DMTCP; rm -rf /' 2>&1")

    def test_repo_status_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["repo", "status", "--directory", "$VSC_DATA/Projects/demo"])

        self.assertIs(args.handler, cmd_repo_status)
        self.assertEqual(args.directory, "$VSC_DATA/Projects/demo")
        command = _repo_status_command(args.directory)
        self.assertIn("test -d $VSC_DATA/Projects/demo", command)
        self.assertIn("git status --short --branch", command)
        self.assertIn("git remote -v", command)
        self.assertIn("git log -1 --oneline", command)

    def test_clone_command_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "clone", "https://github.com/org/repo.git", "--branch", "main"])

        self.assertIs(args.handler, cmd_clone)
        self.assertEqual(args.url, "https://github.com/org/repo.git")
        self.assertEqual(args.branch, "main")

    def test_clone_parser_accepts_directory_override(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "clone",
                "https://github.com/org/repo.git",
                "--branch",
                "main",
                "--directory",
                "$VSC_SCRATCH/repos",
                "--name",
                "demo",
            ]
        )

        self.assertIs(args.handler, cmd_clone)
        self.assertEqual(args.directory, "$VSC_SCRATCH/repos")
        self.assertEqual(args.name, "demo")

    def test_clone_uses_directory_override(self) -> None:
        profile = make_profile(projects_dir=None)
        parser = build_parser(profile)
        args = parser.parse_args(
            [
                "--dry-run",
                "clone",
                "https://github.com/org/repo.git",
                "--directory",
                "$VSC_SCRATCH/repos",
            ]
        )

        with mock.patch("hpc_tools.commands.remote.run_command") as run_remote:
            cmd_clone(args, profile)

        self.assertEqual(
            run_remote.call_args.args[1],
            "cd $VSC_SCRATCH/repos && git -c core.hooksPath=/dev/null clone "
            "--no-recurse-submodules -- https://github.com/org/repo.git repo",
        )

    def test_clone_rejects_local_source(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["--dry-run", "clone", "file:///tmp/repo"])

        with self.assertRaisesRegex(ConfigError, "network URL"):
            cmd_clone(args, profile)

    def test_projects_quotes_directory_paths(self) -> None:
        profile = make_profile(projects_dir="/data/My Projects")
        args = type("Args", (), {"dry_run": False})()

        with mock.patch(
            "hpc_tools.commands.remote.list_remote_directory",
            return_value=("/data/My Projects", (), False),
        ) as listing:
            self.assertEqual(cmd_projects(args, profile), 0)
        self.assertEqual(listing.call_args.args[1], "/data/My Projects")

    def test_clone_requires_directory_when_projects_dir_is_missing(self) -> None:
        profile = make_profile(projects_dir=None)
        parser = build_parser(profile)
        args = parser.parse_args(["clone", "https://github.com/org/repo.git"])

        with self.assertRaises(ConfigError):
            cmd_clone(args, profile)
