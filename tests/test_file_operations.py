from __future__ import annotations

import base64
import contextlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from hpc_tools.capabilities import CapabilityLevel, CapabilityPolicy, RemoteRootGrants
from hpc_tools.config import ConfigError
from hpc_tools.execution import executor_scope
from hpc_tools.mcp.tools import (
    hpc_files_copy,
    hpc_files_download,
    hpc_files_list,
    hpc_files_mkdir,
    hpc_files_read,
    hpc_files_remove,
    hpc_files_upload,
)
from hpc_tools.mcp.server import tool_names_for_preset
from hpc_tools.remote_filesystem import write_local_regular_file
from test_cli_fixtures import make_profile


class FileOperationTests(unittest.TestCase):
    def test_mcp_single_file_round_trip_and_empty_directory_removal(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            profile = self._profile(root)
            source = root / "source.bin"
            source.write_bytes(b"\x00payload\xff")

            with self._local_profile(profile):
                preview = hpc_files_upload(
                    str(source), str(root / "remote.bin"), confirm=True
                )
                self.assertFalse(preview["executed"])
                self.assertFalse((root / "remote.bin").exists())

                uploaded = hpc_files_upload(
                    str(source),
                    str(root / "remote.bin"),
                    dry_run=False,
                    confirm=True,
                )
                copied = hpc_files_copy(
                    str(root / "remote.bin"),
                    str(root / "copied.bin"),
                    dry_run=False,
                    confirm=True,
                )
                downloaded = hpc_files_download(
                    str(root / "copied.bin"),
                    str(root / "downloaded.bin"),
                    dry_run=False,
                    confirm=True,
                )
                read = hpc_files_read(str(root / "remote.bin"), encoding="base64")
                listing = hpc_files_list(str(root))
                created = hpc_files_mkdir(
                    str(root / "empty"), dry_run=False, confirm=True
                )
                removed = hpc_files_remove(
                    str(root / "empty"), dry_run=False, confirm=True
                )

            self.assertTrue(uploaded["executed"])
            self.assertTrue(copied["executed"])
            self.assertTrue(downloaded["executed"])
            self.assertEqual((root / "downloaded.bin").read_bytes(), b"\x00payload\xff")
            self.assertEqual(base64.b64decode(read["content"]), b"\x00payload\xff")
            self.assertIn("remote.bin", {entry["name"] for entry in listing["entries"]})
            self.assertEqual(created["path"], str(root / "empty"))
            self.assertEqual(removed["kind"], "directory")

    def test_transfer_rejects_overwrite_symlink_and_nonempty_removal(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            profile = self._profile(root)
            source = root / "source.txt"
            source.write_text("new", encoding="utf-8")
            destination = root / "destination.txt"
            destination.write_text("old", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(destination)
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "kept").write_text("kept", encoding="utf-8")

            with self._local_profile(profile):
                with self.assertRaisesRegex(ConfigError, "already exists"):
                    hpc_files_upload(
                        str(source), str(destination), dry_run=False, confirm=True
                    )
                with self.assertRaisesRegex(ConfigError, "symbolic link"):
                    hpc_files_upload(
                        str(source), str(link), force=True, dry_run=False, confirm=True
                    )
                with self.assertRaisesRegex(ConfigError, "not empty"):
                    hpc_files_remove(
                        str(nonempty), dry_run=False, confirm=True
                    )
                with self.assertRaisesRegex(ConfigError, "configured remote root"):
                    hpc_files_remove(str(root), dry_run=False, confirm=True)

            self.assertEqual(destination.read_text(encoding="utf-8"), "old")
            self.assertTrue((nonempty / "kept").exists())

    def test_local_publication_is_atomic_and_requires_safe_regular_target(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            destination = root / "result.bin"
            selected, overwritten = write_local_regular_file(
                str(destination), b"first"
            )
            self.assertEqual(selected, destination)
            self.assertFalse(overwritten)
            with self.assertRaisesRegex(ConfigError, "already exists"):
                write_local_regular_file(str(destination), b"second")
            selected, overwritten = write_local_regular_file(
                str(destination), b"second", overwrite=True
            )
            self.assertTrue(overwritten)
            self.assertEqual(selected.read_bytes(), b"second")

    def test_read_without_read_grant_is_denied_before_execution(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            profile = self._profile(root)
            profile = replace(
                profile,
                capabilities=CapabilityPolicy(
                    version=1,
                    max_level=profile.capabilities.max_level,
                    scopes=profile.capabilities.scopes,
                    remote_roots=RemoteRootGrants(
                        list=(str(root),),
                        write=(str(root),),
                        delete=(str(root),),
                    ),
                ),
            )
            with self._local_profile(profile):
                with self.assertRaisesRegex(ConfigError, "no declared read root"):
                    hpc_files_read(str(root / "secret"))

    def test_mcp_discovery_separates_file_grants_from_job_level(self) -> None:
        base = make_profile()
        staging = replace(
            base,
            capabilities=CapabilityPolicy(
                version=1,
                max_level=CapabilityLevel.CLUSTER_DISCOVERY,
                scopes=("remote-workspace.write",),
                remote_roots=RemoteRootGrants(write=("/work",)),
            ),
        )
        lifecycle_without_reads = replace(
            base,
            capabilities=CapabilityPolicy(
                version=1,
                max_level=CapabilityLevel.JOB_LIFECYCLE,
                scopes=(),
                remote_roots=RemoteRootGrants(),
            ),
        )

        staging_tools = tool_names_for_preset("full", staging)
        lifecycle_tools = tool_names_for_preset("full", lifecycle_without_reads)

        self.assertIn("hpc_files_upload", staging_tools)
        self.assertNotIn("hpc_files_read", staging_tools)
        self.assertNotIn("hpc_submit_job", staging_tools)
        self.assertNotIn("hpc_files_read", lifecycle_tools)

    def _profile(self, root: Path):
        base = make_profile()
        return replace(
            base,
            target=None,
            host=None,
            user=None,
            projects_dir=str(root),
            capabilities=CapabilityPolicy(
                version=1,
                max_level=base.capabilities.max_level,
                scopes=base.capabilities.scopes,
                remote_roots=RemoteRootGrants(
                    list=(str(root),),
                    read=(str(root),),
                    write=(str(root),),
                    delete=(str(root),),
                    install=(str(root),),
                ),
            ),
        )

    def _local_profile(self, profile):
        stack = contextlib.ExitStack()
        stack.enter_context(executor_scope("local"))
        stack.enter_context(
            mock.patch("hpc_tools.mcp.tools._resolve_profile", return_value=profile)
        )
        return stack


if __name__ == "__main__":
    unittest.main()
