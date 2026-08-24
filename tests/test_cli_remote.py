from __future__ import annotations

from test_cli_fixtures import *


class CliCoreTests(unittest.TestCase):
    def test_storage_inspect_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect", "$VSC_DATA/Projects/demo"])

        self.assertIs(args.handler, cmd_storage_inspect)
        self.assertEqual(args.path, "$VSC_DATA/Projects/demo")
        command = _storage_inspect_command(args.path)
        self.assertIn("## path", command)
        self.assertIn("ls -ld $VSC_DATA/Projects/demo", command)
        self.assertIn("df -hT $VSC_DATA/Projects/demo", command)
        self.assertIn("du -sh $VSC_DATA/Projects/demo", command)
        self.assertIn("mount | sed -n '1,80p'", command)

    def test_storage_inspect_defaults_to_current_directory(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect"])

        self.assertEqual(args.path, ".")
        self.assertIn("df -hT .", _storage_inspect_command(args.path))

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
            "cd $VSC_SCRATCH/repos && git clone https://github.com/org/repo.git",
        )

    def test_projects_quotes_directory_paths(self) -> None:
        profile = make_profile(projects_dir="/data/My Projects")
        args = type("Args", (), {"dry_run": False})()

        with mock.patch("hpc_tools.commands.remote.run_command") as run_remote:
            cmd_projects(args, profile)

        self.assertEqual(
            run_remote.call_args.args[1],
            "ls -ld '/data/My Projects' 2>/dev/null && ls -1 '/data/My Projects'",
        )

    def test_clone_requires_directory_when_projects_dir_is_missing(self) -> None:
        profile = make_profile(projects_dir=None)
        parser = build_parser(profile)
        args = parser.parse_args(["clone", "https://github.com/org/repo.git"])

        with self.assertRaises(ConfigError):
            cmd_clone(args, profile)
