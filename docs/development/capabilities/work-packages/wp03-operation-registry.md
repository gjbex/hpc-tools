# WP3 shared operation registry and evaluator

Status: implemented on 2026-10-13. WP3 supplies classification and pure
evaluation. WP5 now applies it at built-in CLI and MCP service boundaries;
profile-aware CLI visibility and MCP discovery remain WP7 and WP8.

## Registry contract

`hpc_tools.operation_registry` is the runtime metadata source for all 72
current operations, including the synchronized WP9 additions. Every descriptor has a stable operation ID, minimum
level, required scopes, effects, selectors, profile requirement, and all CLI,
MCP-tool, and MCP-resource bindings. Descriptors can additionally declare
remote-root selectors, site features, safety guards, and an argument resolver.

Registry construction rejects duplicate operation IDs, duplicate bindings on
one surface, unknown scopes, empty bindings, and missing resolver functions.
Unknown operation IDs are denied rather than treated as unrestricted. This is
the fail-closed boundary for future third-party plugin integration.

Every current CLI leaf has an explicit `operation_id` parser default. The
registry independently binds every full-preset MCP tool and every fixed or
templated resource URI. WP3 does not generate CLI or MCP schemas from metadata;
their existing interface definitions remain responsible for argument shape.

## Request and authorization contexts

`RequestContext` carries an operation ID, interface surface, immutable argument
mapping, and optional bound profile. Its resolver produces typed capability,
path, site-feature, selector, effect, overwrite, component, and safety-guard
metadata without inspecting a generated shell command.

`AuthorizationContext.from_profile` intersects the profile policy with any
additional restrictions and then applies an optional lower requested level.
It also records only safe site-feature identifiers, never configured command
strings or URLs.

The pure evaluator returns an `AuthorizationDecision`. Denials distinguish:

- unknown or unintegrated operation;
- insufficient capability level;
- missing independent scope;
- missing declared root grant for a structured path selector; and
- unavailable site functionality.

Public denial summaries contain safe operation, profile, capability, scope,
root-kind, selector, and feature identifiers. They do not disclose configured
roots, selected paths, SSH identity, URLs, or site command strings.

WP3 performs conservative declaration-level root matching and rejects obvious
traversal or shell syntax. This is not remote filesystem confinement. WP4 must
resolve and revalidate paths on the target host before any filesystem operation
can use an allowed registry decision.

## Argument-sensitive operations

- `submit --test-only` resolves to C2 plus `job.validate`; actual submission
  remains C3. MCP submission additionally retains the quote/account and
  validation scopes and its evidence/confirmation-or-delegation guards.
- Probe output to stdout and an unconfirmed MCP preview need no local-write
  scope; writing a file or bundle requires `local-state.write`.
- `force` records overwrite intent but never removes a required scope.
- Python/R install submission removes only the quote or validation requirement
  corresponding to an explicitly skipped or unavailable step. Remote staging
  always retains `remote-workspace.write`.
- WP5 replaced the compound status resolver with a focused C1 site-status
  operation. Quota, balance, and submission history remain separate registry
  operations.
- Profile, configuration, database, ledger, run, job, and path selectors are
  carried as structured values for later binding checks.

`hpc run` remains operator-only, requires `remote-shell.execute`, and is absent
from MCP bindings. Text such as `sbatch --test-only` inside its command argument
does not change its classification.

## Verification boundary

Focused tests compare all registry metadata with the WP1 inventory, inspect the
actual CLI parser bindings, and compare the MCP tool/resource surfaces. They
also cover duplicate/conflicting registration, unknown-operation denial,
monotonic levels, policy intersection, argument modes, alias consistency,
structured selectors, safe denials, site availability, declared paths, and the
absence of shell-command inference. Complete-suite evidence is recorded in
the [capability implementation plan](../implementation-plan.md).
