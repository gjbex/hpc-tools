#!/usr/bin/env python3
"""Run the dependency-complete capability acceptance regression tier."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

SCENARIOS: dict[str, tuple[str, ...]] = {
    "c0-reference-handoff": (
        "test_capability_acceptance.CapabilityAcceptanceTests."
        "test_c0_administrator_reference_handoff_is_offline",
    ),
    "c1-bounded-files": (
        "test_capability_acceptance.CapabilityAcceptanceTests."
        "test_c1_filesystem_grants_are_independent_and_bounded",
        "test_file_operations.FileOperationTests."
        "test_mcp_single_file_round_trip_and_empty_directory_removal",
        "test_file_operations.FileOperationTests."
        "test_read_without_read_grant_is_denied_before_execution",
        "test_file_operations.FileOperationTests."
        "test_mcp_discovery_separates_file_grants_from_job_level",
    ),
    "c2-observe-and-preflight": (
        "test_capability_acceptance.CapabilityAcceptanceTests."
        "test_fake_ssh_http_and_slurm_endpoints_preserve_c2_ceiling",
        "test_builtin_authorization.BuiltinAuthorizationTests."
        "test_c2_job_validation_scope_allows_test_only_preview",
        "test_builtin_authorization.BuiltinAuthorizationTests."
        "test_c2_profile_cannot_submit_or_log",
        "test_builtin_authorization.BuiltinAuthorizationTests."
        "test_c2_profile_cannot_cancel_or_log",
    ),
    "c3-evidence-chain": (
        "test_mcp_submit.McpServerFeatureTests."
        "test_submit_job_executes_and_logs_with_matching_evidence",
        "test_mcp_submit.McpServerFeatureTests."
        "test_submit_job_refuses_missing_account_quote_validation_or_confirmation",
        "test_mcp_submit.McpServerFeatureTests."
        "test_submit_job_rejects_dry_run_or_tampered_evidence",
        "test_mcp_submit.McpServerFeatureTests."
        "test_submit_job_rejects_stale_quote_evidence",
    ),
    "cli-discovery-and-denial": (
        "test_cli_core.CliCoreTests.test_policy_filtered_help_hides_denied_commands",
        "test_cli_core.CliCoreTests."
        "test_hidden_direct_invocation_returns_structured_json_denial",
        "test_cli_core.CliCoreTests."
        "test_display_ceiling_does_not_reduce_execution_authority",
    ),
    "mcp-binding-and-restart": (
        "test_mcp_registry.McpServerFeatureTests."
        "test_profile_policy_filters_discovery_and_is_snapshotted",
        "test_mcp_registry.McpServerFeatureTests."
        "test_bound_reference_visibility_is_limited_to_attached_set",
    ),
    "plugin-contract": (
        "test_plugin_contract.PluginContractTests."
        "test_denied_install_submissions_have_no_effects",
        "test_plugin_contract.PluginContractTests."
        "test_unknown_contract_version_is_rejected_and_omitted",
        "test_plugin_contract.PluginContractTests."
        "test_undeclared_registered_leaf_is_rejected_and_omitted",
    ),
    "restricted-agent-intersection": (
        "test_mcp_registry.McpServerFeatureTests."
        "test_restarted_slurm_job_server_intersects_current_and_captured_policy",
        "test_mcp_registry.McpServerFeatureTests."
        "test_slurm_job_registry_is_a_narrow_fixed_surface",
        "test_restricted_boundary.RestrictedBoundaryTests."
        "test_launcher_registers_one_host_cleanup_job",
        "test_restricted_boundary.RestrictedBoundaryTests."
        "test_launcher_requeues_only_the_bound_parent_and_records_result",
    ),
    "invalid-policy-fails-closed": (
        "test_config.ConfigTests."
        "test_rejects_missing_empty_and_invalid_capability_blocks",
        "test_config.ConfigTests."
        "test_loading_policy_has_no_external_effects_or_file_writes",
    ),
}


def main() -> int:
    sys.path.insert(0, str(TESTS))
    names = [name for tests in SCENARIOS.values() for name in tests]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    print(
        f"capability acceptance: {len(SCENARIOS)} scenarios, "
        f"{suite.countTestCases()} tests",
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
