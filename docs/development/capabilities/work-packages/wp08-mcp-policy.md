# WP8 MCP profile policy and discovery

Status: implemented and accepted locally on 2026-10-14.

## Bound startup authority

Every `hpc-mcp` server now resolves one profile and captures its profile data,
effective preset policy, config path, and submission-database path at startup.
The new `context`, `discovery`, `job-inspect`, and `job-lifecycle` presets add
C0--C3 ceilings. `full` remains a convenience request for everything the
profile itself permits, while `slurm-job` remains the narrower delegated
deployment surface.

Registration is derived from the shared operation registry and filtered by the
preset, profile level and scopes, site helpers, path-grant availability, and
deployment allowlist. Calls are re-resolved and re-authorized inside the same
immutable binding context. Editing config does not change either discovery or
invocation until the server restarts.

## Schemas, resources, and context isolation

All bound tool schemas omit profile, config, and database overrides. Ordinary
mode retains `confirm`; delegated mode additionally hides confirmation and its
existing submission-path overrides. The MCP quote/validate/submit path still
requires account quotation, validation scope, matching evidence, and ordinary
confirmation or delegated authorization. A C3 profile without the preflight
chain does not discover submission.

Cross-profile and arbitrary reference-set resource templates were replaced by
fixed selected-profile resources. Profile enumeration returns only the bound
profile; reference listing/showing is limited to its attached effective set;
submission reads and mutations use its fixed database and profile. The raw
config resource is now parseable TOML containing only the selected profile and
required `default_profile` setting. `hpc://runtime` reports the effective
level, scopes, roots, preset, profile, and executor without adding protected
ordinary-deployment data.

## Verification boundary

Focused FastMCP tests cover different surfaces for two profiles, all four
capability ceilings, hidden override parameters, ordinary versus delegated
confirmation, guessed tool/resource rejection, attached-reference isolation,
selected-profile TOML, submission-chain prerequisites, dynamic call-time
reauthorization, and restart-only config changes. The MCP-focused suite ran 56
tests successfully. The complete supported `.venv` suite ran 420 tests: all
passed, with one skip.

Plugin and skill validation, compilation, capability-schema synchronization,
and `git diff --check` passed. Repository hygiene still reports the checkout's
`.ruff_cache`, build output, egg-info, and bytecode caches. The system Python
still lacks `tomlkit`: 143 tests ran and 27 modules failed to import. A strict
MkDocs build was not run because this checkout's `.venv` has no `mkdocs`
executable. No installed-distribution, external stdio-client, live SSH,
cluster, or scheduler check was run.

WP9 must add the proposed bounded general file operations without weakening
this registration or startup-snapshot boundary.
