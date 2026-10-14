from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from hpc_tools.capabilities import (
    AuthorizationContext,
    CapabilityLevel,
    CapabilityPolicy,
    DenialCode,
    RemoteRootGrants,
    intersect_policies,
)
from hpc_tools.cli import build_parser
from hpc_tools.mcp import server as mcp_server
from hpc_tools.operation_registry import (
    OPERATION_REGISTRY,
    OperationDescriptor,
    OperationRegistry,
    OperationSurface,
    RegistryError,
    RequestContext,
)


ROOT = Path(__file__).resolve().parents[1]


class OperationRegistryTests(unittest.TestCase):
    def test_registry_matches_every_wp1_descriptor(self) -> None:
        inventory = json.loads(
            (ROOT / "tests/fixtures/capability_inventory.json").read_text(
                encoding="utf-8"
            )
        )
        expected_levels = {
            "C0": CapabilityLevel.PROFILE_CONTEXT,
            "C1": CapabilityLevel.CLUSTER_DISCOVERY,
            "C2": CapabilityLevel.JOB_INSPECTION,
            "C3": CapabilityLevel.JOB_LIFECYCLE,
            "operator": CapabilityLevel.JOB_LIFECYCLE,
        }
        self.assertEqual(len(OPERATION_REGISTRY.operations), 65)
        self.assertEqual(
            {operation.id for operation in OPERATION_REGISTRY.operations},
            {item["id"] for item in inventory["operations"]},
        )
        for item in inventory["operations"]:
            with self.subTest(operation=item["id"]):
                operation = OPERATION_REGISTRY.require(item["id"])
                self.assertIs(operation.minimum_level, expected_levels[item["proposed_level"]])
                self.assertEqual(operation.scopes, tuple(item["proposed_scopes"]))
                self.assertEqual(operation.effects, tuple(item["current_effects"]))
                self.assertEqual(operation.cli, tuple(item["cli"]))
                self.assertEqual(operation.mcp, tuple(item["mcp"]))
                self.assertEqual(operation.resources, tuple(item["resources"]))
                self.assertEqual(operation.selectors, tuple(item["selectors"]))
                self.assertEqual(operation.operator_only, item["proposed_level"] == "operator")

    def test_every_cli_leaf_is_explicitly_bound_to_its_descriptor(self) -> None:
        with mock.patch(
            "hpc_tools.plugin_system._iter_plugin_entry_points",
            return_value=[],
        ):
            parser = build_parser()
        leaves = _cli_leaves(parser)
        expected = set(OPERATION_REGISTRY.bindings(OperationSurface.CLI))
        self.assertEqual(set(leaves), expected)
        for command, child in leaves.items():
            with self.subTest(command=command):
                operation_id = child.get_default("operation_id")
                self.assertIsNotNone(operation_id)
                self.assertEqual(
                    OPERATION_REGISTRY.require(operation_id),
                    OPERATION_REGISTRY.for_binding(OperationSurface.CLI, command),
                )

    def test_mcp_tools_and_resources_have_one_registry_binding(self) -> None:
        self.assertEqual(
            set(OPERATION_REGISTRY.bindings(OperationSurface.MCP_TOOL)),
            set(mcp_server.FULL_TOOL_NAMES),
        )
        resources = {
            *mcp_server.FULL_RESOURCE_URIS,
            *mcp_server.FULL_RESOURCE_TEMPLATES,
            *mcp_server.SLURM_JOB_RESOURCE_URIS,
            *mcp_server.SLURM_JOB_RESOURCE_TEMPLATES,
        }
        self.assertEqual(
            set(OPERATION_REGISTRY.bindings(OperationSurface.MCP_RESOURCE)),
            resources,
        )

    def test_registry_rejects_duplicate_ids_and_conflicting_bindings(self) -> None:
        first = _descriptor("one", cli=("same",))
        with self.assertRaisesRegex(RegistryError, "duplicate operation id"):
            OperationRegistry((first, first))
        with self.assertRaisesRegex(RegistryError, "conflicting cli binding"):
            OperationRegistry((first, _descriptor("two", cli=("same",))))

    def test_unknown_or_unintegrated_operation_is_denied(self) -> None:
        decision = OPERATION_REGISTRY.authorize(
            _request("external.plugin", OperationSurface.SERVICE),
            _context(_policy("job-lifecycle", scopes=ALL_SCOPES)),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.denials[0].code, DenialCode.UNKNOWN_OPERATION)

    def test_level_is_monotonic_when_scopes_are_fixed(self) -> None:
        request = _request("job.list", OperationSurface.CLI)
        outcomes = []
        for level in (
            "profile-context",
            "cluster-discovery",
            "job-inspection",
            "job-lifecycle",
        ):
            outcomes.append(
                OPERATION_REGISTRY.authorize(
                    request,
                    _context(_policy(level, scopes=ALL_SCOPES)),
                ).allowed
            )
        self.assertEqual(outcomes, [False, False, True, True])

    def test_intersection_never_supplies_a_scope_from_only_one_policy(self) -> None:
        profile = _policy(
            "job-inspection",
            scopes=("job.validate", "accounting.read"),
        )
        preset = _policy("job-inspection", scopes=("job.validate",))
        context = _context(intersect_policies(profile, preset))

        decision = OPERATION_REGISTRY.authorize(
            _request("job.quote", OperationSurface.CLI),
            context,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.denials[0].code, DenialCode.MISSING_SCOPE)
        self.assertEqual(decision.denials[0].missing_scopes, ("accounting.read",))

    def test_submit_test_only_is_c2_but_actual_submission_is_c3(self) -> None:
        context = _context(
            _policy("job-inspection", scopes=("job.validate",))
        )
        test_only = OPERATION_REGISTRY.authorize(
            _request(
                "job.submit",
                OperationSurface.CLI,
                test_only=True,
                validate_first=True,
            ),
            context,
        )
        actual = OPERATION_REGISTRY.authorize(
            _request("job.submit", OperationSurface.CLI, test_only=False),
            context,
        )

        self.assertTrue(test_only.allowed)
        self.assertFalse(actual.allowed)
        self.assertEqual(actual.denials[0].code, DenialCode.MISSING_LEVEL)

    def test_mcp_submission_retains_preflight_and_account_scopes(self) -> None:
        resolved = OPERATION_REGISTRY.resolve(
            _request("job.submit", OperationSurface.MCP_TOOL, confirm=True)
        )
        self.assertIs(resolved.requirement.minimum_level, CapabilityLevel.JOB_LIFECYCLE)
        self.assertEqual(
            resolved.requirement.scopes,
            ("accounting.read", "job.validate"),
        )
        self.assertEqual(
            resolved.safety_guards,
            (
                "confirmation-or-delegation",
                "quote-evidence",
                "validation-evidence",
            ),
        )

    def test_aliases_resolve_to_one_operation_and_requirements(self) -> None:
        write = OPERATION_REGISTRY.for_binding(OperationSurface.CLI, "write-probe")
        hardware = OPERATION_REGISTRY.for_binding(
            OperationSurface.CLI,
            "write-hardware-probe",
        )
        self.assertIs(write, hardware)
        self.assertEqual(write.id, "probe.write")
        self.assertIs(
            OPERATION_REGISTRY.for_binding(OperationSurface.CLI, "install-probe"),
            OPERATION_REGISTRY.for_binding(
                OperationSurface.CLI,
                "install-hardware-probe",
            ),
        )

    def test_probe_stdout_and_mcp_preview_do_not_require_local_write(self) -> None:
        stdout = OPERATION_REGISTRY.resolve(
            _request("probe.write", OperationSurface.CLI, output="-", force=True)
        )
        file_write = OPERATION_REGISTRY.resolve(
            _request("probe.write", OperationSurface.CLI, output="probe.slurm")
        )
        preview = OPERATION_REGISTRY.resolve(
            _request(
                "probe.write",
                OperationSurface.MCP_TOOL,
                output="probe.slurm",
                confirm=False,
            )
        )
        self.assertEqual(stdout.requirement.scopes, ())
        self.assertEqual(preview.requirement.scopes, ())
        self.assertEqual(file_write.requirement.scopes, ("local-state.write",))

    def test_force_records_overwrite_without_removing_required_scope(self) -> None:
        resolved = OPERATION_REGISTRY.resolve(
            _request(
                "references.export",
                OperationSurface.CLI,
                force=True,
                output="archive.tar.gz",
            )
        )
        self.assertTrue(resolved.overwrite_requested)
        self.assertEqual(resolved.requirement.scopes, ("local-state.write",))

    def test_path_and_site_denials_are_distinct_and_safe(self) -> None:
        path_decision = OPERATION_REGISTRY.authorize(
            _request(
                "filesystem.inspect",
                OperationSurface.CLI,
                path="/project/group",
            ),
            _context(
                _policy(
                    "cluster-discovery",
                    scopes=("remote-filesystem.list",),
                )
            ),
        )
        site_decision = OPERATION_REGISTRY.authorize(
            _request("cluster.quota", OperationSurface.CLI),
            _context(_policy("cluster-discovery")),
        )

        self.assertEqual(path_decision.denials[0].code, DenialCode.MISSING_PATH_GRANT)
        self.assertNotIn("/project/group", str(path_decision.public_summary()))
        self.assertEqual(
            site_decision.denials[0].code,
            DenialCode.SITE_FUNCTION_UNAVAILABLE,
        )

    def test_declared_path_grant_allows_a_descendant_at_registry_stage(self) -> None:
        policy = _policy(
            "cluster-discovery",
            scopes=("remote-filesystem.list",),
            roots=RemoteRootGrants(list=("/project",)),
        )
        decision = OPERATION_REGISTRY.authorize(
            _request(
                "filesystem.inspect",
                OperationSurface.CLI,
                path="/project/group",
            ),
            _context(policy),
        )
        self.assertTrue(decision.allowed)

    def test_registry_path_check_rejects_obvious_traversal_before_wp4(self) -> None:
        policy = _policy(
            "cluster-discovery",
            scopes=("remote-filesystem.list",),
            roots=RemoteRootGrants(list=("/project",)),
        )
        decision = OPERATION_REGISTRY.authorize(
            _request(
                "filesystem.inspect",
                OperationSurface.CLI,
                path="/project/../private",
            ),
            _context(policy),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.denials[0].code, DenialCode.MISSING_PATH_GRANT)

    def test_site_status_is_a_focused_c1_operation(self) -> None:
        resolved = OPERATION_REGISTRY.resolve(
            _request("cluster.status", OperationSurface.CLI)
        )
        self.assertEqual(resolved.components, ())
        self.assertIs(
            resolved.requirement.minimum_level,
            CapabilityLevel.CLUSTER_DISCOVERY,
        )
        self.assertEqual(resolved.requirement.scopes, ())
        self.assertEqual(resolved.requirement.site_features, ("status-page",))

    def test_install_submission_modes_only_remove_skipped_requirements(self) -> None:
        profile = SimpleNamespace(sam_quote_command="sam-quote")
        full = OPERATION_REGISTRY.resolve(
            _request(
                "python.submit-install",
                OperationSurface.CLI,
                bound_profile=profile,
                directory="/project",
            )
        )
        skip_both = OPERATION_REGISTRY.resolve(
            _request(
                "python.submit-install",
                OperationSurface.CLI,
                bound_profile=profile,
                directory="/project",
                skip_quote=True,
                no_validate_first=True,
            )
        )
        self.assertEqual(
            full.requirement.scopes,
            ("accounting.read", "job.validate", "remote-workspace.write"),
        )
        self.assertEqual(skip_both.requirement.scopes, ("remote-workspace.write",))

    def test_profile_and_state_selectors_are_carried_structurally(self) -> None:
        resolved = OPERATION_REGISTRY.resolve(
            _request(
                "job.cancel",
                OperationSurface.MCP_TOOL,
                profile="cluster-a",
                database="state.sqlite3",
                jobid="42",
            )
        )
        self.assertIn(("profile", "cluster-a"), resolved.selectors)
        self.assertIn(("database", "state.sqlite3"), resolved.selectors)
        self.assertIn(("jobid", "42"), resolved.selectors)

    def test_arbitrary_command_text_cannot_change_operation_requirements(self) -> None:
        resolved = OPERATION_REGISTRY.resolve(
            _request(
                "remote.shell",
                OperationSurface.CLI,
                remote_command="sbatch --test-only job.slurm",
            )
        )
        self.assertTrue(resolved.requirement.operator_only)
        self.assertIs(resolved.requirement.minimum_level, CapabilityLevel.JOB_LIFECYCLE)
        self.assertEqual(resolved.requirement.scopes, ("remote-shell.execute",))

    def test_authorization_context_intersects_and_narrows_profile_policy(self) -> None:
        profile = SimpleNamespace(
            name="cluster",
            capabilities=_policy(
                "job-lifecycle",
                scopes=("job.validate", "accounting.read"),
            ),
            status_url="https://status.example",
            quota_command="quota",
            queue_command=None,
            sam_balance_command="balance",
            sam_statement_command=None,
            sam_quote_command="quote",
            projects_dir=None,
            email=None,
        )
        restriction = _policy("job-inspection", scopes=("job.validate",))
        context = AuthorizationContext.from_profile(
            profile,
            requested_level="cluster-discovery",
            restrictions=(restriction,),
        )
        self.assertIs(context.policy.max_level, CapabilityLevel.CLUSTER_DISCOVERY)
        self.assertEqual(context.policy.scopes, ("job.validate",))
        self.assertEqual(
            context.site_features,
            frozenset({"status-page", "quota", "account-balance", "job-quote"}),
        )

    def test_namespace_context_copies_arguments(self) -> None:
        namespace = argparse.Namespace(test_only=True)
        request = RequestContext.from_namespace(
            "job.submit",
            OperationSurface.CLI,
            namespace,
        )
        namespace.test_only = False
        self.assertTrue(request.arguments["test_only"])


ALL_SCOPES = (
    "accounting.read",
    "config.read.raw",
    "delegation-ledger.read",
    "job.validate",
    "local-state.write",
    "remote-filesystem.list",
    "remote-filesystem.read",
    "remote-install.write",
    "remote-shell.execute",
    "remote-workspace.delete",
    "remote-workspace.write",
    "submission-record.write",
)


def _policy(
    level: str,
    *,
    scopes: tuple[str, ...] = (),
    roots: RemoteRootGrants | None = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        version=1,
        max_level=CapabilityLevel(level),
        scopes=tuple(sorted(scopes)),
        remote_roots=roots or RemoteRootGrants(),
    )


def _context(policy: CapabilityPolicy) -> AuthorizationContext:
    return AuthorizationContext(profile_name="cluster", policy=policy)


def _request(
    operation_id: str,
    surface: OperationSurface,
    *,
    bound_profile=None,
    **arguments,
) -> RequestContext:
    return RequestContext(
        operation_id=operation_id,
        surface=surface,
        arguments=arguments,
        profile=bound_profile,
    )


def _descriptor(
    operation_id: str,
    *,
    cli: tuple[str, ...],
) -> OperationDescriptor:
    return OperationDescriptor(
        id=operation_id,
        minimum_level=CapabilityLevel.PROFILE_CONTEXT,
        scopes=(),
        effects=("local-read",),
        cli=cli,
    )


def _cli_leaves(
    parser: argparse.ArgumentParser,
    prefix: str = "",
) -> dict[str, argparse.ArgumentParser]:
    result: dict[str, argparse.ArgumentParser] = {}
    children = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            children.extend(action.choices.items())
    if parser.get_default("handler") is not None:
        result[prefix] = parser
    for name, child in children:
        result.update(_cli_leaves(child, f"{prefix} {name}".strip()))
    return result


if __name__ == "__main__":
    unittest.main()
