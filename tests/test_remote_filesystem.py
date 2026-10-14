from __future__ import annotations

from dataclasses import replace
import stat
import tempfile
import unittest
from pathlib import Path

from test_cli_fixtures import make_profile

from hpc_tools.capabilities import CapabilityPolicy, RemoteRootGrants
from hpc_tools.config import ConfigError
from hpc_tools.execution import LocalExecutor
from hpc_tools.filesystem import FilesystemService
from hpc_tools.remote_filesystem import (
    install_remote_assets,
    list_remote_directory,
    plan_remote_assets,
    resolve_granted_path,
)


class RemoteFilesystemServiceTests(unittest.TestCase):
    def test_preview_validates_bundle_without_remote_effects(self) -> None:
        planned = plan_remote_assets(
            "$WORK/probes",
            {"probe.slurm": "#!/bin/sh\n", "data.txt": b"data"},
            roots=("$WORK",),
        )

        self.assertEqual(
            [(asset.path, asset.mode) for asset in planned],
            [("$WORK/probes/probe.slurm", 0o700), ("$WORK/probes/data.txt", 0o600)],
        )
        with self.assertRaisesRegex(ConfigError, "invalid remote asset path"):
            plan_remote_assets(
                "$WORK/probes",
                {"../escape": "no"},
                roots=("$WORK",),
            )

    def test_asset_bundle_uses_bounded_helper_and_preserves_modes(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            profile, service = self._profile_and_service(root)

            installed = install_remote_assets(
                profile,
                f"{root}/bundle",
                {
                    "job.slurm": "#!/bin/bash\n",
                    "nested/input.txt": b"\x00data\xff",
                },
                roots=(str(root),),
                service=service,
            )

            self.assertEqual(len(installed), 2)
            self.assertEqual((root / "bundle/nested/input.txt").read_bytes(), b"\x00data\xff")
            self.assertEqual(
                stat.S_IMODE((root / "bundle/job.slurm").stat().st_mode),
                0o700,
            )
            self.assertEqual(
                stat.S_IMODE((root / "bundle/nested/input.txt").stat().st_mode),
                0o600,
            )

    def test_existing_asset_conflict_is_checked_before_publication(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            (root / "bundle").mkdir()
            (root / "bundle/existing.txt").write_text("old", encoding="utf-8")
            profile, service = self._profile_and_service(root)

            with self.assertRaisesRegex(ConfigError, "already exists"):
                install_remote_assets(
                    profile,
                    f"{root}/bundle",
                    {"new.txt": "new", "existing.txt": "replacement"},
                    roots=(str(root),),
                    service=service,
                )

            self.assertFalse((root / "bundle/new.txt").exists())
            self.assertEqual((root / "bundle/existing.txt").read_text(), "old")

    def test_invalid_asset_path_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            profile, service = self._profile_and_service(root)

            with self.assertRaisesRegex(ConfigError, "invalid remote asset"):
                install_remote_assets(
                    profile,
                    f"{root}/bundle",
                    {"../escape": "bad"},
                    roots=(str(root),),
                    service=service,
                )

            self.assertFalse((root / "bundle").exists())

    def test_directory_listing_is_bounded_to_declared_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            (root / "one").write_text("1", encoding="utf-8")
            profile, service = self._profile_and_service(root)

            selected, entries, truncated = list_remote_directory(
                profile,
                str(root),
                roots=(str(root),),
                service=service,
            )

            self.assertEqual(selected, str(root))
            self.assertEqual([entry.name for entry in entries], ["one"])
            self.assertFalse(truncated)
            with self.assertRaisesRegex(ConfigError, "outside"):
                resolve_granted_path(str(root.parent / "private"), (str(root),))

    def _profile_and_service(self, root: Path):
        base = make_profile()
        grants = RemoteRootGrants(
            list=(str(root),),
            read=(str(root),),
            write=(str(root),),
            install=(str(root),),
        )
        profile = replace(
            base,
            target=None,
            host=None,
            user=None,
            capabilities=CapabilityPolicy(
                version=1,
                max_level=base.capabilities.max_level,
                scopes=base.capabilities.scopes,
                remote_roots=grants,
            ),
        )
        return profile, FilesystemService(profile, executor=LocalExecutor())


if __name__ == "__main__":
    unittest.main()
