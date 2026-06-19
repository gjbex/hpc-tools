from __future__ import annotations

import contextlib
import io
import tempfile
import textwrap
import tarfile
import unittest
from pathlib import Path
from unittest import mock

from hpc_tools.config import load_config, resolve_profile
from hpc_tools.hardware import render_hardware_context
from hpc_tools.references import (
    create_reference_set,
    export_reference_set,
    format_reference_set,
    import_reference_set,
    list_reference_sets,
    load_reference_set,
    set_profile_reference_set,
)


class ReferenceSetTests(unittest.TestCase):
    def test_create_reference_set_copies_profile_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            profile = resolve_profile(load_config(str(config_path)), "genius")

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                reference_set = create_reference_set("kuleuven-tier2", profile)

            self.assertTrue(reference_set.hardware_reference.exists())
            self.assertTrue(reference_set.slurm_reference.exists())
            self.assertTrue(reference_set.storage_reference.exists())
            self.assertTrue(reference_set.probe_hardware_report.exists())
            self.assertIn(
                "format_version = 1",
                (reference_set.path / "manifest.toml").read_text(encoding="utf-8"),
            )
            self.assertIn("source_profile: genius", format_reference_set(reference_set))
            self.assertIn("status_url: https://status.example.org/", format_reference_set(reference_set))

    def test_export_and_import_reference_set_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            profile = resolve_profile(load_config(str(config_path)), "genius")

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                create_reference_set("kuleuven-tier2", profile)
                archive_path = export_reference_set(
                    "kuleuven-tier2",
                    output=root / "kuleuven-tier2-reference-set.tar.gz",
                )

                imported_root = root / "imported-xdg"
                with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(imported_root)}, clear=True):
                    imported = import_reference_set(archive_path)
                    listed = list_reference_sets()

            self.assertEqual(imported.name, "kuleuven-tier2")
            self.assertEqual(imported.status_url, "https://status.example.org/")
            self.assertEqual([reference_set.name for reference_set in listed], ["kuleuven-tier2"])

    def test_render_hardware_context_prefers_attached_reference_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                profile = resolve_profile(load_config(str(config_path)), "genius")
                create_reference_set("kuleuven-tier2", profile)
                set_profile_reference_set(config_path, "genius", "kuleuven-tier2")
                attached_profile = resolve_profile(load_config(str(config_path)), "genius")

                paths = render_hardware_context(attached_profile, path_only=True)

            self.assertIn("reference_set: kuleuven-tier2", paths)
            self.assertIn("reference-sets/kuleuven-tier2/hardware.md", paths)

    def test_showing_missing_reference_set_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}, clear=True):
                with self.assertRaisesRegex(ValueError, "reference set manifest not found"):
                    load_reference_set("missing")

    def test_set_profile_reference_set_escapes_toml_strings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            value = 'weird"name\\set'

            set_profile_reference_set(config_path, "genius", value)
            config = load_config(str(config_path))

        self.assertEqual(resolve_profile(config, "genius").reference_set, value)

    def test_set_profile_reference_set_preserves_existing_toml_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            original = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                original.replace(
                    '[profiles.genius]\n',
                    '[profiles.genius]\n# operator-owned profile notes\n',
                ),
                encoding="utf-8",
            )

            set_profile_reference_set(config_path, "genius", "baseline")
            updated = config_path.read_text(encoding="utf-8")

        self.assertIn("# operator-owned profile notes", updated)
        self.assertIn('reference_set = "baseline"', updated)

    def test_import_reference_set_rejects_symlink_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            profile = resolve_profile(load_config(str(config_path)), "genius")
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                create_reference_set("kuleuven-tier2", profile)

                archive_path = root / "bad-reference-set.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    top = tarfile.TarInfo("bad-set")
                    top.type = tarfile.DIRTYPE
                    archive.addfile(top)
                    link = tarfile.TarInfo("bad-set/hardware.md")
                    link.type = tarfile.SYMTYPE
                    link.linkname = "/etc/passwd"
                    archive.addfile(link)

                with self.assertRaisesRegex(ValueError, "unsupported archive member type"):
                    import_reference_set(archive_path)

    def _write_config(self, root: Path) -> Path:
        profile_dir = root / "hpc-tools" / "profiles" / "genius"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "hardware.md").write_text("# hardware\n", encoding="utf-8")
        (profile_dir / "slurm.md").write_text("# slurm\n", encoding="utf-8")
        (profile_dir / "storage.md").write_text("# storage\n", encoding="utf-8")
        (profile_dir / "probe-hardware-report.md").write_text("# probe\n", encoding="utf-8")

        config_path = root / "hpc-tools" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            textwrap.dedent(
                f"""
                default_profile = "genius"

                [profiles.genius]
                ssh_target = "genius"
                hardware_reference = "{profile_dir / 'hardware.md'}"
                hardware_url = "https://example.org/hardware"
                slurm_reference = "{profile_dir / 'slurm.md'}"
                slurm_url = "https://example.org/slurm"
                storage_reference = "{profile_dir / 'storage.md'}"
                storage_url = "https://example.org/storage"
                status_url = "https://status.example.org/"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return config_path


if __name__ == "__main__":
    unittest.main()
