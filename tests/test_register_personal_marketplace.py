from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "register_personal_marketplace.py"


def load_module():
    spec = importlib.util.spec_from_file_location("register_personal_marketplace", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegisterPersonalMarketplaceTests(unittest.TestCase):
    def create_plugin(self, plugin_root: Path) -> None:
        manifest = plugin_root / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "hpc-tools"}) + "\n", encoding="utf-8")

    def test_registers_missing_entry(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin_root = tmp_path / "plugins" / "hpc-tools"
            manifest = plugin_root / ".codex-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"name": "hpc-tools"}) + "\n",
                encoding="utf-8",
            )

            marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
            changed = module.register_plugin(plugin_root, marketplace)

            self.assertTrue(changed)
            payload = json.loads(marketplace.read_text(encoding="utf-8"))
            self.assertEqual(payload["name"], "personal")
            self.assertEqual(
                payload["plugins"],
                [
                    {
                        "name": "hpc-tools",
                        "source": {
                            "source": "local",
                            "path": "./plugins/hpc-tools",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            )

    def test_registration_is_idempotent(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin_root = tmp_path / "plugins" / "hpc-tools"
            manifest = plugin_root / ".codex-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"name": "hpc-tools"}) + "\n",
                encoding="utf-8",
            )

            marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
            self.assertTrue(module.register_plugin(plugin_root, marketplace))
            self.assertFalse(module.register_plugin(plugin_root, marketplace))

    def test_repairs_absolute_entry_and_preserves_other_entries_and_metadata(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "hpc-tools"
            self.create_plugin(plugin_root)
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            other = {"name": "another-plugin", "source": "./plugins/another-plugin"}
            payload = {
                "name": "personal",
                "interface": {"displayName": "My plugins"},
                "custom": {"keep": True},
                "plugins": [
                    other,
                    {
                        "name": "hpc-tools",
                        "source": {"source": "local", "path": str(plugin_root)},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity",
                    },
                ],
            }
            module.write_json(marketplace, payload)
            self.assertTrue(module.register_plugin(plugin_root, marketplace))
            payload["plugins"][1]["source"]["path"] = "./plugins/hpc-tools"
            self.assertEqual(json.loads(marketplace.read_text(encoding="utf-8")), payload)
            self.assertFalse(module.register_plugin(plugin_root, marketplace))

    def test_custom_marketplace_roots_and_checkout_locations(self) -> None:
        module = load_module()
        for manifest_location in (".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"):
            with self.subTest(manifest_location=manifest_location), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "team"
                plugin_root = root / "checkouts" / "HPC tools"
                self.create_plugin(plugin_root)
                marketplace = root / manifest_location
                module.register_plugin(plugin_root, marketplace)
                entry = json.loads(marketplace.read_text(encoding="utf-8"))["plugins"][0]
                self.assertEqual(entry["source"]["path"], "./checkouts/HPC tools")
                self.assertEqual((root / entry["source"]["path"]).resolve(), plugin_root.resolve())

    def test_rejects_checkout_outside_root_without_writing_marketplace(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "elsewhere" / "hpc-tools"
            self.create_plugin(plugin_root)
            marketplace = root / "team" / ".agents" / "plugins" / "marketplace.json"
            with self.assertRaisesRegex(ValueError, "outside marketplace root"):
                module.register_plugin(plugin_root, marketplace)
            self.assertFalse(marketplace.exists())

            module.write_json(marketplace, module.default_marketplace())
            before = marketplace.read_bytes()
            with self.assertRaisesRegex(ValueError, "outside marketplace root"):
                module.register_plugin(plugin_root, marketplace)
            self.assertEqual(marketplace.read_bytes(), before)

    def test_rejects_symlink_to_checkout_outside_root(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "elsewhere" / "hpc-tools"
            self.create_plugin(plugin_root)
            marketplace_root = root / "team"
            marketplace_root.mkdir()
            linked = marketplace_root / "hpc-tools"
            linked.symlink_to(plugin_root, target_is_directory=True)
            marketplace = marketplace_root / ".agents" / "plugins" / "marketplace.json"
            with self.assertRaisesRegex(ValueError, "outside marketplace root"):
                module.register_plugin(linked, marketplace)
            self.assertFalse(marketplace.exists())

    def test_rejects_unsupported_marketplace_location(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "hpc-tools"
            self.create_plugin(plugin_root)
            marketplace = root / "catalog" / "marketplace.json"
            with self.assertRaisesRegex(ValueError, "marketplace path must be"):
                module.register_plugin(plugin_root, marketplace)
            self.assertFalse(marketplace.exists())

    def test_cli_resolves_relative_arguments_and_reports_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_plugin(root / "plugins" / "hpc-tools")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "plugins/hpc-tools", "--marketplace-path",
                 ".agents/plugins/marketplace.json"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            entry = json.loads(marketplace.read_text(encoding="utf-8"))["plugins"][0]
            self.assertEqual(entry["source"]["path"], "./plugins/hpc-tools")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "plugins/hpc-tools", "--marketplace-path",
                 "team/.agents/plugins/marketplace.json"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("outside marketplace root", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
