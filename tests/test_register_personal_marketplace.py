from __future__ import annotations

import importlib.util
import json
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
                            "path": str(plugin_root),
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


if __name__ == "__main__":
    unittest.main()
