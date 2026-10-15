# Capability implementation plan

Status: WP1--WP4 complete on 2026-10-13, WP5--WP10 complete on 2026-10-14,
and WP11--WP12 complete on 2026-10-15.

Design authority: [Capability model](design.md). This plan implements the
agreed C0--C3 hierarchy, per-profile grants, independent filesystem scopes,
default CLI hiding with optional display, and allowed-only MCP discovery.
It supplements the [MCP server roadmap](../mcp-roadmap.md). The current CLI and MCP
implementations enforce the capability policy. WP12 completes the local and
installed-distribution acceptance package.

## Scope and delivery boundaries

Deliver one policy model shared by CLI and MCP, coverage of existing built-ins
and bundled Python CLI plugins, and bounded remote file operations.  Preserve
Slurm evidence, confirmation, accounting, ownership, and delegation checks.
Policy remains in the ordinary user-editable configuration.

Implement work packages in dependency order.  Each package must leave a
reviewable change with focused validation.  Do not enable a partially guarded
profile through a new preset: until an operation is integrated, omit or deny it
for capability policies. Every profile must declare capability policy; there is
no compatibility branch for configurations that predate this feature.

The project has not been rolled out to users, so current commands, schemas,
configuration shapes, and internal re-exports are inventory inputs rather than
backward-compatibility promises. Intentional changes are allowed when they make
the model safer or clearer. The implementation, generated/discovery schemas,
documentation, examples, and tests must change together.

The scope excludes automatic reference-archive downloads or update catalogs,
new job-control features, arbitrary MCP shell execution, mandatory immutable
configuration, and operating-system confinement of submitted job payloads.
Existing reference create/export/import/attach workflows remain the way to
share administrator-prepared cluster knowledge.

## Current implementation and integration points

The following findings come from the current checkout, not the old roadmap's
implementation-status wording:

| Surface | Current implementation | Required integration |
| --- | --- | --- |
| Profile configuration | `hpc_tools/config.py`: frozen `Profile`, `load_config`, `_parse_profile`, `resolve_profile` | Require and retain one strict policy for every profile |
| CLI grammar and dispatch | `hpc_tools/cli.py`: `build_parser`, `main`, `_build_pre_parser`, `_should_parse_without_config`, `_dispatch_with_executor` | Resolve policy before help and guard calls before handlers produce effects |
| Core command registration | Built-in and Python CLI plugin handlers carry operation IDs and authorize before effects | Finish profile-aware visibility in WP7 |
| Execution | `hpc_tools/execution.py`, `hpc_tools/ssh.py` | Preserve SSH/local selection; carry authorized actions rather than infer permission from shell text |
| Python CLI plugins | Versioned operation metadata covers bundled and external CLI plugins; incompatible or undeclared surfaces are rejected | Keep the public contract synchronized as plugins evolve |
| MCP registration | Registry-derived candidates are filtered against one profile/preset startup snapshot; fixed selected-profile resources replace cross-profile templates | Preserve this boundary as new WP9 tools are added |
| MCP implementation | Bound schemas hide profile/config/database overrides, calls re-authorize against the snapshot, and config/reference/submission context is profile-isolated | Extend the same contract to bounded file operations in WP9 |
| MCP re-export module | `hpc_tools/mcp_server.py` | Update or remove it and its internal test imports together; only the configured console entry point must remain valid |
| Local durable state | Built-in reference, submission, and agent handlers apply scopes; submission reads/mutations are profile-isolated | Apply the plugin contract and finish interface visibility work |
| Restricted agent | `delegation.py`, `restricted_jobs.py`, `restricted_launch.py`, `agent_cleanup.py` | Intersect policy with delegation without expanding the image's surface |
| Packaging | `setup.cfg`, `.codex-plugin/plugin.json`, `.mcp.json` | Keep Python runtime, CLI extensions, and Codex skills distribution separate |

Specific traps to cover:

- `_should_parse_without_config` currently skips configuration for all help
  requests and several local operations.  Profile-aware help and local writes
  must not silently take this path when an applicable profile is selected.
- WP5 removed the compound `build_status_report`: `status` is now only the
  public site-status read, while quota, balance, and submissions remain
  independently classified. Dry-run does not fetch the page.
- WP5 filters submission lists/resources by selected profile and rejects
  unlabelled and cross-profile record mutations.
- Python/R `submit-install` workflows authorize the compound operation before
  bounded staging, then quote, validate, submit, and log in order.
- Delegated MCP quote/validation prepares temporary job artifacts, and job
  observation can reconcile the protected ledger.  Their internal bookkeeping
  is not equivalent to general workspace-write authority.
- Existing remote path builders support shell forms such as `$VSC_DATA` and
  `~`.  Root enforcement cannot be implemented with a local string-prefix
  check or an unrestricted shell expansion.
- Python package checks and R `requireNamespace` can execute package/module
  initialization.  Audit their actual effects before calling them passive
  filesystem reads.

## Implementation contracts

These are proposed engineering choices to make the work concrete.  Keep them
aligned with the policy decisions in `capabilities.md`; refine identifiers
before publishing a stable configuration or plugin API.

### Policy loading

- Add typed policy objects, preferably in `hpc_tools/capabilities.py`, with
  canonical level names, scope names, and root grants.
- Parse required `[profiles.<name>.capabilities]` and its `remote_roots` table.
  The block requires a valid `max_level`; omitted scopes and roots grant nothing.
  Reject unknown keys within the new policy tables, unknown levels/scopes,
  malformed lists, invalid roots, and missing or empty capability blocks.
  Update all bundled examples and test profile factories in the same package.
- CLI invocations load fresh policy.  MCP loads a profile/configuration snapshot
  at startup and requires restart for edits.  Tool functions must use that
  resolved snapshot rather than silently reloading via `_resolve_profile`.
- `full` requests every operation allowed by one bound profile. It is not a
  compatibility or unrestricted mode. All presets bind one profile and remove
  profile/configuration overrides from their public tool schemas.
- With no usable profile, generic CLI help and genuinely standalone local
  utilities remain available.  Remote operations require a profile.  Explicit
  `--profile`/`--config` selection errors must not fall back to standalone or
  unconfigured execution. Standalone local behavior is documented as outside a
  cluster profile, not a route to access a restricted remote profile.

### Operation registry and authorization

Each operation descriptor contains a stable internal ID, CLI/MCP bindings,
minimum level, all required scopes, effects, profile/state selectors, path
requirements, and confirmation/evidence/delegation requirements.  Keep
interface schemas in their interfaces and bind them to shared descriptors;
do not generate arbitrary CLI grammar from MCP signatures.

An evaluator returns an allowed decision or a structured denial with operation,
profile, missing level/scopes, and a safe reason.  Use exit status 2 for CLI
policy denial and a JSON error code such as `capability.denied`. Interface
response shapes may be simplified before release, provided every caller,
schema, example, and document is updated in the same work package.

Authorize before remote execution, local state changes, archive extraction,
temporary job staging, and ledger reservation.  For composite operations,
check every planned action before the first side effect and retain checks at
the individual action boundaries.  Authorization must never be inferred from
an arbitrary command string.

Normal audit/submission bookkeeping intrinsic to a permitted lifecycle action
remains part of that descriptor.  The `submission-record.write` grant controls
independent record-management operations; removing it must not disable required
submission logging.  Likewise, delegated private staging/reconciliation is
confined to existing host-authorized roots and is not a general filesystem
grant.

Dry-run and confirmation are independent of permission.  A denied action must
not become executable through `dry_run`, `confirm`, `force`, skip-quote options,
or a different executor.  A permitted preview must accurately report any
remaining requirements without taking the action.

### Initial operation mapping

This table is the starting inventory, not a substitute for per-leaf registry
coverage.  Path-consuming variants also require their relevant root grants.

| Operation family | Level | Additional requirements |
| --- | --- | --- |
| Paths, safe profile summaries, installed references, plugin metadata | C0 | Selected-profile projection where needed; raw configuration requires `config.read.raw` |
| Reference create/export/import/attach/detach; generated local assets; audit export | C0, or C2 for protected audit data | `local-state.write`; protected audit also needs `delegation-ledger.read` |
| Login checks, module/site/limit queries, quota, site-only status | C1 | Bounded configured operations; no queue or submission data |
| Directory/metadata inspection | C1 | `remote-filesystem.list` and list roots |
| Source, input, script, and log content reads | C1 | `remote-filesystem.read` and read roots |
| Clone, mkdir, upload, copy, file replacement | C1 | `remote-workspace.write` and write roots; remote copy also needs source read |
| Packaged remote asset installation | C1 | `remote-install.write` and install roots |
| Explicit deletion | C1 | `remote-workspace.delete` and delete roots |
| Balance/statement | C1 | `accounting.read` |
| Queue/job/accounting and profile-filtered submission history | C2 | Existing job/delegation ownership rules |
| Resource quotation and test-only validation | C2 | `job.validate`; credit quotation also needs `accounting.read` |
| Observe-and-store, mark-collected/analysed, close | C2 | `submission-record.write`; verify target record's profile |
| Actual submission/cancellation, authorized controller actions | C3 | Existing safety gates; workflow preflight also needs its preflight/account grants |
| CLI arbitrary `run` | Outside cumulative grants | Explicit operator scope `remote-shell.execute`; absent from all MCP presets |

General local source scanning and benchmark analysis are local operations; do
not require C2 merely because they concern job results.  Local file generation
needs `local-state.write` when a policy is selected.  Plugin package-check
execution requires an audited descriptor, not a blanket claim of read-only
behavior.

### Filesystem implementation boundary

Provide one bounded filesystem service used by existing clone/install/read
paths and new CLI/MCP operations.  Proposed new modules are
`hpc_tools/filesystem.py` and a packaged standard-library remote helper.

The implementation direction is a fixed helper request protocol, invoked via
the selected executor, with structured action/path/data arguments.  The helper
performs authorization-related path resolution and file operations together
on the target host.  A configurable remote Python interpreter and an explicit
availability check are preferable to silently installing dependencies.  If
the helper or required filesystem primitives are unavailable, deny restricted
filesystem operations with a clear reason; do not fall back to unconfined
shell commands.

Resolve roots on the remote host.  Permit only documented home/environment
path forms needed by existing profiles; forbid command substitution, globs,
and arbitrary expansion.  Normalize them to absolute paths before use.
Traverse relative to verified directory descriptors, avoid following links
below roots, validate destination parents, and operate through those same
descriptors.  A separate `realpath` check followed by a shell command is not
sufficient protection against path changes.

Start with regular files and directories.  Explicitly bound byte/entry counts,
timeouts, recursion, and overwrite behavior.  Exclude special files and
implicit recursive reads/deletion.  Deny deletion of an allowed root itself.
For Git clone, use a fixed argv and a checked destination, disable hooks and
recursive submodule initialization for this operation, and reject local/file
clone sources unless they satisfy source-read grants.  Test the actual Git
effects rather than assuming clone is a single safe file write.

General filesystem grants constrain the tools' own file operations.  They do
not confine arbitrary submitted job scripts, package initialization, site
commands, or external executables.  Document this distinction and retain the
existing container/delegation deployment boundary.

## Dependency order

| Package | Deliverable | Depends on |
| --- | --- | --- |
| WP1 | Complete surface inventory and synchronized snapshots | None |
| WP2 | Typed mandatory per-profile policy | WP1 |
| WP3 | Shared registry and policy evaluator | WP2 |
| WP4 | Root-aware filesystem foundation | WP2, WP3 |
| WP5 | Authorization of existing core operations | WP3, WP4 |
| WP6 | Bundled and external Python CLI plugin contract | WP3, WP4, WP5 |
| WP7 | CLI resolution, hiding, display, and execution denial | WP5, WP6 |
| WP8 | MCP profile binding, discovery, resources, and invocation | WP5, WP6, WP7 |
| WP9 | New bounded file operations through CLI and MCP | WP4, WP7, WP8 |
| WP10 | Restricted-agent and controller integration | WP5, WP8 |
| WP11 | User documentation, examples, and packaging | WP7, WP8, WP9, WP10 |
| WP12 | End-to-end and installed-distribution acceptance | WP1--WP11 |

The table permits separate development of WP9 and WP10 after their
prerequisites; no partial release is accepted merely because a later package
can be started.

## WP1: Inventory and characterization

Targets: `cli.py`, all `commands/` modules, all bundled plugin registrations,
`mcp/server.py`, `mcp/tools.py`, `mcp/submit.py`, `mcp/resources.py`, and
existing CLI/MCP/delegation tests.

Work:

1. Enumerate every CLI leaf, alias, relevant argument mode, MCP tool, fixed
   resource, and resource template.  Record current effects and state/path
   selectors.  Include standalone console scripts that perform job control.
2. Snapshot current schemas and no-config behavior before refactoring. Identify
   tests importing re-export modules or calling handlers directly; these are
   change-impact sites, not interfaces that must be preserved.
3. Capture focused baseline tests in the supported development environment;
   distinguish missing optional dependencies from product failures.
4. Record the inventory with registry fixtures to be consumed by WP3, not a
   second manually maintained authorization implementation.

Exit criteria: every current public action has a proposed classification;
compound/dynamic actions and pre-policy bypasses are explicitly identified.
Snapshots are synchronized change detectors, not compatibility contracts. No
runtime policy claim is made yet.

Implementation record (2026-10-13):

- [WP1](work-packages/wp01-surface-inventory.md) records the characterized
  surface, direct-call/re-export dependencies, pre-policy no-config behavior,
  synchronization rule, and validation.
- The WP1 baseline classified 65 operations. The synchronized current fixture
  classifies 72 operations and all six console scripts; coverage tests account
  once for every one of the 68 CLI leaves, 39 full-preset MCP tools, and 10
  distinct MCP resource identifiers.
- `tests/fixtures/capability_surface_snapshot.json` and
  `tests/fixtures/capability_mcp_schema_snapshot.json` record parser, callable,
  console, resource, no-config, and FastMCP discovery state. They must be
  deliberately updated alongside intentional interface and documentation changes.
- `tests/test_capability_inventory.py` verifies exact current snapshots,
  one-to-one coverage, and explicit dynamic/compound/operator exceptions.
- The supported `.venv` suite passed 308 tests with one skip. The literal
  system-`python3` suite was also attempted but that interpreter lacks the
  required `tomlkit` dependency; this was an environment/setup failure, not a
  product-test failure. Repository plugin/skill validators and compilation
  passed. Repository hygiene remains blocked by pre-existing caches, build
  output, and egg-info, which were preserved as unrelated working-tree state.

## WP2: Policy configuration

Targets: `config.py`, new `capabilities.py`, `tests/test_config.py`, new
`tests/test_capabilities.py`, and shared profile test factories.

Work:

1. Define ordered levels, recognized scopes, and immutable root grants. Add a
   required policy field to `Profile`; update every construction site, shared
   fixture, and example instead of supplying a compatibility default.
2. Parse nested policy tables with strict validation confined to those tables.
3. Make grant intersection and requested-level narrowing explicit; do not
   combine permissions by union across profiles or presets.
4. Define safe public policy summaries separately from raw `asdict(Profile)`
   serialization.

Exit criteria: tests cover all four levels, rejected absent/empty/invalid blocks,
unknown scopes/keys, malformed roots, multiple profiles, XDG/config overrides,
and no unintended grants from defaults.  Loading a policy performs no cluster
queries and no writes.

Implementation record (2026-10-13):

- [WP2](work-packages/wp02-profile-policy.md) records the schema, strict
  parsing rules, intersection boundary, documentation synchronization, and
  validation scope.
- `hpc_tools/capabilities.py` implements policy version 1, the four ordered
  levels, recognized scopes, immutable root grants, parsing, requested-level
  narrowing, intersection, and plain public summaries.
- `Profile.capabilities` is mandatory. Missing, empty, unsupported-version, or
  invalid policy fails configuration loading; no compatibility default exists.
- All direct `Profile` constructors, test configuration factories, checked-in
  TOML examples, and user-facing profile snippets were updated. Tests load the
  installed examples and every documented TOML profile block through the real
  parser.
- Focused policy/configuration/documentation tests passed, and the complete
  supported `.venv` suite passed 328 tests with one skip. No live cluster,
  scheduler, SSH connection, or remote write was used.

## WP3: Registry and evaluator

Targets: new operation-registry module, `capabilities.py`, command registration
bindings, and new `tests/test_operation_registry.py`.

Work:

1. Give every retained WP1 operation an ID and descriptor. Remove redundant
   aliases where useful, or bind retained aliases to the same semantics. Add
   argument resolvers for test-only submission, stdout-only generation,
   overwrite, composite status, and profile/state selectors.
2. Implement pure evaluation plus structured denial.  Distinguish missing
   level, scope, path grant, and unavailable site functionality.
3. Add request/authorization context usable by CLI, MCP, and plugin services.
4. Validate complete registry coverage and prevent duplicate/conflicting
   bindings. Keep unknown or unintegrated operations denied.

Exit criteria: evaluator tests prove level monotonicity with fixed scopes,
scope intersection, C2 test-only versus C3 submission, and alias consistency.
No string parsing of generated shell commands supplies authorization.

Implementation record (2026-10-13):

- [WP3](work-packages/wp03-operation-registry.md) records the shared descriptor,
  request-resolution, and structured-decision contracts.
- `hpc_tools/operation_registry.py` now classifies all 72 operations
  and validates unique CLI, MCP-tool, and MCP-resource bindings. All 68 CLI
  leaves carry an explicit `operation_id`, including bundled plugin commands
  and the two retained probe aliases.
- `hpc_tools/capabilities.py` provides pure requirement evaluation and safe,
  structured denials for unknown operations, levels, scopes, declared path
  grants, and unavailable site functionality.
- Argument resolvers cover stdout/preview versus file generation, overwrite
  intent, C2 test-only versus C3 submission, install-workflow preflight modes,
  the pre-WP5 compound status operation, path selectors, and profile/state
  selectors. WP5 subsequently replaced the compound status resolver with a
  focused C1 operation. Arbitrary remote command text is never parsed for authority.
- Runtime CLI denial/hiding and MCP discovery filtering remain unimplemented by
  design; WP3 supplies the shared classification and evaluation boundary used
  by later packages.
- Focused registry/evaluator tests passed, and the complete supported `.venv`
  suite passed 349 tests with one skip. No live cluster, scheduler, SSH
  connection, or user configuration/state was used.

## WP4: Filesystem foundation

Targets: new filesystem service/helper, executor transport extensions where
necessary, package inclusion, and new `tests/test_filesystem.py`.

Work:

1. Define structured requests/results, root resolution, regular-file reads,
   directory listing, and safe destination primitives.
2. Implement descriptor-based traversal and bounded data transport with the
   same service behavior for local and SSH executors.  Package the helper so
   installed CLI use does not require the checkout or a remote hpc-tools install.
3. Add finite byte/entry/transfer/time limits and explicit failure/truncation
   results.  Preserve binary bytes for transfers; text reading has defined
   encoding behavior.
4. Implement publication/overwrite and cleanup primitives that later writes
   can reuse.  An interrupted transfer must not present an incomplete target
   as a successful copy.

Exit criteria: real temporary-filesystem tests cover sibling-prefix escapes,
`..`, absolute/relative paths, home/environment forms, links and link swaps,
missing parents, special files, limits, overwrite conflicts, and interruption.
Missing helper/interpreter/primitives fails closed.  No live cluster needed.

Implementation record (2026-10-13):

- [WP4](work-packages/wp04-filesystem-foundation.md) records the structured protocol,
  descriptor traversal, transport limits, atomic publication, and integration
  boundary.
- `hpc_tools/filesystem.py` provides typed requests/results, binary and explicit
  UTF-8 text reads, finite limits, one executor-independent service, structured
  failures, and upload/publication/cleanup primitives.
- The self-contained standard-library helper is packaged as
  `hpc_tools/data/filesystem_helper.py` and streamed over a framed stdin
  protocol. A cluster needs a suitable Python interpreter but no hpc-tools
  checkout or remote package installation.
- Root expansion occurs on the selected executor. Operations traverse from
  opened directory descriptors without following links below roots, exclude
  special-file reads/writes/deletion, avoid recursion, and publish complete
  files atomically with explicit overwrite behavior.
- Local-executor temporary-filesystem tests and framed SSH transport tests cover
  the exit criteria without a live cluster. WP5 routes built-ins through this
  service; WP6 now routes Python/R install staging and verification through it.
- The complete supported `.venv` suite passed 379 tests with one skip. A local
  wheel build also confirmed that both `hpc_tools/filesystem.py` and the
  packaged helper are present in the distribution. No live cluster, SSH
  connection, scheduler action, or user configuration/state was used.

## WP5: Existing built-ins and compound operations

Targets: `commands/core.py`, `remote.py`, `probes.py`, `slurm.py`,
`submissions.py`, `references.py`, `agent.py`, MCP underlying services, and
their focused tests.

Work:

1. Guard shared operation services before effects, including direct handler
   paths used by tests.  Keep interface wrappers thin; do not rely solely on
   top-level CLI dispatch to protect a service callable from MCP.
2. Route all path-consuming reads, clone, and asset installation through the
   filesystem foundation. Delete the unconfined pre-policy path rather than
   keeping a parallel execution branch.
3. Factor site status, credit/account status, and submission status into
   separate services. The current combined `status` may be removed or retained
   as a fully authorized composite; do not silently omit denied sections.
   Offer focused CLI/MCP operations for lower-level profiles.
4. Filter submission reads by profile before producing results.  Resolve a
   record's profile before mutating it; reject cross-profile run identifiers.
   Reject unlabelled records and update all fixtures to create attributed
   records; no alternate read path is required before the first release.
5. Preserve logging intrinsic to submission/cancellation and make dry-run
   previews free of HTTP, SSH, scheduler, staging, and local mutation effects.
6. Limit safe profile views; reserve command strings/raw profile configuration
   for the raw-config grant.  Reference import/attach must not overwrite or
   elevate capability policy.

Exit criteria: denied operations produce no external effects, including no
temporary staging or record changes. C0 uses only installed references; C1
uses no job queries; C2 never submits/cancels. Retained lifecycle and reference
round-trip behavior matches the synchronized interface documentation.

Implementation record (2026-10-14):

- [WP5](work-packages/wp05-built-in-authorization.md) records the built-in service
  boundary, bounded filesystem routing, focused status behavior, submission
  isolation, safe profile views, and dry-run guarantees.
- `hpc_tools/authorization.py` applies the WP3 registry/evaluator before
  built-in CLI and MCP effects, including direct handler/callable paths.
- Remote directory inspection, clone destination preparation, and packaged
  asset installation use the WP4 filesystem service. The former unconfined
  asset-install and storage-listing branches were removed.
- Submission reads are selected-profile projections; unlabelled records and
  cross-profile mutation identifiers fail closed. Quote/validation/submission
  authorization occurs before temporary staging.
- `status` is now a focused C1 public status-page read. Quota, account balance,
  and submission history remain separate operations, and previews perform no
  HTTP, SSH, scheduler, staging, or local record effects.
- CLI visibility and MCP discovery/profile binding deliberately remain WP7 and
  WP8 respectively; Python CLI plugin enforcement is implemented by WP6.
- Focused and complete supported-environment validation passed: the `.venv`
  suite ran 396 tests with one skip, plugin and skill validators passed, and
  the required compilation checks passed. No live cluster, SSH connection,
  scheduler action, status-page request, or user configuration/state was used.
  The literal system-Python suite remains unusable because that interpreter
  lacks `tomlkit`; repository hygiene continues to report the checkout's
  existing caches, build output, and egg-info artifacts.

## WP6: Python CLI plugins

Targets: `plugin_system.py`, bundled plugin factories/commands, Python/R
install-plan and verification helpers, plugin tests, and `docs/plugins.md`
contract notes to be finalized in WP11.

Work:

1. Extend the entry-point plugin protocol with versioned operation metadata
   and bindings. Reject plugins that do not implement the supported contract.
2. Register bundled benchmark, C/C++, Python, and R leaf operations, including
   local scans, generated files, remote checks, output verification, and
   staged install submissions.
3. Pre-authorize every stage of install submission before uploading a script.
   Resolve target/output paths through the same filesystem service.
4. Audit module/package initialization effects.  If a check cannot meet its
   advertised bounded contract, deny it under capability policy until a
   suitable operation contract exists; do not relabel executable code as a
   passive file read.
5. Omit/deny undeclared external plugin operations and
   explain the metadata requirement in plugin information.  Metadata is a
   contract for trusted installed Python code, not a sandbox for malicious
   plugins or their import-time behavior.

Exit criteria: fake plugins exercise declared, unknown-version, and undeclared
cases.  A denied Python/R submission does not stage, quote, validate, reserve,
submit, or append a record.  Local analysis remains usable without a cluster.

Implementation record (2026-10-14):

- [WP6](work-packages/wp06-plugin-authorization.md) records the versioned plugin
  contract, dispatch and direct-handler authorization, bounded Python/R install
  staging and verification, and trusted-code boundary.
- Bundled benchmark, C/C++, Python, and R plugins declare every leaf operation
  through the canonical registry. External plugins must declare matching CLI
  bindings under contract version 1; incompatible and undeclared surfaces are
  rejected and explained by plugin information.
- Python/R install submissions authorize all enabled stages before upload,
  stage through `remote_roots.write`, preserve existing scripts unless
  `--force` is explicit, and read verification output through
  `remote_roots.read`.
- Package/module checks remain classified as remote execution because language
  and module initialization may execute code. Local scans remain profile-free.
- The complete supported `.venv` suite ran 408 tests with one skip; plugin,
  skill, compilation, snapshot, and diff validation passed without live cluster
  or scheduler access. The system interpreter still lacks `tomlkit`, and the
  hygiene check still reports existing caches, build output, and egg-info.

## WP7: CLI policy and visibility

Targets: `cli.py`, command registration helpers, and
`tests/test_cli_core.py`, `test_cli_plugin_parsers.py`, plus capability tests.

Work:

1. Resolve explicit/default profile policy before profile-aware help, including
   local commands formerly covered by `_should_parse_without_config`.
2. Add proposed `--show-disallowed` and `--capability <level>` global options.
   Hide unavailable leaf commands and empty groups by default; show annotated
   denial reasons in the alternate mode.
3. Keep the full internal grammar available for precise denial of direct
   invocation without advertising denied commands in help or completion.
   Ensure parser error suggestions do not reveal an unfiltered command list.
4. For mixed-mode commands, show the allowed form explicitly (for example,
   test-only submission), then enforce the parsed arguments at dispatch.
5. Provide human and JSON policy summaries through a proposed
   `hpc capabilities` command, exposing effective grants and their source.

Exit criteria: root/subcommand help, both display modes, explicit/default
profiles, argument-dependent commands, JSON denials, and the intentionally
small profile-free bootstrap/local surface are tested. Display options never
change execution permission.

Implementation record (2026-10-14):

- [WP7](work-packages/wp07-cli-policy.md) records profile-aware filtered
  help, annotated expanded discovery, the separate full execution grammar,
  mixed-mode presentation, and validation boundaries.
- `--capability` narrows only discovery, while `--show-disallowed` explains
  unavailable leaves. Neither option is an execution grant or restriction;
  dispatch and handlers continue to authorize against configured policy.
- `hpc capabilities` reports the selected policy source and distinguishes
  configured execution grants from display grants in human and JSON forms.
- The supported `.venv` suite ran 417 tests with one skip; plugin, skill, and
  compilation validation passed. Hygiene remains blocked by the checkout's
  existing caches, build output, and egg-info. The system interpreter still
  lacks `tomlkit` (143 tests ran; 27 modules failed to import). No live cluster
  or scheduler operation was run.

## WP8: MCP profile policy and discovery

Targets: `mcp/server.py`, `common.py`, `resources.py`, `tools.py`, `submit.py`,
the current re-export module/entry point, and MCP registry/resource/submit/tool tests.

Work:

1. Add `context`, `discovery`, `job-inspect`, and `job-lifecycle` presets with
   profile-bound startup snapshots.  Derive tools/resources/templates from the
   registry intersected with preset, profile, site availability, and deployment.
2. Remove profile/config/database override parameters from bound schemas;
   inject trusted selections internally.  Preserve `confirm` in ordinary mode;
   existing delegated-mode binding rules remain additional restrictions.
3. Re-authorize calls with the bound snapshot.  Test decorated functions and
   actual protocol registration, not just exported name constants.
4. Filter profile enumeration, profile templates, references, submission
   history, and record updates to permitted context.  A templated URI naming
   another profile/reference set must not bypass the bound context.  Shared
   reference visibility is limited to the selected profile's effective set.
5. Replace whole-file `hpc://config` disclosure with selected-profile TOML and
   necessary shared settings when its scope is granted.  Safe runtime context
   reports effective level/scopes without protected deployment data.
6. Preserve quote/validate/submit evidence checks; filter out tools whose
   required preflight/account chain is unavailable.  C3 does not override
   those prerequisites. Replace the WP1 schema snapshots with the intended
   policy-filtered schemas and update MCP documentation/examples at the same time.

Exit criteria: two differently configured profiles expose different surfaces;
denied tools/resources are absent and inaccessible by guessed names or URIs.
Config edits take effect only after restart, consistently across discovery,
resources, and invocation.  Required confirmation and evidence remain enforced.

Implementation record (2026-10-14):

- [WP8](work-packages/wp08-mcp-policy.md) records the bound startup
  snapshot, registry-derived filtering, fixed resource, schema, and
  reauthorization contracts.
- `context`, `discovery`, `job-inspect`, `job-lifecycle`, and policy-constrained
  `full` servers now expose different level/scope/site-dependent surfaces;
  `slurm-job` retains its additional delegation allowlist and ledger controls.
- FastMCP integration tests prove two-profile separation, guessed-name/URI
  rejection, restart-only config changes, attached-reference isolation,
  hidden trusted selectors, ordinary confirmation, delegated restrictions,
  and preflight/evidence-chain availability.
- The supported `.venv` suite passed 420 tests with one skip; focused MCP tests
  passed 56 tests. Plugin, skill, compilation, schema-snapshot, and diff checks
  passed. Hygiene remains blocked by checkout artifacts; system Python lacks
  `tomlkit`; MkDocs is not installed in `.venv`. No live or installed-
  distribution operation was run.

## WP9: Bounded file operations

Targets: new `commands/files.py`, filesystem service, registry entries,
MCP wrappers, and new CLI/MCP file-operation tests.

Proposed public operations (names are provisional until WP1/WP3 registration):

| CLI | MCP | Contract |
| --- | --- | --- |
| `hpc files list` | `hpc_files_list` | Bounded entries and metadata under list roots |
| `hpc files read` | `hpc_files_read` | Bounded content under read roots |
| `hpc files download` | `hpc_files_download` | Remote read plus local file write |
| `hpc files upload` | `hpc_files_upload` | Explicit local input and remote destination |
| `hpc files copy` | `hpc_files_copy` | Remote source read and destination write |
| `hpc files mkdir` | `hpc_files_mkdir` | Explicit directory creation under write roots |
| `hpc files remove` | `hpc_files_remove` | Explicit target under delete roots |
| Existing `hpc clone` | `hpc_repo_clone` | Fixed Git clone operation under write roots |

Use bounded full-file replacement via upload for the initial editing workflow;
an interactive editor or general patch language is not required.  Single-file
transfer is required; recursive tree transfer is deferred and must not occur
implicitly.  Empty-directory removal and regular-file removal are the initial
delete surface; recursive deletion is deferred.

Work:

1. Bind all operations to registry descriptors and WP4 primitives, with
   explicit limits, overwrite policy, and structured results.
2. Preserve MCP preview/confirmation for writes and dry-run command previews.
   Local download destinations are explicit; reject special files and unsafe
   overwrite targets.  Client filesystem permissions still apply.
3. Use atomic file publication where supported; report partial bundle failure
   accurately rather than claiming transactional multi-file success.
4. Do not execute uploaded scripts.  Validate both endpoints for remote copies;
   delete grants are independent of write grants.

Exit criteria: C1 can upload a script but cannot submit it; C2 can read allowed
logs without workspace writes; C3 without read grants cannot retrieve arbitrary
user files.  Round trips preserve bytes and do not require a repository checkout
or installed hpc-tools on the target host.

Implementation record (2026-10-14):

- [WP9](work-packages/wp09-file-operations.md) records the seven bounded
  CLI/MCP file operations, the confirm-gated MCP clone tool, limits, atomic
  publication behavior, and focused acceptance evidence.
- Operations use the packaged WP4 helper over the selected executor. Upload,
  download, and copy preserve binary bytes; listing and reads are bounded;
  mkdir is one-level; removal accepts only a regular file or empty directory.
- The registry, capability inventory, CLI and FastMCP discovery snapshots,
  command/MCP reference documentation, and examples are synchronized with the
  new surface.
- The supported `.venv` suite passed 427 tests with one skip; the focused WP9
  slice passed 61 tests. Plugin, skill, compilation, and diff checks passed.
  The system interpreter still lacks `tomlkit`, and the hygiene check still
  reports pre-existing generated checkout artifacts.

## WP10: Restricted-agent integration

Targets: `delegation.py`, `restricted_jobs.py`, `restricted_launch.py`,
`agent_cleanup.py`, `mcp/server.py`, runtime resources, and delegation/restricted
boundary/lifecycle tests.

Work:

1. Intersect profile policy with `slurm-job`'s existing fixed tool allowlist,
   delegation, ownership, budgets, expiry, and parent-allocation identity.
   Do not add general filesystem/onboarding tools to that preset or image.
2. Keep private staging, evidence, ledger reservations, reconciliation, and
   cancellation idempotency working as intrinsic guarded operations.
3. Authorize controller startup and cleanup-job registration before creating
   scheduler effects.  Record effective policy provenance alongside the
   existing attempt/controller context.
4. Preserve cleanup/requeue already authorized for an active delegation under
   its captured controller authority.  Restarting with a narrower editable
   profile cannot silently grant new work or orphan existing owned jobs by
   disabling previously authorized cleanup.  Explain the snapshot/restart
   lifecycle explicitly in tests and documentation.

Exit criteria: profile C2 prevents delegated submission even under a permissive
manifest; C3 cannot exceed manifest budgets/ownership.  Lower grants do not
expand the fixed tool surface.  Existing requeue, draining, cancellation, and
cleanup invariants remain tested without running real jobs.

Implementation record (2026-10-14):

- [WP10](work-packages/wp10-restricted-agent.md) records the captured controller
  authority, current/captured policy intersection, lifecycle exceptions, and
  focused acceptance evidence.
- Initial controller launch and cleanup-job registration require C3 before any
  scheduler command. The first accepted profile policy and configuration
  digests are retained in the delegation audit ledger and attempt provenance.
- New MCP work is discoverable and executable only through the intersection of
  the current profile, the captured controller ceiling, and the fixed
  `slurm-job` surface. General filesystem and onboarding tools remain absent.
- Requeue and cleanup use the captured C3 authority so later profile narrowing
  cannot orphan already owned jobs; widening the profile cannot enlarge the
  captured ceiling.

## WP11: Documentation, examples, and packaging

Targets: `docs/development/capabilities/design.md`, README,
`docs/development/mcp-roadmap.md`, `docs/configuration.md`,
`docs/reference.md`, `docs/mcp.md`, `docs/plugins.md`, reference-set and
restricted-agent guides, relevant skills, `examples/`, `mkdocs.yml`,
`setup.cfg`, and distribution/plugin validation as needed.

Work:

1. Publish `docs/capabilities.md` and navigation covering all four levels,
   scopes/roots, CLI visibility, effective policy inspection, and MCP restart.
   Keep the proposal and implementation status consistent with delivered code.
2. Add template profiles for C0 installed references, C1 file staging, C2
   monitoring/preflight, and C3 lifecycle.  State the scopes needed by each
   example and include two centers with different policies.
3. Document mandatory capability blocks, the plugin operation-metadata
   contract, per-profile MCP instances, and the filtering of `full`. Update
   every checked-in configuration fragment and command/schema example.
4. Explain administrator reference publishing separately from user policy.
   Importing reference knowledge does not install policy, change SSH settings,
   or authorize job execution.
5. Update skills to inspect effective policy and stop on denied operations.
   They must not recommend shell execution as an automatic denial workaround.
6. Package the filesystem helper and keep the optional MCP dependency optional
   for CLI-only installation.  Keep Python plugin and Codex plugin APIs distinct.

Exit criteria: examples match installed help/schemas, Markdown links resolve,
strict MkDocs build succeeds, and applicable repository/plugin/skill checks
pass.  No durable user cluster records enter `examples/` or the repository.

Implementation record (2026-10-15):

- [WP11](work-packages/wp11-documentation-packaging.md) records the published policy
  guide, fictional role templates, packaging boundary, and validation evidence.
- The MkDocs site, README, design/status records, configuration and command
  references, MCP/plugin/reference/restricted-agent guides, and all interactive
  skills now describe the same implemented C0--C3 policy.
- The role templates cover C0 context, C1 staging, C2 monitoring/preflight,
  and C3 lifecycle across two fictional centers, and parse with the production
  loader. No durable user or real-center cluster state was added.
- Strict MkDocs, plugin/skill validation, compilation, and the supported full
  suite passed; the environment-only system-Python and hygiene limitations are
  recorded without deleting unrelated checkout artifacts.

## WP12: Acceptance and handoff

Targets: integration/installed-process fixtures and tests, repository validation,
and a dated acceptance record with literal commands and results.

Required scenarios:

1. An administrator exports a reference set; a new user imports/attaches it and
   reads context under C0 without SSH, HTTP, Slurm calls, or rediscovery.
2. C1 lists/reads only granted roots and stages a script when write permission
   is present; missing read/write/delete grants fail independently.
3. C2 observes jobs and performs allowed quotation/test-only validation but
   cannot submit, cancel, or use `--validate-first` to escalate.
4. C3 completes the existing MCP evidence chain with confirmation, required
   scopes, and recorded submission; malformed/dry-run/mismatched evidence fails.
5. CLI default help omits denied commands; `--show-disallowed` explains them;
   direct calls are denied in either mode before effects.
6. MCP tool/resource enumeration and invocation agree for two profiles;
   alternate config/profile/database arguments and guessed URIs cannot escape
   the bound context.  Policy changes are picked up consistently after restart.
7. Bundled plugin composite workflows honor policy before staging. An external
   plugin without supported metadata is rejected.
8. Restricted-agent policy intersects with manifest authority, preserves
   cleanup/reconciliation, and never gains general filesystem tools.
9. Missing, empty, unknown-version, and otherwise invalid profile policy is
   rejected without falling back to an unrestricted surface.

Run unit and integration scenarios with temporary local directories, fake SSH,
fake HTTP, and fake Slurm executables.  Also exercise a real stdio MCP client
against an installed server with the optional dependency present, so registry
filtering is verified through the protocol rather than only mock FastMCP.

Build wheel and source archive and test independent installations outside the
checkout.  Use isolated pipx homes for release-style CLI/MCP testing, with no
changes to the user's normal installation.  Verify packaged helper availability,
CLI-only use without MCP dependencies, and the selected-profile MCP workflow.
Downloads needed to provision these environments are setup evidence, not live
cluster acceptance.

At final acceptance run the repository-required checks:

```bash
python3 tools/validate_plugin.py .
python3 tools/validate_skills.py .
python3 tools/check_repo_hygiene.py .
python3 -m py_compile hpc_tools/*.py hpc_tools/plugins/*.py hpc_tools/plugins/cxx/*.py hpc_tools/plugins/python/*.py hpc_tools/plugins/r/*.py hpc_tools/commands/*.py hpc_tools/mcp/*.py tests/*.py tools/*.py
python3 -m unittest discover -s tests
mkdocs build --strict
git diff --check
```

Include any new module directories in compilation/CI checks.  Run required
checks after changing skills, README onboarding, examples, or tests as directed
by `AGENTS.md`; use focused tests during other intermediate packages.  Preserve
unrelated working-tree changes and pre-existing caches/build artifacts.  If
hygiene is blocked by those artifacts, record that separately from functional
test results and clean only task-owned outputs.

Acceptance evidence must distinguish unit/integration, installed-distribution,
optional-MCP protocol, documentation, and live-cluster checks.  Record counts,
skips, environment/setup failures, and unrun scenarios.  This plan authorizes
no real cluster installs or Slurm submissions; live validation is a separate
explicitly authorized activity.

Implementation record (2026-10-15):

- [WP12](work-packages/wp12-acceptance.md) maps all nine required
  scenarios to executable acceptance tests and records literal results.
- The local acceptance runner exercises 27 stable unit/integration cases,
  including fake SSH, HTTP, and Slurm endpoints, without contacting a cluster.
- Both the wheel and source archive pass independent isolated-pipx checks. The
  wheel works without the optional MCP dependency; the source archive with the
  `mcp` extra passes a real stdio MCP discovery and invocation probe.
- CI builds both artifacts and runs the same local and installed-distribution
  acceptance tiers. Live-cluster installation and Slurm submission remain
  unrun because this work package does not authorize them.

## Completion tracking

Mark a package complete only after its exit criteria have literal evidence.
Use `not started`, `in progress`, `implemented / acceptance pending`, and
`complete` rather than inferring completion from code presence or this plan.

Current state: WP1--WP12 are **complete** with the evidence recorded above and
in the per-package implementation records. The capability feature has passed
local, fake-endpoint, installed-distribution, and optional-MCP protocol
acceptance. Built-in CLI/MCP callables and versioned Python CLI plugins enforce
registry decisions and use the bounded filesystem foundation where applicable;
MCP discovery and invocation are bound to one profile snapshot. Live-cluster
validation is outside this plan and remains a separately authorized activity.
