# WP1 capability surface inventory

Status: implemented, characterized, and reconciled with the project's
pre-release/no-compatibility policy on 2026-10-13. This document records the
WP1 inventory; WP5 now enforces its built-in operations at their service
boundaries. CLI visibility and MCP discovery are still handled by later work
packages in the [capability implementation plan](../implementation-plan.md).

## Inventory artifacts

The machine-readable inventory is
`tests/fixtures/capability_inventory.json`.
It now contains 72 operation descriptors covering all 68 built-in CLI
leaf paths, all 39 full-preset MCP tools, and all 10 distinct fixed-resource
or resource-template URIs after the synchronized WP9 additions. Each interface binding occurs exactly once. The
seven restricted `slurm-job` tools are a bound subset of the full tool set;
its four fixed resources are included separately. All six packaged console
scripts are also inventoried.

The current operation counts are 27 C0, 27 C1, 13 C2, four C3, and one
operator-only action. They began as inputs to WP3 and are now enforced by the
shared registry. Thirteen argument-dependent modes are recorded
for probe generation, direct submission, and the Python and R install-submit
workflows.

The inventory records selectors and the union of observed effects. In
particular, it calls out these exceptions rather than treating command names
as sufficient authorization evidence:

- `status` is a compound web, remote, accounting, submission-database read,
  with possible SQLite initialization writes.
- `run` is arbitrary remote shell execution and remains outside cumulative
  C0--C3 grants.
- probe generation can be stdout-only, write a local file, or preview through
  MCP.
- `submit --test-only` differs from actual submission, while the MCP submit
  path additionally requires quote and validation evidence.
- Python and R package checks may execute module and package initialization.
- Python and R install-submit commands stage a remote script before scheduler
  submission and can selectively skip quotation or validation.
- delegated quote, validation, observation, and accounting can mutate private
  staging or ledger state without granting general filesystem-write authority.
- submission-history reads can initialize an existing SQLite database; full
  MCP reads are currently not selected-profile projections.
- `hpc-mcp-bridge serve` can launch its configured local command and is an
  operator transport, not an ordinary cluster-information operation.

## Synchronized current-surface snapshots

`tests/fixtures/capability_surface_snapshot.json`
captures the current built-in CLI parser tree, handler bindings, argument
shape, console parser shape, MCP callable signatures, resource registries, and
representative pre-policy no-config decisions. Collection suppresses user-installed
Python entry points so a developer's environment cannot change the repository
snapshot or run third-party import-time code.

`tests/fixtures/capability_mcp_schema_snapshot.json`
captures the actual FastMCP input schemas advertised for all full-preset tools.
This is distinct from Python function signatures and detects unintended drift
in the discovery surface.

Neither snapshot is a backward-compatibility contract. Later work packages may
remove or rename commands, arguments, tools, resources, and re-export modules.
When they do, the implementation, operation inventory, snapshots,
documentation, examples, and tests must be updated together. The exact-match
tests enforce that synchronization rule rather than preservation of this
pre-policy interface.

The synchronized no-config cases after WP5 are:

| Parses without configuration | Requires configuration before full parsing |
| --- | --- |
| root or subcommand help | no command |
| `paths` | `doctor` and remote core commands |
| stdout probe/container generation without explicit profile/config or mail notification | generation with explicit profile/config or mail notification |
| reference list/show/validate | all reference mutations and export |
| plugin list/info | submissions, agent audit/export, and profile-dependent plugin operations |
| benchmark, C++ scan/generation, Python scan/inspect, and R scan | Python/R check, plan, submit, and verify |

The remaining profile-free entries are deliberate bootstrap or local-analysis
surfaces. Generic help still bypasses configuration even when `--profile` is
present; WP7 will make help and command visibility profile-aware.

## Direct-call and re-export dependencies

Tests currently rely on re-export modules and direct handlers. These are
change-impact sites, not interfaces that must remain available. Later
authorization work must either update them or protect the service/handler
boundary rather than relying only on top-level dispatch:

- `tests/test_cli_fixtures.py` imports `build_parser`, `main`, private command
  builders, and many `cmd_*` handlers from `hpc_tools.cli`; feature modules
  import this fixture with wildcard imports.
- `tests/test_plugin_fixtures.py` imports `build_parser` from `hpc_tools.cli`.
- `tests/test_cli_fixtures.py` and `tests/test_mcp_fixtures.py` import the
  current re-export module `hpc_tools.mcp_server`.
- direct handler calls occur in `test_cli_probes.py`, `test_cli_remote.py`,
  `test_cli_slurm.py`, `test_cxx_plugin.py`, `test_plugin_benchmark.py`,
  `test_python_plugin.py`, and `test_r_plugin.py`, as well as their shared CLI
  fixture.

## Verification

Before adding WP1 tests, the supported `.venv` ran the complete suite as 302
tests passing with one skip. The WP1 regression module adds six fast tests
that compare both synchronized snapshots and prove one-to-one inventory coverage.
No cluster, SSH connection, scheduler, or remote write is used while collecting
or testing these artifacts.

After the final documentation update, the supported `.venv` ran 308 tests: all
passed, with one skip. Plugin and skill validation and the required compilation
command passed. The literal system-`python3` suite was attempted separately but
that interpreter does not contain the required `tomlkit` dependency, producing
22 import errors rather than product-test failures. Repository hygiene remains
blocked by pre-existing `.ruff_cache`, `build`, `hpc_tools.egg-info`, and
`__pycache__` artifacts; they were left untouched because they are unrelated
working-tree state.
