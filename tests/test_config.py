from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from hpc_tools.config import ConfigError, default_config_dir, default_config_path, load_config, resolve_profile


class ConfigTests(unittest.TestCase):
    def test_default_config_path_uses_xdg_config_home(self) -> None:
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True):
            self.assertEqual(default_config_dir(), Path("/tmp/xdg/hpc-tools"))
            self.assertEqual(default_config_path(), Path("/tmp/xdg/hpc-tools/config.toml"))

    def test_hpc_tools_config_overrides_xdg_config_home(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "XDG_CONFIG_HOME": "/tmp/xdg",
                "HPC_TOOLS_CONFIG": "/tmp/custom/config.toml",
            },
            clear=True,
        ):
            self.assertEqual(default_config_path(), Path("/tmp/custom/config.toml"))

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
            sam_quote_command = "sam-quote"
            hardware_reference = "/tmp/hardware.md"
            hardware_url = "https://example.org/hardware"
            slurm_reference = "/tmp/slurm.md"
            slurm_url = "https://example.org/slurm"
            storage_reference = "/tmp/storage.md"
            storage_url = "https://example.org/storage"
            status_url = "https://status.example.org/"
            reference_set = "kuleuven-tier2"
            default_cluster = "wice"
            email = "gjb@example.org"
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
        self.assertEqual(profile.sam_quote_command, "sam-quote")
        self.assertEqual(profile.hardware_reference, "/tmp/hardware.md")
        self.assertEqual(profile.hardware_url, "https://example.org/hardware")
        self.assertEqual(profile.slurm_reference, "/tmp/slurm.md")
        self.assertEqual(profile.slurm_url, "https://example.org/slurm")
        self.assertEqual(profile.storage_reference, "/tmp/storage.md")
        self.assertEqual(profile.storage_url, "https://example.org/storage")
        self.assertEqual(profile.status_url, "https://status.example.org/")
        self.assertEqual(profile.reference_set, "kuleuven-tier2")
        self.assertEqual(profile.default_cluster, "wice")
        self.assertEqual(profile.email, "gjb@example.org")

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
