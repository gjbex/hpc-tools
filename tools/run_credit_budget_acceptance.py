#!/usr/bin/env python3
"""Run the delegated quoted-credit budget acceptance regression tier."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

SCENARIOS: dict[str, tuple[str, ...]] = {
    "real-stdio-restricted-bridge": (
        "test_credit_budget_acceptance.CreditBudgetAcceptanceTests."
        "test_real_stdio_bridge_accepts_boundary_and_rejects_next_minor_unit",
    ),
    "fixed-point-policy-boundaries": (
        "test_delegation.DelegationTests."
        "test_credit_budget_inclusive_numeric_boundaries_are_valid",
        "test_delegation.DelegationTests."
        "test_credit_budget_rejects_invalid_or_inconsistent_policy",
    ),
    "independent-count-and-credit-limits": (
        "test_delegation.DelegationTests."
        "test_credit_ledger_enforces_per_job_total_replay_and_release",
        "test_delegation.DelegationTests."
        "test_credit_count_budget_remains_independent_of_zero_cost_quotes",
    ),
    "arrays-and-atomic-concurrency": (
        "test_delegation.DelegationTests."
        "test_array_elements_consume_cumulative_node_budget",
        "test_delegation.DelegationTests."
        "test_concurrent_credit_reservations_cannot_overspend_final_unit",
        "test_delegation.DelegationTests."
        "test_concurrent_count_and_resource_limits_are_atomic",
        "test_delegation.DelegationTests."
        "test_concurrent_duplicate_key_submits_once_and_budget_stays_capped",
    ),
    "expiry-and-controller-restart": (
        "test_delegation.DelegationTests."
        "test_expired_credit_is_rejected_without_a_reservation",
        "test_delegation.DelegationTests."
        "test_controller_requeue_blocks_submission_until_reconciliation",
        "test_delegation.DelegationTests."
        "test_restart_recovers_when_requeue_acceptance_was_not_persisted",
    ),
    "definite-failure-and-uncertain-acceptance": (
        "test_delegation.DelegationTests."
        "test_failed_reservation_releases_budget_and_rejection_is_audited",
        "test_delegation.DelegationTests."
        "test_uncertain_credit_remains_consumed",
        "test_delegation.DelegationTests."
        "test_accepted_submission_recovery_retains_ownership_and_budget",
    ),
    "public-state-and-protected-boundary": (
        "test_mcp_submit.McpServerFeatureTests."
        "test_restricted_submission_records_ownership_and_is_idempotent",
        "test_mcp_registry.McpServerFeatureTests."
        "test_slurm_job_server_loads_host_side_delegation_context",
        "test_restricted_boundary.RestrictedBoundaryTests."
        "test_parent_command_has_only_explicit_bind_modes",
        "test_restricted_boundary.RestrictedBoundaryTests."
        "test_apptainer_like_clean_environment_exposes_no_scheduler_commands",
        "test_agent_audit.AgentAuditTests."
        "test_report_exposes_quote_maxima_without_mutating_the_ledger",
    ),
}


def main() -> int:
    sys.path.insert(0, str(TESTS))
    names = [name for tests in SCENARIOS.values() for name in tests]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    print(
        f"credit-budget acceptance: {len(SCENARIOS)} scenarios, "
        f"{suite.countTestCases()} tests",
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
