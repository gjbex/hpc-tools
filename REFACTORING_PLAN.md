# hpc-tools Refactoring Plan

This plan focuses on maintainability and organization without changing the
public CLI, MCP, skill, or config contracts. Keep each phase behavior-preserving
unless a specific issue is called out and covered by tests.

## Goals

- Reduce the size and coupling of the largest modules.
- Make command, MCP, parser, and workflow boundaries easier to understand.
- Preserve the current safety model for remote commands and Slurm submission.
- Keep validation fast and local.

## Current Pressure Points

- `hpc_tools/cli.py` is the main bottleneck. It mixes parser construction,
  command handlers, template rendering, JSON wrapping, and command-family
  behavior in one large file.
- `hpc_tools/mcp_server.py` mixes MCP resources, MCP tools, guarded Slurm
  submission, schema details, and output parsers.
- `hpc_tools/plugins/python_support.py` and `hpc_tools/plugins/r_support.py`
  each combine CLI registration, dependency scanning, install-plan rendering,
  remote verification, and output parsing.
- Large test files make it harder to find the relevant regression coverage even
  though the overall coverage is strong.

## Phase 1: Split CLI Command Families

Status: implemented.

Target files:

- `hpc_tools/cli.py`
- `hpc_tools/commands/` package

Implemented modules:

- `hpc_tools/commands/core.py`: `run`, `doctor`, `site-env`, `paths`,
  `plugins`.
- `hpc_tools/commands/references.py`: `references list/show/validate/create`,
  `export/import/attach/detach`.
- `hpc_tools/commands/probes.py`: probe and container write/install commands.
- `hpc_tools/commands/slurm.py`: `jobs`, `job`, `submit`, `sacct`,
  `slurm-limits`, optional quote/account/status commands.
- `hpc_tools/commands/remote.py`: storage, repo, clone, module-spider,
  projects.
- `hpc_tools/commands/submissions.py`: local Slurm submission event-log
  commands.

Completed:

1. Moved built-in parser registration into small command-family modules under
   `hpc_tools/commands/`.
2. Moved command handlers and command-family helper functions into the same
   command-family modules.
3. Reordered the top-level command list by operator workflow.
4. Added grouped top-level `hpc --help` output for:
   local setup and metadata, cluster inspection, remote workspace, packaged
   assets, Slurm accounting and safety, Slurm job lifecycle, and workflow
   plugins.
5. Added regression coverage for the grouped help headings and command order.
6. Kept compatibility imports in `hpc_tools/cli.py` for tests and callers that
   import command helpers from the old module path.

Ongoing constraints:

1. Keep `cli.py` responsible for pre-parsing, config resolution, plugin
   loading, JSON wrapping, and top-level error handling.
2. Do not rename commands, arguments, handler names exposed in tests, or output
   shapes unless the change is explicitly intentional.

Acceptance criteria:

- `hpc_tools/cli.py` becomes a composition layer rather than the owner of all
  command behavior.
- Existing command tests pass. Tests that mock command execution patch the new
  command-family module boundaries.
- `hpc --help` intentionally uses grouped command headings, while plugin command
  visibility remains stable under the "Workflow plugins" group.

## Phase 2: Split MCP Server Responsibilities

Status: implemented.

Target file:

- `hpc_tools/mcp_server.py`

Implemented modules:

- `hpc_tools/mcp/resources.py`: config, profile, reference-set, submission-log
  resources.
- `hpc_tools/mcp/tools.py`: profile, jobs, status, paths, reference, and local
  utility tools.
- `hpc_tools/mcp/submit.py`: `hpc_quote_job`, `hpc_validate_job`,
  `hpc_submit_job`, evidence tokens, and confirm-gated submit checks.
- `hpc_tools/mcp/parsers.py`: Slurm limits, module spider, and other remote
  command-output parsers.
- `hpc_tools/mcp/server.py`: FastMCP app creation and registration.
- `hpc_tools/mcp/common.py`: shared config/profile resolution, remote result
  formatting, confirm-gated mutation previews, and serialization helpers.
- `hpc_tools/mcp_server.py`: compatibility wrapper that preserves the
  `hpc-mcp = hpc_tools.mcp_server:main` entry point and legacy imports.

Completed:

1. Extracted pure parser helpers into `hpc_tools/mcp/parsers.py`.
2. Extracted guarded submission into `hpc_tools/mcp/submit.py`; the quote ->
   validate -> submit evidence chain remains cohesive.
3. Extracted read/write MCP tool handlers into `hpc_tools/mcp/tools.py`.
4. Extracted resource handlers into `hpc_tools/mcp/resources.py`.
5. Extracted FastMCP registration and constants into `hpc_tools/mcp/server.py`.
6. Kept `hpc-mcp = hpc_tools.mcp_server:main` working through a compatibility
   wrapper.

Acceptance criteria:

- `tests/test_mcp_server.py` continues to validate tool names, resource URIs,
  schemas, and guarded submission refusals.
- The quote -> validate -> submit evidence chain remains in one obvious place.
- No new direct submit path bypasses evidence, account, validation, or
  confirmation checks.

## Phase 3: Organize Python and R Plugin Workflows

Status: implemented.

Target files:

- `hpc_tools/plugins/python_support.py`
- `hpc_tools/plugins/r_support.py`

Implemented module shape:

- `hpc_tools/plugins/python/commands.py`
- `hpc_tools/plugins/python/dependencies.py`
- `hpc_tools/plugins/python/install_plan.py`
- `hpc_tools/plugins/python/remote_verify.py`
- `hpc_tools/plugins/r/commands.py`
- `hpc_tools/plugins/r/dependencies.py`
- `hpc_tools/plugins/r/install_plan.py`
- `hpc_tools/plugins/r/remote_verify.py`
- `hpc_tools/plugins/python_support.py`: compatibility re-export wrapper for
  the existing entry point and legacy imports.
- `hpc_tools/plugins/r_support.py`: compatibility re-export wrapper for the
  existing entry point and legacy imports.

Completed:

1. Moved dependency scanning and dependency-file parsing into
   `dependencies.py`.
2. Moved install-script rendering, quote arguments, remote staging, and
   submission logging helpers into `install_plan.py`.
3. Moved remote check and verify output parsing into `remote_verify.py`.
4. Moved CLI plugin registration and command handlers into `commands.py`.
5. Kept the entry-point group unchanged:
   `hpc_tools.plugins = python = hpc_tools.plugins.python_support:get_plugin`
   and `r = hpc_tools.plugins.r_support:get_plugin`.

Acceptance criteria:

- Plugin entry points remain stable.
- JSON output shapes for scan, inspect, check, plan, and verify commands remain
  stable.
- The Python dependency scanner continues to use libraries for structured
  formats: TOML via `tomllib`/`tomli`, YAML via `PyYAML`, requirements via
  `packaging`.
- The R dependency scanner continues to use JSON for `renv.lock` and stdlib
  parsing for `DESCRIPTION`.

## Phase 4: Split Large Test Files by Feature

Target files:

- `tests/test_commands.py`
- `tests/test_mcp_server.py`
- `tests/test_plugins.py`
- `tests/test_skills.py`

Proposed split:

- `tests/test_cli_core.py`
- `tests/test_cli_references.py`
- `tests/test_cli_slurm.py`
- `tests/test_cli_probes.py`
- `tests/test_mcp_resources.py`
- `tests/test_mcp_submit.py`
- `tests/test_python_plugin.py`
- `tests/test_r_plugin.py`
- `tests/test_skill_routing.py`
- `tests/test_skill_content.py`

Suggested approach:

1. Move tests only; avoid changing assertions in the same commit.
2. Keep shared test fixtures local and minimal.
3. Prefer feature-oriented files over class-based catch-all test suites.

Acceptance criteria:

- `python3 -m unittest discover -s tests` remains the one full-suite command.
- Test names make it clear which contract failed.
- No coverage is dropped during test moves.

## Phase 5: Formalize Internal Contracts

Candidates for explicit data/service modules:

- profile and reference-set operations;
- submission-log state transitions;
- guarded submit evidence;
- Slurm command result parsing;
- plugin command registration metadata.

Suggested approach:

1. Add dataclasses or small service modules only where they replace repeated
   dictionary/string handling.
2. Keep public CLI output stable.
3. Prefer pure functions for parsers and state transitions so tests stay cheap.

Acceptance criteria:

- Fewer command handlers manipulate raw dictionaries directly.
- Submission lifecycle transitions remain append-only and testable.
- Slurm safety checks are easier to audit from one or two modules.

## Validation

After each phase, run:

```bash
python3 tools/validate_plugin.py .
python3 tools/validate_skills.py .
python3 tools/check_repo_hygiene.py .
python3 -m py_compile hpc_tools/*.py hpc_tools/plugins/*.py hpc_tools/plugins/python/*.py hpc_tools/plugins/r/*.py hpc_tools/commands/*.py hpc_tools/mcp/*.py tests/*.py tools/*.py
python3 -m unittest discover -s tests
```

If a phase creates `__pycache__` directories before the hygiene check, remove
the generated caches and rerun hygiene.

## Branching Guidance

Use one focused branch per phase. Avoid mixing behavior changes with file moves.
For large moves, prefer a commit that only moves code, followed by a commit that
does small cleanup inside the new structure.

## Non-Goals

- Do not replace custom parsers for Slurm, `sacct`, Lmod, or other remote
  command output unless there is a stable machine-readable output mode to use.
- Do not change the installed CLI versus Codex plugin distribution boundary.
- Do not move durable user-generated cluster references into the repository.
- Do not require a repository checkout for installed probe or onboarding
  workflows.
