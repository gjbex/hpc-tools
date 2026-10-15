# MCP Server Status and Roadmap

This note tracks the agent-friendly MCP server for `hpc-tools`. The server now
exists as an additional interface over the existing Python modules while
sharing the CLI's mandatory per-profile capability policy and preserving its
Slurm safety rules. WP12 clean-install and real stdio protocol acceptance is
complete and recorded in the
[WP12 acceptance record](capabilities/work-packages/wp12-acceptance.md).

## Goal

Maintain the MCP server as an additional interface:

- CLI: human-friendly `hpc ...` commands.
- MCP server: structured tools and resources for agents.
- Codex plugin skills: workflow guidance and safety policy.

The MCP server should call existing `hpc_tools` Python functions where
possible, instead of shelling out to the `hpc` command. Shelling out can remain
a temporary fallback for code paths that have not yet been factored into
reusable functions.

## Design Principles

- Bind each server process to exactly one profile at startup. Resolve that
  profile like the CLI, snapshot its policy, and omit profile/config/database
  overrides from public tool schemas.
- Preserve existing XDG-aware config paths and durable state under
  `~/.config/hpc-tools` or `$XDG_CONFIG_HOME/hpc-tools`.
- Keep the existing quote-before-submit, account-selection, validate-first,
  and pilot-first Slurm safety model.
- Do not expose a broad arbitrary remote shell tool as the first interface.
  Prefer narrow tools with typed arguments and bounded output.
- Return structured JSON-like results rather than terminal-formatted text when
  possible.
- Register only the tools and fixed resources allowed by the intersection of
  the selected profile, the requested preset, configured site features, and
  any delegation ceiling. `full` requests the complete allowed intersection;
  it is not a policy bypass.
- Require a server restart after profile or policy changes so discovery and
  invocation use the same snapshot.

## Phase 1: Read-Only Tools

Status: implemented through the `hpc_tools.mcp` package and the
`hpc_tools.mcp_server` console facade with the official FastMCP framework,
exposed as `hpc-mcp`.

Start with tools that inspect local config, durable references, and remote
state without writing files or submitting jobs.

Suggested tools:

- `hpc_profiles_list`
- `hpc_paths`
- `hpc_profile_show`
- `hpc_hardware_context`
- `hpc_hardware_sources`
- `hpc_references_list`
- `hpc_references_show`
- `hpc_plugins_list`
- `hpc_submissions_list`
- `hpc_status`
- `hpc_jobs`
- `hpc_job`
- `hpc_slurm_limits`
- `hpc_module_spider`
- `hpc_storage_inspect`
- `hpc_files_list`
- `hpc_files_read`
- `hpc_site_env`

These tools give agents most of the context they currently scrape from CLI
output while avoiding accidental cluster changes.

## Phase 2: MCP Resources

Status: implemented as profile-bound FastMCP resources. There are no
cross-profile or arbitrary reference-set resource templates.

Expose durable local context as resources:

- `hpc://paths`
- `hpc://config`
- `hpc://profile`
- `hpc://reference-set` when the profile attaches one
- `hpc://cluster/hardware`
- `hpc://cluster/slurm`
- `hpc://cluster/storage`
- `hpc://submissions/active`
- `hpc://submissions/all`
- `hpc://runtime`

Resources should read from the active hpc-tools config tree, not from
repository examples.

## Phase 3: Guarded Local And Remote Writes

Status: implemented with confirm-gated tools for reference sets,
submission-log lifecycle marks, generated probe/container files, bounded
single-file operations, repository clone, and remote installs. Slurm job
submission remains the separate Phase 4 evidence chain.

Add tools that write local state or install generated files remotely, but make
the mutation explicit.

Suggested tools:

- `hpc_references_create`
- `hpc_references_import`
- `hpc_references_attach`
- `hpc_submissions_mark_collected`
- `hpc_submissions_mark_analysed`
- `hpc_submissions_close`
- `hpc_write_probe`
- `hpc_install_probe`
- `hpc_write_container`
- `hpc_install_container`
- `hpc_files_download`
- `hpc_files_upload`
- `hpc_files_copy`
- `hpc_files_mkdir`
- `hpc_files_remove`
- `hpc_repo_clone`

For tools that create or upload scripts, return the generated script or command
preview and require `confirm=true` for the write or remote install step. File
and clone tools also require the matching filesystem scope and remote root;
they do not fall back to arbitrary shell execution.

## Phase 4: Guarded Slurm Submission

Status: implemented in `hpc_tools/mcp_server.py` as a quote, validate, and
submit workflow with shape-bound evidence tokens.

Do not expose a single permissive submit tool initially. Model submission as a
multi-step workflow:

1. `hpc_quote_job`
2. `hpc_validate_job`
3. `hpc_submit_job`

`hpc_submit_job` should require structured evidence from the prior steps:

- profile
- account
- jobscript path
- remote directory
- resource shape
- quote result
- quote timestamp or token
- validation result
- `confirm=true`

The quote evidence should become stale when resource shape, walltime, job
count, account, reservation, cluster, partition, GPU request, or jobscript path
changes. This keeps the MCP interface aligned with the existing rule that
resource-shape changes require a fresh quote.

Successful real submissions must continue to append to the hpc-tools submission
event log. Validation-only runs should not create submitted events.

## Phase 5: Packaging

Status: implemented with `hpc-mcp` as a Python package console script, the
optional `mcp` package extra, and Codex plugin MCP metadata in `plugin.json`
plus `.mcp.json`.

Add a module such as:

```text
hpc_tools/mcp_server.py
```

Expose it through package metadata, for example:

```ini
[options.entry_points]
console_scripts =
    hpc = hpc_tools.cli:main
    hpc-mcp = hpc_tools.mcp_server:main
```

Keep MCP packaging in the Python package first. The Codex plugin can later
include MCP configuration once the server is runnable, tested, and documented.

## Phase 6: Documentation

Status: implemented across `README.md`, `ROUTING.md`, `AGENTS.md`,
`skills/hpc-cluster-onboarding/SKILL.md`, and tests that pin MCP startup,
routing, packaging, and safety wording.

Update:

- `README.md`: add an MCP server section and startup examples.
- `ROUTING.md`: say when agents should prefer MCP over CLI.
- `AGENTS.md`: identify MCP as the structured agent interface and CLI as the
  human interface.
- `skills/hpc-cluster-onboarding/SKILL.md`: mention verifying MCP server
  availability after plugin and CLI setup.
- Tests that pin the MCP documentation and safety wording.

## Phase 7: Testing

Status: implemented across the MCP, capability-policy, filesystem, CLI, and
skill tests, including registry/schema stability, bound profile schemas,
allowed-only discovery, fixed resources, read-only no-write behavior,
confirm-gated mutations, bounded file operations, stale evidence, dry-run
evidence, and submit evidence checks.

Add tests for:

- stable MCP tool schemas;
- startup rejecting missing, unknown, or invalid profile policy;
- separate profiles producing different discovery surfaces;
- read-only tools not writing local or remote state;
- guarded write tools refusing mutation without `confirm=true`;
- `hpc_submit_job` refusing missing account, quote evidence, validation
  evidence, or confirmation;
- quote evidence becoming stale when resource shape changes;
- submission tools reusing the existing append-only submissions log;
- fixed resources resolving only from the bound profile, active config, and
  attached reference set;
- deterministic structured output suitable for agents.

## Open Design Questions

- Resolved: use FastMCP through the optional `hpc-tools[mcp]` dependency.
- Resolved: do not expose a raw remote command tool by default; remote access
  stays behind narrow typed tools.
- Resolved: quote and validation evidence use structured resource shape data
  plus a shape-bound token.
- Mostly resolved: MCP tools return structured dictionaries. Remote inspection
  tools still include captured stdout/stderr when the underlying site command is
  text-oriented, and `hpc_slurm_limits` plus `hpc_module_spider` now add
  best-effort `parsed` fields with `parse_warnings`.
- Open: decide whether additional remote inspection tools should parse common
  output into richer structured fields instead of only returning stdout lines.
- Open: decide how long-running remote operations should report progress and
  partial output if future MCP SDK support makes that practical.

## Remaining Roadmap

The original first-slice implementation is complete. Useful follow-up work is:

1. Reload or reinstall the Codex plugin/MCP server after MCP tool additions so
   new tools such as `hpc_status` and `hpc_module_spider` are available in fresh
   sessions.
2. Review additional remote read tools for output that should become structured
   fields. Treat `hpc_status` quota and balance parsing cautiously because those
   commands are site-specific.
3. Keep CLI and MCP parity in sync when new narrow operational helpers are
   added to the CLI.
4. Revisit progress/partial-output support only when a real long-running MCP
   operation needs it.

The current safety boundary remains: local writes and remote installs are
confirm-gated, and real Slurm submission requires the
`hpc_quote_job` -> `hpc_validate_job` -> `hpc_submit_job` evidence chain.
