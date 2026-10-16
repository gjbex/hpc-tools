from __future__ import annotations

import contextlib
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

from hpc_tools.capabilities import CapabilityLevel, CapabilityPolicy, RemoteRootGrants
from hpc_tools.cli import main
from hpc_tools.config import ConfigError, load_config, resolve_profile
from hpc_tools.execution import executor_scope
from hpc_tools.hardware import render_hardware_context
from hpc_tools.mcp.tools import (
    hpc_files_list,
    hpc_files_read,
    hpc_files_remove,
    hpc_files_upload,
)
from hpc_tools.references import (
    create_reference_set,
    export_reference_set,
    import_reference_set,
    set_profile_reference_set,
)
from test_cli_fixtures import make_profile


class _StatusHandler(BaseHTTPRequestHandler):
    requests = 0

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        type(self).requests += 1
        payload = b"<html><body><h1>Fake center operational</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class CapabilityAcceptanceTests(unittest.TestCase):
    def test_c0_administrator_reference_handoff_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            admin_root = root / "administrator"
            user_root = root / "user"
            admin_config = self._write_reference_publisher(admin_root)
            admin_profile = resolve_profile(load_config(str(admin_config)), "publisher")

            with mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": str(admin_root)}, clear=False
            ):
                create_reference_set("example-center-2026", admin_profile)
                archive = export_reference_set(
                    "example-center-2026",
                    output=root / "example-center-2026-reference-set.tar.gz",
                )

            user_config = self._write_context_consumer(user_root)
            with mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": str(user_root)}, clear=False
            ), mock.patch("hpc_tools.execution.subprocess.run") as remote, mock.patch(
                "hpc_tools.commands.slurm.urlopen"
            ) as http, mock.patch(
                "hpc_tools.mcp.common.run_command_capture"
            ) as scheduler:
                imported = import_reference_set(archive)
                set_profile_reference_set(
                    user_config,
                    "context",
                    imported.name,
                )
                profile = resolve_profile(load_config(str(user_config)), "context")
                rendered = render_hardware_context(profile)

            self.assertIn("Administrator hardware reference", rendered)
            self.assertIn("Administrator Slurm reference", rendered)
            self.assertIn("Administrator storage reference", rendered)
            self.assertEqual(profile.target, None)
            remote.assert_not_called()
            http.assert_not_called()
            scheduler.assert_not_called()

    def test_c1_filesystem_grants_are_independent_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            list_root = root / "list"
            read_root = root / "read"
            write_root = root / "write"
            delete_root = root / "delete"
            for path in (list_root, read_root, write_root, delete_root):
                path.mkdir()
            (list_root / "visible.txt").write_text("listed", encoding="utf-8")
            readable = read_root / "readable.txt"
            readable.write_text("readable", encoding="utf-8")
            removable = delete_root / "removable.txt"
            removable.write_text("remove", encoding="utf-8")
            source = root / "job.slurm"
            source.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")

            base = make_profile()
            profile = replace(
                base,
                target=None,
                host=None,
                user=None,
                capabilities=CapabilityPolicy(
                    version=1,
                    max_level=CapabilityLevel.CLUSTER_DISCOVERY,
                    scopes=(
                        "remote-filesystem.list",
                        "remote-filesystem.read",
                        "remote-workspace.write",
                        "remote-workspace.delete",
                    ),
                    remote_roots=RemoteRootGrants(
                        list=(str(list_root),),
                        read=(str(read_root),),
                        write=(str(write_root),),
                        delete=(str(delete_root),),
                    ),
                ),
            )

            with executor_scope("local"), mock.patch(
                "hpc_tools.mcp.tools._resolve_profile", return_value=profile
            ):
                listing = hpc_files_list(str(list_root))
                read = hpc_files_read(str(readable))
                staged = hpc_files_upload(
                    str(source),
                    str(write_root / "job.slurm"),
                    dry_run=False,
                    confirm=True,
                )
                removed = hpc_files_remove(
                    str(removable), dry_run=False, confirm=True
                )

                denied_calls = (
                    ("list", lambda: hpc_files_list(str(read_root))),
                    ("read", lambda: hpc_files_read(str(list_root / "visible.txt"))),
                    (
                        "write",
                        lambda: hpc_files_upload(
                            str(source),
                            str(read_root / "job.slurm"),
                            dry_run=False,
                            confirm=True,
                        ),
                    ),
                    (
                        "delete",
                        lambda: hpc_files_remove(
                            str(write_root / "job.slurm"),
                            dry_run=False,
                            confirm=True,
                        ),
                    ),
                )
                for grant, operation in denied_calls:
                    with self.subTest(grant=grant), self.assertRaisesRegex(
                        ConfigError, f"no declared {grant} root"
                    ):
                        operation()

            self.assertIn(
                "visible.txt", {entry["name"] for entry in listing["entries"]}
            )
            self.assertEqual(read["content"], "readable")
            self.assertTrue(staged["executed"])
            self.assertTrue((write_root / "job.slurm").is_file())
            self.assertEqual(removed["kind"], "file")
            self.assertFalse(removable.exists())

    def test_fake_ssh_http_and_slurm_endpoints_preserve_c2_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            ssh_log = root / "ssh.log"
            slurm_log = root / "slurm.log"

            self._write_executable(
                bin_dir / "ssh",
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$FAKE_SSH_LOG"\n'
                'printf "fake-login\\n"\n',
            )
            self._write_executable(
                bin_dir / "squeue",
                "#!/bin/sh\n"
                'printf "squeue %s\\n" "$*" >> "$FAKE_SLURM_LOG"\n'
                'printf "123 fake-partition fake-job RUNNING\\n"\n',
            )
            self._write_executable(
                bin_dir / "sbatch",
                "#!/bin/sh\n"
                'printf "sbatch %s\\n" "$*" >> "$FAKE_SLURM_LOG"\n'
                'case " $* " in *" --test-only "*) '
                'printf "sbatch: Job 1 to start later\\n";; '
                '*) printf "unexpected real submission\\n" >&2; exit 97;; esac\n',
            )
            self._write_executable(
                bin_dir / "scancel",
                "#!/bin/sh\n"
                'printf "scancel %s\\n" "$*" >> "$FAKE_SLURM_LOG"\n'
                "exit 98\n",
            )

            _StatusHandler.requests = 0
            server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                config = self._write_transport_config(root, server.server_port)
                environment = {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "FAKE_SSH_LOG": str(ssh_log),
                    "FAKE_SLURM_LOG": str(slurm_log),
                }
                with mock.patch.dict(os.environ, environment, clear=False), \
                        contextlib.redirect_stdout(io.StringIO()) as stdout, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        main(["--config", str(config), "--profile", "discovery", "doctor"]),
                        0,
                    )
                    self.assertEqual(
                        main(["--config", str(config), "--profile", "discovery", "status"]),
                        0,
                    )
                    self.assertEqual(
                        main(
                            [
                                "--config",
                                str(config),
                                "--profile",
                                "inspect",
                                "--executor",
                                "local",
                                "jobs",
                            ]
                        ),
                        0,
                    )
                    self.assertEqual(
                        main(
                            [
                                "--config",
                                str(config),
                                "--profile",
                                "inspect",
                                "--executor",
                                "local",
                                "submit",
                                "job.slurm",
                                "--test-only",
                            ]
                        ),
                        0,
                    )
                    for denied in (
                        ["submit", "job.slurm"],
                        ["submit", "job.slurm", "--validate-first"],
                        ["cancel", "123"],
                    ):
                        self.assertEqual(
                            main(
                                [
                                    "--config",
                                    str(config),
                                    "--profile",
                                    "inspect",
                                    "--executor",
                                    "local",
                                    "--json",
                                    *denied,
                                ]
                            ),
                            2,
                        )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(_StatusHandler.requests, 1)
            self.assertIn("Fake center operational", stdout.getvalue())
            self.assertTrue(ssh_log.is_file())
            self.assertIn("hostname; whoami; pwd", ssh_log.read_text(encoding="utf-8"))
            slurm_calls = slurm_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(sum(line.startswith("squeue ") for line in slurm_calls), 1)
            self.assertEqual(sum(line.startswith("sbatch --test-only") for line in slurm_calls), 1)
            self.assertFalse(any(line.startswith("scancel ") for line in slurm_calls))
            self.assertFalse(
                any(
                    line.startswith("sbatch ") and "--test-only" not in line
                    for line in slurm_calls
                )
            )

    def _write_reference_publisher(self, root: Path) -> Path:
        profile_dir = root / "hpc-tools" / "profiles" / "publisher"
        profile_dir.mkdir(parents=True)
        references = {
            "hardware": "# Administrator hardware reference\n",
            "slurm": "# Administrator Slurm reference\n",
            "storage": "# Administrator storage reference\n",
        }
        for name, contents in references.items():
            (profile_dir / f"{name}.md").write_text(contents, encoding="utf-8")
        config = root / "hpc-tools" / "config.toml"
        config.write_text(
            textwrap.dedent(
                f"""
                [profiles.publisher]
                hardware_reference = "{profile_dir / 'hardware.md'}"
                slurm_reference = "{profile_dir / 'slurm.md'}"
                storage_reference = "{profile_dir / 'storage.md'}"

                [profiles.publisher.capabilities]
                version = 1
                max_level = "profile-context"
                scopes = ["local-state.write"]
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config

    def _write_context_consumer(self, root: Path) -> Path:
        config = root / "hpc-tools" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            textwrap.dedent(
                """
                default_profile = "context"

                [profiles.context]

                [profiles.context.capabilities]
                version = 1
                max_level = "profile-context"
                scopes = ["local-state.write"]
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config

    def _write_transport_config(self, root: Path, port: int) -> Path:
        config = root / "config.toml"
        config.write_text(
            textwrap.dedent(
                f"""
                [profiles.discovery]
                ssh_target = "fake-login"
                status_url = "http://127.0.0.1:{port}/status"

                [profiles.discovery.capabilities]
                version = 1
                max_level = "cluster-discovery"

                [profiles.inspect]
                login_shell = ["sh", "-c"]
                default_cluster = "fake"

                [profiles.inspect.capabilities]
                version = 1
                max_level = "job-inspection"
                scopes = ["job.validate"]
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config

    def _write_executable(self, path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
