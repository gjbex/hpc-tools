# WP10 restricted-agent integration

Status: complete on 2026-10-14.

WP10 composes the per-profile capability policy with the existing restricted
agent boundary. It does not enlarge the `slurm-job` MCP preset or replace the
delegation manifest, ownership ledger, resource budgets, expiry, parent-job
identity, evidence chain, or container boundary.

## Authority model

An initial controller launch requires C3 (`job-lifecycle`). The launcher and
the restricted MCP server reject a C2 profile before issuing a scheduler
command. The first accepted launch stores one immutable `controller_authority`
event in the protected delegation audit ledger containing:

- the complete profile-policy snapshot and its SHA-256 digest;
- the selected configuration path and its SHA-256 digest; and
- the capture timestamp.

Every controller attempt copies this evidence into its protected provenance
record. Runtime resources expose the policy and digests but omit the private
configuration path.

For new MCP work, effective authority is the intersection of the current
profile policy and the captured ceiling. Registration then filters that result
through the seven fixed `slurm-job` tools and four fixed resources. A narrowed
profile removes newly forbidden tools after restart. A widened profile cannot
restore a scope or root absent from the original capture. General filesystem,
repository, installation, onboarding, and profile-management tools are never
part of the preset.

Requeue, dependent-cleanup registration, and final cleanup are host lifecycle
operations rather than agent tools. They require C3 from the captured
authority. This lets the controller settle jobs it already owns if the editable
profile is narrowed later, without granting any new agent work. Manifest
allowlists, aggregate budgets, exact job ownership, controller generation,
reconciliation, and cancellation idempotency remain independently enforced.

## Restart lifecycle

Each MCP process binds an immutable startup view. Editing a profile does not
alter a running server. On restart, the server reloads the current profile and
intersects it with the original capture. The captured authority itself is
never replaced. A new delegation captures a new ceiling and must again pass
the initial C3 check.

The launcher passes its selected `--config` path explicitly to the host MCP
server. This prevents a different default configuration from being selected at
the launcher/server boundary and makes the recorded configuration digest
meaningful.

## Acceptance evidence

Focused tests cover C2 startup denial, immutable authority capture, restart
under a narrower profile, MCP discovery from the current/captured intersection,
absence of WP9 filesystem tools from `slurm-job`, protected provenance, and the
existing budget, ownership, requeue, draining, cancellation, and cleanup
invariants. No real scheduler job is submitted by these tests.

The focused WP10 slice passed 79 tests with one expected skip. The supported
`.venv` suite passed 432 tests with one skip. Plugin, skill, compilation, and
diff checks passed. The literal system-Python suite remains unavailable because
that interpreter lacks the declared `tomlkit` dependency. Repository hygiene
still reports the pre-existing build, cache, egg-info, and bytecode artifacts.
