from __future__ import annotations

from dataclasses import replace
from importlib import resources
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from hpc_tools.data import filesystem_helper
from hpc_tools.execution import CommandExecutor, LocalExecutor, SshExecutor
from hpc_tools.filesystem import (
    FILESYSTEM_PROTOCOL_VERSION,
    FilesystemAction,
    FilesystemFailureCode,
    FilesystemLimits,
    FilesystemRequest,
    FilesystemService,
)

from test_cli_fixtures import make_profile


ROOT = Path(__file__).resolve().parents[1]


class FilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "root"
        self.root.mkdir()
        self.profile = replace(make_profile(), target=None, host=None, user=None)
        self.service = FilesystemService(
            self.profile,
            executor=LocalExecutor(),
            limits=FilesystemLimits(
                max_bytes=1024,
                max_entries=20,
                max_transfer_bytes=4096,
                timeout_seconds=5,
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_packaged_helper_probe_needs_no_remote_package_import(self) -> None:
        helper = resources.files("hpc_tools.data").joinpath("filesystem_helper.py")
        self.assertTrue(helper.is_file())
        source = helper.read_text(encoding="utf-8")
        self.assertNotIn("import hpc_tools", source)

        result = self.service.probe()

        self.assertTrue(result.ok)
        self.assertIs(result.action, FilesystemAction.PROBE)

    def test_binary_write_and_read_preserve_exact_bytes(self) -> None:
        payload = b"\x00\xffbinary\r\ncontent"

        written = self.service.write_bytes(
            "payload.bin",
            payload,
            roots=(str(self.root),),
        )
        read = self.service.read_bytes(
            str(self.root / "payload.bin"),
            roots=(str(self.root),),
        )

        self.assertTrue(written.ok)
        self.assertTrue(read.ok)
        self.assertEqual(read.data, payload)
        self.assertEqual((self.root / "payload.bin").read_bytes(), payload)

    def test_text_read_is_utf8_strict_by_default(self) -> None:
        (self.root / "invalid.txt").write_bytes(b"valid\xffinvalid")

        strict = self.service.read_text(
            "invalid.txt",
            roots=(str(self.root),),
        )
        replaced = self.service.read_text(
            "invalid.txt",
            roots=(str(self.root),),
            errors="replace",
        )

        self.assertFalse(strict.ok)
        self.assertEqual(strict.failure.code, FilesystemFailureCode.ENCODING_ERROR)
        self.assertTrue(replaced.ok)
        self.assertEqual(replaced.text, "valid\ufffdinvalid")

    def test_listing_is_bounded_and_does_not_follow_entries(self) -> None:
        (self.root / "file.txt").write_text("data", encoding="utf-8")
        (self.root / "directory").mkdir()
        (self.root / "link").symlink_to(self.root / "file.txt")
        os.mkfifo(self.root / "pipe")

        result = self.service.list_directory(
            str(self.root),
            roots=(str(self.root),),
        )

        self.assertTrue(result.ok)
        kinds = {entry.name: entry.kind for entry in result.entries}
        self.assertEqual(kinds["file.txt"], "file")
        self.assertEqual(kinds["directory"], "directory")
        self.assertEqual(kinds["link"], "symlink")
        self.assertEqual(kinds["pipe"], "special")

    def test_read_and_listing_report_truncation(self) -> None:
        (self.root / "large.bin").write_bytes(b"abcdefghij")
        for index in range(4):
            (self.root / f"entry-{index}").write_text("x", encoding="utf-8")
        service = FilesystemService(
            self.profile,
            executor=LocalExecutor(),
            limits=FilesystemLimits(
                max_bytes=4,
                max_entries=2,
                max_transfer_bytes=16,
                timeout_seconds=5,
            ),
        )

        read = service.read_bytes("large.bin", roots=(str(self.root),))
        listing = service.list_directory(str(self.root), roots=(str(self.root),))

        self.assertTrue(read.ok)
        self.assertEqual(read.data, b"abcd")
        self.assertEqual(read.size, 10)
        self.assertTrue(read.truncated)
        self.assertTrue(listing.ok)
        self.assertEqual(len(listing.entries), 2)
        self.assertTrue(listing.truncated)

    def test_oversized_transfer_returns_structured_failure(self) -> None:
        service = FilesystemService(
            self.profile,
            executor=LocalExecutor(),
            limits=FilesystemLimits(max_transfer_bytes=3),
        )

        result = service.write_bytes(
            "large.bin",
            b"four",
            roots=(str(self.root),),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.LIMIT_EXCEEDED)
        self.assertFalse((self.root / "large.bin").exists())

    def test_relative_path_uses_selected_root_and_rejects_ambiguity(self) -> None:
        second = Path(self.temporary.name) / "second"
        second.mkdir()
        (second / "value.txt").write_text("second", encoding="utf-8")

        selected = self.service.read_text(
            "value.txt",
            roots=(str(self.root), str(second)),
            root=str(second),
        )
        ambiguous = self.service.read_bytes(
            "value.txt",
            roots=(str(self.root), str(second)),
        )

        self.assertTrue(selected.ok)
        self.assertEqual(selected.text, "second")
        self.assertFalse(ambiguous.ok)
        self.assertEqual(ambiguous.failure.code, FilesystemFailureCode.INVALID_PATH)

    def test_sibling_prefix_escape_is_denied(self) -> None:
        sibling = Path(f"{self.root}-sibling")
        sibling.mkdir()
        (sibling / "secret").write_text("secret", encoding="utf-8")

        result = self.service.read_bytes(
            str(sibling / "secret"),
            roots=(str(self.root),),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.ROOT_DENIED)

    def test_parent_traversal_and_ambiguous_segments_are_denied(self) -> None:
        cases = (
            f"{self.root}/../outside",
            f"{self.root}//file",
            f"{self.root}/./file",
            f"{self.root}/file/",
        )
        for path in cases:
            with self.subTest(path=path):
                result = self.service.read_bytes(path, roots=(str(self.root),))
                self.assertFalse(result.ok)
                self.assertEqual(result.failure.code, FilesystemFailureCode.INVALID_PATH)

    def test_filesystem_root_grant_is_rejected_by_the_helper(self) -> None:
        result = self.service.list_directory("/", roots=("/",))

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.ROOT_DENIED)

    def test_environment_root_and_path_are_expanded_remotely(self) -> None:
        (self.root / "env.txt").write_text("environment", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HPC_TOOLS_TEST_ROOT": str(self.root)}):
            result = self.service.read_text(
                "$HPC_TOOLS_TEST_ROOT/env.txt",
                roots=("$HPC_TOOLS_TEST_ROOT",),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "environment")

    def test_home_form_is_resolved_by_the_helper(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            (root / "home.txt").write_text("home", encoding="utf-8")
            relative = root.relative_to(Path.home())
            configured_root = f"~/{relative}"

            result = self.service.read_text(
                f"{configured_root}/home.txt",
                roots=(configured_root,),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "home")

    def test_missing_or_relative_environment_value_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            missing = self.service.list_directory(
                "$HPC_TOOLS_MISSING",
                roots=("$HPC_TOOLS_MISSING",),
            )
        with mock.patch.dict(os.environ, {"HPC_TOOLS_RELATIVE": "relative"}):
            relative = self.service.list_directory(
                "$HPC_TOOLS_RELATIVE",
                roots=("$HPC_TOOLS_RELATIVE",),
            )

        self.assertEqual(
            missing.failure.code,
            FilesystemFailureCode.UNAVAILABLE_ENVIRONMENT,
        )
        self.assertEqual(
            relative.failure.code,
            FilesystemFailureCode.UNAVAILABLE_ENVIRONMENT,
        )

    def test_symlink_file_and_parent_are_not_followed(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "secret").write_text("secret", encoding="utf-8")
        (self.root / "file-link").symlink_to(outside / "secret")
        (self.root / "directory-link").symlink_to(outside, target_is_directory=True)

        file_result = self.service.read_bytes(
            "file-link",
            roots=(str(self.root),),
        )
        parent_result = self.service.read_bytes(
            "directory-link/secret",
            roots=(str(self.root),),
        )

        self.assertEqual(file_result.failure.code, FilesystemFailureCode.SYMLINK_DENIED)
        self.assertIn(
            parent_result.failure.code,
            {FilesystemFailureCode.SYMLINK_DENIED, FilesystemFailureCode.NOT_DIRECTORY},
        )

    def test_special_files_are_not_read_or_removed(self) -> None:
        pipe = self.root / "pipe"
        os.mkfifo(pipe)

        read = self.service.read_bytes("pipe", roots=(str(self.root),))
        removed = self.service.remove("pipe", roots=(str(self.root),))

        self.assertEqual(read.failure.code, FilesystemFailureCode.SPECIAL_FILE_DENIED)
        self.assertEqual(removed.failure.code, FilesystemFailureCode.SPECIAL_FILE_DENIED)
        self.assertTrue(pipe.exists())

    def test_missing_destination_parent_is_not_created_implicitly(self) -> None:
        result = self.service.write_bytes(
            "missing/file.txt",
            b"data",
            roots=(str(self.root),),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.MISSING_PARENT)
        self.assertFalse((self.root / "missing").exists())

    def test_overwrite_conflict_and_atomic_replacement_are_explicit(self) -> None:
        destination = self.root / "result.txt"
        destination.write_text("old", encoding="utf-8")

        conflict = self.service.write_text(
            "result.txt",
            "new",
            roots=(str(self.root),),
        )
        replaced = self.service.write_text(
            "result.txt",
            "new",
            roots=(str(self.root),),
            overwrite=True,
        )

        self.assertFalse(conflict.ok)
        self.assertEqual(conflict.failure.code, FilesystemFailureCode.CONFLICT)
        self.assertTrue(replaced.ok)
        self.assertTrue(replaced.overwritten)
        self.assertEqual(destination.read_text(encoding="utf-8"), "new")

    def test_mkdir_and_nonrecursive_remove_primitives(self) -> None:
        created = self.service.make_directory("work", roots=(str(self.root),))
        (self.root / "work" / "file").write_text("data", encoding="utf-8")
        nonempty = self.service.remove("work", roots=(str(self.root),))
        file_removed = self.service.remove("work/file", roots=(str(self.root),))
        directory_removed = self.service.remove("work", roots=(str(self.root),))
        root_removed = self.service.remove(str(self.root), roots=(str(self.root),))

        self.assertTrue(created.ok)
        self.assertEqual(nonempty.failure.code, FilesystemFailureCode.NOT_EMPTY)
        self.assertEqual(file_removed.removed_kind, "file")
        self.assertEqual(directory_removed.removed_kind, "directory")
        self.assertEqual(root_removed.failure.code, FilesystemFailureCode.ROOT_DENIED)
        self.assertTrue(self.root.exists())

    def test_cleanup_only_removes_regular_helper_temporary_files(self) -> None:
        stale = self.root / ".hpc-tools-stale.tmp"
        ordinary = self.root / "ordinary.tmp"
        stale.write_text("partial", encoding="utf-8")
        ordinary.write_text("keep", encoding="utf-8")
        (self.root / ".hpc-tools-link.tmp").symlink_to(ordinary)

        result = self.service.cleanup_temporary(
            str(self.root),
            roots=(str(self.root),),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.removed_temporary, (stale.name,))
        self.assertFalse(stale.exists())
        self.assertTrue(ordinary.exists())
        self.assertTrue((self.root / ".hpc-tools-link.tmp").is_symlink())

    def test_interrupted_new_publication_leaves_no_target_or_temporary(self) -> None:
        request = FilesystemRequest(
            action=FilesystemAction.WRITE,
            path="result.bin",
            roots=(str(self.root),),
            data=b"complete data",
            limits=self.service.limits,
        ).protocol_value()
        with mock.patch.object(
            filesystem_helper.os,
            "link",
            side_effect=InterruptedError("interrupted"),
        ):
            response = filesystem_helper.handle_request(request)

        self.assertFalse(response["ok"])
        self.assertFalse((self.root / "result.bin").exists())
        self.assertEqual(list(self.root.glob(".hpc-tools-*.tmp")), [])

    def test_interrupted_overwrite_preserves_old_target(self) -> None:
        destination = self.root / "result.bin"
        destination.write_bytes(b"old complete data")
        request = FilesystemRequest(
            action=FilesystemAction.WRITE,
            path="result.bin",
            roots=(str(self.root),),
            data=b"new complete data",
            overwrite=True,
            limits=self.service.limits,
        ).protocol_value()
        with mock.patch.object(
            filesystem_helper.os,
            "replace",
            side_effect=InterruptedError("interrupted"),
        ):
            response = filesystem_helper.handle_request(request)

        self.assertFalse(response["ok"])
        self.assertEqual(destination.read_bytes(), b"old complete data")
        self.assertEqual(list(self.root.glob(".hpc-tools-*.tmp")), [])

    def test_open_directory_descriptor_survives_link_swap_without_escape(self) -> None:
        inside = self.root / "inside"
        outside = Path(self.temporary.name) / "outside"
        inside.mkdir()
        outside.mkdir()
        (inside / "value").write_bytes(b"safe")
        (outside / "value").write_bytes(b"secret")
        record = (str(self.root), str(self.root), os.path.realpath(self.root))
        root_fd = filesystem_helper._open_root(record)
        parent_fd, name = filesystem_helper._open_parent_at(
            root_fd,
            ("inside", "value"),
        )
        try:
            inside.rename(self.root / "original")
            (self.root / "inside").symlink_to(outside, target_is_directory=True)
            file_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                observed = os.read(file_fd, 32)
            finally:
                os.close(file_fd)
        finally:
            os.close(parent_fd)
            os.close(root_fd)

        self.assertEqual(observed, b"safe")
        self.assertNotEqual(observed, b"secret")

    def test_missing_interpreter_and_packaged_helper_fail_closed(self) -> None:
        missing_interpreter = FilesystemService(
            self.profile,
            executor=LocalExecutor(),
            interpreter="hpc-tools-python-does-not-exist",
        ).probe()
        with mock.patch(
            "hpc_tools.filesystem._helper_source",
            side_effect=FileNotFoundError("missing"),
        ):
            missing_helper = self.service.probe()

        self.assertEqual(
            missing_interpreter.failure.code,
            FilesystemFailureCode.HELPER_UNAVAILABLE,
        )
        self.assertEqual(
            missing_helper.failure.code,
            FilesystemFailureCode.HELPER_UNAVAILABLE,
        )

    def test_missing_descriptor_primitives_fail_closed(self) -> None:
        request = FilesystemRequest(
            action=FilesystemAction.PROBE,
            limits=self.service.limits,
        ).protocol_value()
        with mock.patch.object(filesystem_helper, "_platform_supported", return_value=False):
            response = filesystem_helper.handle_request(request)

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unsupported-platform")

    def test_transport_timeout_is_a_structured_failure(self) -> None:
        executor = _FailingExecutor(
            subprocess.TimeoutExpired(cmd=("python3",), timeout=1)
        )
        service = FilesystemService(self.profile, executor=executor)

        result = service.probe()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.TIMEOUT)

    def test_malformed_helper_response_is_rejected(self) -> None:
        executor = _ResultExecutor(
            subprocess.CompletedProcess(("helper",), 0, b"not-json", b"")
        )
        result = FilesystemService(self.profile, executor=executor).probe()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.PROTOCOL_ERROR)

    def test_oversized_helper_response_is_rejected(self) -> None:
        executor = _ResultExecutor(
            subprocess.CompletedProcess(("helper",), 0, b"x" * 70000, b"")
        )
        service = FilesystemService(
            self.profile,
            executor=executor,
            limits=FilesystemLimits(
                max_bytes=1,
                max_entries=1,
                max_transfer_bytes=1,
                timeout_seconds=1,
            ),
        )

        result = service.probe()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, FilesystemFailureCode.LIMIT_EXCEEDED)

    def test_local_and_executor_agnostic_loopback_have_identical_results(self) -> None:
        (self.root / "value").write_bytes(b"same")
        local = self.service.read_bytes("value", roots=(str(self.root),))
        loopback = FilesystemService(
            self.profile,
            executor=_LoopbackExecutor("ssh-loopback"),
            limits=self.service.limits,
        ).read_bytes("value", roots=(str(self.root),))

        self.assertEqual(loopback, local)

    def test_ssh_executor_uses_the_same_framed_payload(self) -> None:
        response = json.dumps({
            "protocol": FILESYSTEM_PROTOCOL_VERSION,
            "ok": True,
            "action": "probe",
            "available": True,
        }).encode("utf-8")
        completed = subprocess.CompletedProcess(("ssh",), 0, response, b"")
        profile = make_profile()
        service = FilesystemService(profile, executor=SshExecutor())

        with mock.patch(
            "hpc_tools.execution.subprocess.run",
            return_value=completed,
        ) as run:
            result = service.probe()

        self.assertTrue(result.ok)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ("ssh", "-x", "gjb@genius"))
        payload = run.call_args.kwargs["input"]
        helper_length = int.from_bytes(payload[:8], "big")
        self.assertGreater(helper_length, 0)
        request = json.loads(payload[8 + helper_length:].decode("utf-8"))
        self.assertEqual(request["action"], "probe")

    def test_limits_are_finite_positive_values(self) -> None:
        for updates in (
            {"max_bytes": 0},
            {"max_entries": -1},
            {"max_transfer_bytes": 0},
            {"timeout_seconds": 0},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                FilesystemLimits(**updates)


class _LoopbackExecutor(CommandExecutor):
    def __init__(self, name: str) -> None:
        self.name = name

    def build_argv(self, profile, command):
        return LocalExecutor().build_argv(profile, command)


class _ResultExecutor(CommandExecutor):
    name = "result"

    def __init__(self, result) -> None:
        self.result = result

    def build_argv(self, profile, command):
        del profile
        return ["result", command]

    def run_plan_bytes(self, plan, *, input_data, timeout):
        del plan, input_data, timeout
        return self.result


class _FailingExecutor(_ResultExecutor):
    def run_plan_bytes(self, plan, *, input_data, timeout):
        del plan, input_data, timeout
        raise self.result


if __name__ == "__main__":
    unittest.main()
