from __future__ import annotations

import configparser
import json
from pathlib import Path
import unittest

from capability_snapshot import current_surface_snapshot, full_mcp_input_schemas


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CapabilityInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_fixture("capability_inventory.json")
        cls.surface = load_fixture("capability_surface_snapshot.json")

    def test_current_cli_mcp_and_console_snapshot_is_synchronized(self) -> None:
        self.assertEqual(current_surface_snapshot(), self.surface)
        self.assertIn("update intentionally", self.surface["snapshot_semantics"])

    def test_fastmcp_discovery_schemas_are_stable(self) -> None:
        expected = load_fixture("capability_mcp_schema_snapshot.json")
        self.assertEqual(full_mcp_input_schemas(), expected)

    def test_inventory_covers_every_cli_mcp_and_resource_binding_once(self) -> None:
        operations = self.inventory["operations"]
        expected_cli = {
            name
            for name, schema in self.surface["cli"].items()
            if schema["handler"] is not None
        }
        expected_mcp = set(self.surface["mcp_full"])
        expected_resources = {
            resource
            for resources in self.surface["resources"].values()
            for resource in resources
        }

        for field, expected in (
            ("cli", expected_cli),
            ("mcp", expected_mcp),
            ("resources", expected_resources),
        ):
            bindings = [binding for item in operations for binding in item[field]]
            self.assertEqual(set(bindings), expected, field)
            self.assertEqual(len(bindings), len(set(bindings)), field)

    def test_inventory_records_registry_inputs_without_enforcing_them(self) -> None:
        self.assertEqual(self.inventory["format_version"], 1)
        self.assertIn("not runtime authorization", self.inventory["purpose"])
        self.assertIn("current effects", self.inventory["effects_are"])
        operations = self.inventory["operations"]
        ids = [item["id"] for item in operations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            {item["proposed_level"] for item in operations},
            {"C0", "C1", "C2", "C3", "operator"},
        )
        expected_fields = {
            "id", "cli", "mcp", "resources", "proposed_level",
            "proposed_scopes", "current_effects", "selectors", "notes", "modes",
        }
        for item in operations:
            self.assertEqual(set(item), expected_fields, item["id"])
            self.assertTrue(item["cli"] or item["mcp"] or item["resources"], item["id"])
            self.assertTrue(item["current_effects"], item["id"])
            for mode in item["modes"]:
                self.assertTrue(
                    {"name", "when", "level", "scopes", "effects"}.issubset(mode),
                    (item["id"], mode),
                )

    def test_inventory_tracks_all_packaged_console_scripts(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(ROOT / "setup.cfg", encoding="utf-8")
        configured = {}
        for line in parser["options.entry_points"]["console_scripts"].splitlines():
            if line.strip():
                name, entry = line.split("=", maxsplit=1)
                configured[name.strip()] = entry.strip()

        inventoried = {
            item["name"]: item["entry"]
            for item in self.inventory["consoles"]
        }
        self.assertEqual(configured, self.surface["console_entry_points"])
        self.assertEqual(inventoried, configured)

    def test_compound_dynamic_and_pre_policy_exceptions_remain_explicit(self) -> None:
        operations = {item["id"]: item for item in self.inventory["operations"]}
        for operation in ("probe.write", "job.submit", "python.submit-install", "r.submit-install"):
            self.assertTrue(operations[operation]["modes"], operation)
        self.assertIn("cluster.status", operations)
        self.assertIn("remote.shell", operations)
        self.assertEqual(operations["remote.shell"]["proposed_level"], "operator")
        self.assertEqual(
            operations["remote.shell"]["proposed_scopes"],
            ["remote-shell.execute"],
        )
        no_config = self.surface["pre_policy_no_config_examples"]
        self.assertTrue(no_config["root-help"])
        self.assertTrue(no_config["submissions-mark"])
        self.assertFalse(no_config["submissions-observe"])
        self.assertFalse(no_config["python-check"])


if __name__ == "__main__":
    unittest.main()
