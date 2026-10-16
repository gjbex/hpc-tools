# WP5 built-in authorization and effect boundaries

Status: implemented and accepted locally on 2026-10-14.

## Service authorization boundary

`hpc_tools.authorization.require_authorized` resolves a registry operation,
evaluates its primary and component requirements against the selected profile,
and raises a structured, safe `CapabilityAuthorizationError` on denial.
Built-in CLI handlers and MCP callables invoke this boundary before HTTP,
executor, scheduler, staging, filesystem, or durable-state effects. Direct
handler calls therefore receive the same protection as top-level dispatch.

This package does not implement visibility policy. The CLI still advertises
its full grammar until WP7, and the MCP server still registers its configured
tool set until WP8. A discovered but disallowed built-in operation nevertheless
fails at invocation before its effect.

## Focused reads and dry-run behavior

The former compound status report is removed. `hpc status` and `hpc_status`
read only the configured public status page at C1. Quota, account balance, and
submission history remain separate registry operations with their own levels
and scopes. A status dry run reports its intended read without making an HTTP
request.

Built-in dry-run paths do not perform HTTP, SSH, scheduler, remote staging,
bounded-helper writes, or local submission-record mutations. Submission,
cancellation, and their intrinsic audit logging retain their existing ordering
for real authorized operations.

## Bounded filesystem routing

`hpc_tools.remote_filesystem` binds structured paths to explicit profile root
grants and adapts the WP4 service for directory inspection, directory creation,
and asset installation. Built-in project/storage listings use the helper.
Probe and container installers validate the complete relative bundle, preflight
conflicts, create permitted directory components, and atomically publish each
file. Scripts use mode `0700`; other assets use `0600`.

Clone validates and prepares its destination through the helper before invoking
Git. Repository inspection preflights the selected directory and bounded `.git`
metadata before invoking Git. Git itself remains an external process governed
by the remote identity's operating-system permissions; WP4 is a filesystem
operation boundary, not process confinement. General file read/write commands
remain later work.

There is no unrestricted shell fallback for the migrated list/install paths.
Expected destination conflicts are detected before publishing bundle files.
Publication is atomic per file, not transactional across an entire bundle.

## Profile and durable-state isolation

Submission reconstruction requires a non-empty profile attribution. Lists and
MCP resources project only records belonging to the selected profile. Observe,
mark, and close operations resolve the run before mutation and reject unknown,
unlabelled, or cross-profile run identifiers.

Safe profile listings expose names, capability summaries, attached-reference
metadata, and feature availability without SSH identities or configured
commands. Detailed profile views and `hpc://config` require
`config.read.raw`; the config resource returns only the selected resolved
profile, never the entire multi-profile file. Reference import and attachment
are guarded local-state writes and preserve the selected profile's capability
policy.

## Verification boundary

Focused tests cover denial before executor, HTTP, scheduler, staging, logging,
and local reference mutations; C1 job-query denial; C2 lifecycle denial;
profile-filtered and cross-profile-resistant submissions; helper-backed bundle
installation, modes, traversal rejection, conflict preflight, and bounded
listing; focused status; and safe MCP projections.

WP6 subsequently guards bundled and external Python CLI plugins. WP7 must still
implement profile-aware CLI hiding and display modes. WP8 must bind one MCP profile,
remove public override parameters, and make only allowed tools/resources
discoverable. Those omissions do not create alternate unguarded built-in
service paths, but they mean the overall capability feature is not complete.

The supported `.venv` ran 396 tests: all passed, with one skip. Plugin and skill
validation and both required compilation checks passed. The literal
system-`python3` suite was also attempted, but that interpreter lacks the
required `tomlkit` dependency and produced 26 import errors; this is not a
product-test failure. Repository hygiene still reports pre-existing/local
`.ruff_cache`, `build`, `hpc_tools.egg-info`, and `__pycache__` artifacts, which
were not removed as part of WP5.
