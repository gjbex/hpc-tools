from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from hpc_tools.capabilities import CapabilityLevel
from hpc_tools.config import (
    ConfigError,
    default_config_dir,
    default_config_path,
    load_config,
    profile_capability_summary,
    resolve_profile,
)


ROOT = Path(__file__).resolve().parents[1]


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
            sam_quote_format = "hpc-tools-credit-quote-v1"
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

            [profiles.genius.capabilities]
            version = 1
            max_level = "job-inspection"
            scopes = ["job.validate", "remote-filesystem.read"]

            [profiles.genius.capabilities.remote_roots]
            read = ["$VSC_DATA/Projects"]
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
        self.assertEqual(profile.sam_quote_format, "hpc-tools-credit-quote-v1")
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
        self.assertIs(profile.capabilities.max_level, CapabilityLevel.JOB_INSPECTION)
        self.assertEqual(
            profile.capabilities.scopes,
            ("job.validate", "remote-filesystem.read"),
        )
        self.assertEqual(
            profile.capabilities.remote_roots.read,
            ("$VSC_DATA/Projects",),
        )

    def test_loads_ssh_config_alias_profile(self) -> None:
        path = self._write_config(
            """
            default_profile = "genius"

            [profiles.genius]
            ssh_target = "genius"
            ssh_options = ["-x", "-A"]
            projects_dir = "$VSC_DATA/Projects"

            [profiles.genius.capabilities]
            version = 1
            max_level = "profile-context"
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

    def test_loads_full_toml_string_forms(self) -> None:
        path = self._write_config(
            r'''
            [profiles.genius]
            ssh_target = "genius"
            login_shell = 'bash -l -c'
            queue_command = """
            module load slurm
            squeue --me
            """

            [profiles.genius.capabilities]
            version = 1
            max_level = "cluster-discovery"
            '''
        )

        profile = resolve_profile(load_config(str(path)), "genius")

        self.assertEqual(profile.login_shell, ("bash", "-l", "-c"))
        self.assertEqual(profile.queue_command, "module load slurm\nsqueue --me\n")

    def test_prefers_explicit_ssh_target_over_host_user(self) -> None:
        path = self._write_config(
            """
            [profiles.genius]
            ssh_target = "genius"
            host = "login.somewhere"
            user = "gjb"

            [profiles.genius.capabilities]
            version = 1
            max_level = "profile-context"
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

            [profiles.bad.capabilities]
            version = 1
            max_level = "profile-context"
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

            [profiles.bad.capabilities]
            version = 1
            max_level = "profile-context"
            """
        )

        with self.assertRaises(ConfigError):
            load_config(str(path))

    def test_structured_quote_format_is_strict_and_requires_a_command(self) -> None:
        cases = {
            "unknown": (
                'sam_quote_command = "quote"\nsam_quote_format = "site-v1"',
                "must be one of",
            ),
            "without-command": (
                'sam_quote_format = "hpc-tools-credit-quote-v1"',
                "requires sam_quote_command",
            ),
            "wrong-type": (
                'sam_quote_command = "quote"\nsam_quote_format = 1',
                "must be a non-empty string",
            ),
        }
        for name, (fields, message) in cases.items():
            with self.subTest(name=name):
                path = self._write_config(
                    f"""
                    [profiles.bad]
                    {fields}

                    [profiles.bad.capabilities]
                    version = 1
                    max_level = "job-inspection"
                    """
                )
                with self.assertRaisesRegex(ConfigError, message):
                    load_config(str(path))

    def test_allows_profile_without_ssh_target_for_local_execution(self) -> None:
        path = self._write_config(
            """
            [profiles.local]
            projects_dir = "$VSC_DATA/Projects"

            [profiles.local.capabilities]
            version = 1
            max_level = "cluster-discovery"
            """
        )

        profile = load_config(str(path)).profiles["local"]

        self.assertIsNone(profile.ssh_target)
        self.assertIsNone(profile.host)

    def test_rejects_missing_empty_and_invalid_capability_blocks(self) -> None:
        cases = (
            (
                """
                [profiles.missing]
                ssh_target = "missing"
                """,
                "must define.*capabilities",
            ),
            (
                """
                [profiles.empty]
                ssh_target = "empty"

                [profiles.empty.capabilities]
                """,
                "must define version",
            ),
            (
                """
                [profiles.invalid]
                ssh_target = "invalid"

                [profiles.invalid.capabilities]
                version = 1
                max_level = "full-control"
                """,
                "unknown capability max_level",
            ),
        )
        for contents, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ConfigError, message):
                    load_config(str(self._write_config(contents)))

    def test_strict_policy_validation_does_not_reject_unrelated_profile_keys(self) -> None:
        path = self._write_config(
            """
            [profiles.example]
            ssh_target = "example"
            future_site_field = "ignored outside the policy tables"

            [profiles.example.capabilities]
            version = 1
            max_level = "profile-context"
            """
        )

        profile = load_config(str(path)).profiles["example"]

        self.assertEqual(profile.ssh_target, "example")

    def test_multiple_profiles_keep_independent_policies(self) -> None:
        path = self._write_config(
            """
            default_profile = "observe"

            [profiles.observe]
            ssh_target = "observe"

            [profiles.observe.capabilities]
            version = 1
            max_level = "job-inspection"
            scopes = ["job.validate"]

            [profiles.submit]
            ssh_target = "submit"

            [profiles.submit.capabilities]
            version = 1
            max_level = "job-lifecycle"
            scopes = ["accounting.read"]
            """
        )

        config = load_config(str(path))

        self.assertIs(
            config.profiles["observe"].capabilities.max_level,
            CapabilityLevel.JOB_INSPECTION,
        )
        self.assertEqual(config.profiles["observe"].capabilities.scopes, ("job.validate",))
        self.assertIs(
            config.profiles["submit"].capabilities.max_level,
            CapabilityLevel.JOB_LIFECYCLE,
        )
        self.assertEqual(config.profiles["submit"].capabilities.scopes, ("accounting.read",))

    def test_loads_mandatory_policy_through_xdg_and_explicit_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            xdg = Path(directory)
            default_path = xdg / "hpc-tools" / "config.toml"
            default_path.parent.mkdir(parents=True)
            default_path.write_text(
                textwrap.dedent(
                    """
                    [profiles.xdg]
                    ssh_target = "xdg"

                    [profiles.xdg.capabilities]
                    version = 1
                    max_level = "profile-context"
                    """
                ),
                encoding="utf-8",
            )
            explicit_path = xdg / "explicit.toml"
            explicit_path.write_text(
                textwrap.dedent(
                    """
                    [profiles.explicit]
                    ssh_target = "explicit"

                    [profiles.explicit.capabilities]
                    version = 1
                    max_level = "cluster-discovery"
                    """
                ),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(xdg)}, clear=True):
                self.assertIn("xdg", load_config().profiles)
                self.assertIn("explicit", load_config(str(explicit_path)).profiles)

    def test_loading_policy_has_no_external_effects_or_file_writes(self) -> None:
        path = self._write_config(
            """
            [profiles.local]

            [profiles.local.capabilities]
            version = 1
            max_level = "profile-context"
            """
        )
        before = path.read_bytes()

        with mock.patch("subprocess.run") as run, mock.patch("urllib.request.urlopen") as urlopen:
            profile = load_config(str(path)).profiles["local"]

        self.assertEqual(path.read_bytes(), before)
        run.assert_not_called()
        urlopen.assert_not_called()
        self.assertEqual(profile.capabilities.scopes, ())

    def test_public_policy_summary_excludes_profile_connection_details(self) -> None:
        path = self._write_config(
            """
            [profiles.private]
            ssh_target = "user@login.example"
            sam_quote_command = "private-quote --account secret"

            [profiles.private.capabilities]
            version = 1
            max_level = "job-inspection"
            scopes = ["job.validate"]
            """
        )
        profile = load_config(str(path)).profiles["private"]

        summary = profile_capability_summary(profile)

        self.assertEqual(summary["name"], "private")
        self.assertEqual(summary["capabilities"]["max_level"], "job-inspection")
        self.assertNotIn("ssh_target", summary)
        self.assertNotIn("sam_quote_command", summary)
        self.assertNotIn("sam_quote_format", summary)

    def test_checked_in_profile_examples_use_the_accepted_policy_schema(self) -> None:
        for name in (
            "ssh-alias-config.toml",
            "user-host-config.toml",
            "capability-profiles.toml",
        ):
            with self.subTest(name=name):
                config = load_config(str(ROOT / "examples" / name))
                self.assertTrue(config.profiles)
                for profile in config.profiles.values():
                    self.assertEqual(profile.capabilities.version, 1)

    def test_capability_role_templates_cover_four_levels_and_two_centers(self) -> None:
        config = load_config(str(ROOT / "examples" / "capability-profiles.toml"))

        self.assertEqual(
            set(config.profiles),
            {
                "atlas-context",
                "atlas-staging",
                "borealis-monitor",
                "borealis-lifecycle",
            },
        )
        self.assertEqual(
            [
                config.profiles[name].capabilities.max_level
                for name in config.profiles
            ],
            [
                CapabilityLevel.PROFILE_CONTEXT,
                CapabilityLevel.CLUSTER_DISCOVERY,
                CapabilityLevel.JOB_INSPECTION,
                CapabilityLevel.JOB_LIFECYCLE,
            ],
        )
        staging = config.profiles["atlas-staging"].capabilities
        self.assertEqual(staging.remote_roots.read, ("/project/example-team/source",))
        self.assertEqual(staging.remote_roots.write, ("/project/example-team/staging",))
        lifecycle = config.profiles["borealis-lifecycle"].capabilities
        self.assertNotIn("remote-filesystem.read", lifecycle.scopes)
        self.assertEqual(lifecycle.remote_roots.read, ())

    def _write_config(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.toml"
        path.write_text(textwrap.dedent(contents), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
