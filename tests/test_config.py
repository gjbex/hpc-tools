from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from hpc_tools.config import ConfigError, load_config, resolve_profile


class ConfigTests(unittest.TestCase):
    def test_loads_default_profile(self) -> None:
        path = self._write_config(
            """
            default_profile = "genius"

            [profiles.genius]
            host = "genius"
            user = "gjb"
            projects_dir = "$VSC_DATA/Projects"
            sam_balance_command = "sam-balance"
            sam_statement_command = "sam-statement"
            hardware_reference = "/tmp/hardware.md"
            hardware_url = "https://example.org/hardware"
            slurm_reference = "/tmp/slurm.md"
            slurm_url = "https://example.org/slurm"
            default_cluster = "wice"
            """
        )

        config = load_config(str(path))
        profile = resolve_profile(config, None)

        self.assertEqual(profile.name, "genius")
        self.assertEqual(profile.target, "gjb@genius")
        self.assertEqual(profile.ssh_target, "gjb@genius")
        self.assertEqual(profile.host, "genius")
        self.assertEqual(profile.user, "gjb")
        self.assertEqual(profile.ssh_options, ())
        self.assertEqual(profile.login_shell, ("bash", "-l", "-c"))
        self.assertEqual(profile.projects_dir, "$VSC_DATA/Projects")
        self.assertEqual(profile.sam_balance_command, "sam-balance")
        self.assertEqual(profile.sam_statement_command, "sam-statement")
        self.assertEqual(profile.hardware_reference, "/tmp/hardware.md")
        self.assertEqual(profile.hardware_url, "https://example.org/hardware")
        self.assertEqual(profile.slurm_reference, "/tmp/slurm.md")
        self.assertEqual(profile.slurm_url, "https://example.org/slurm")
        self.assertEqual(profile.default_cluster, "wice")

    def test_loads_ssh_config_alias_profile(self) -> None:
        path = self._write_config(
            """
            default_profile = "genius"

            [profiles.genius]
            ssh_target = "genius"
            ssh_options = ["-x", "-A"]
            projects_dir = "$VSC_DATA/Projects"
            """
        )

        config = load_config(str(path))
        profile = resolve_profile(config, None)

        self.assertEqual(profile.name, "genius")
        self.assertEqual(profile.target, "genius")
        self.assertEqual(profile.ssh_target, "genius")
        self.assertEqual(profile.ssh_options, ("-x", "-A"))
        self.assertIsNone(profile.host)
        self.assertIsNone(profile.user)

    def test_prefers_explicit_ssh_target_over_host_user(self) -> None:
        path = self._write_config(
            """
            [profiles.genius]
            ssh_target = "genius"
            host = "login.somewhere"
            user = "gjb"
            """
        )

        config = load_config(str(path))
        profile = resolve_profile(config, "genius")

        self.assertEqual(profile.ssh_target, "genius")

    def test_rejects_login_shell_without_command_flag(self) -> None:
        path = self._write_config(
            """
            [profiles.bad]
            host = "example"
            login_shell = ["bash", "-l"]
            """
        )

        with self.assertRaises(ConfigError):
            load_config(str(path))

    def test_rejects_non_string_ssh_options(self) -> None:
        path = self._write_config(
            """
            [profiles.bad]
            ssh_target = "bad"
            ssh_options = "not-a-list"
            """
        )

        with self.assertRaises(ConfigError):
            load_config(str(path))

    def test_rejects_profile_without_ssh_target_or_host(self) -> None:
        path = self._write_config(
            """
            [profiles.bad]
            projects_dir = "$VSC_DATA/Projects"
            """
        )

        with self.assertRaises(ConfigError):
            load_config(str(path))

    def _write_config(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.toml"
        path.write_text(textwrap.dedent(contents), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
