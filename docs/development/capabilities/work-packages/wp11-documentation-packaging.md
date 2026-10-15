# WP11 documentation, examples, and packaging

Status: complete on 2026-10-15.

WP11 publishes the capability policy implemented by WP1--WP10 across the user
documentation, profile templates, MCP and plugin guidance, and interactive
skills. It adds no new authority and makes no remote cluster changes.

## Published capability guidance

The [capability policy guide](../../../capabilities.md) is the user-facing
policy guide and is part of the strict MkDocs navigation. It documents:

- the cumulative C0 `profile-context`, C1 `cluster-discovery`, C2
  `job-inspection`, and C3 `job-lifecycle` levels;
- all independent scopes and list/read/write/delete/install root categories;
- the mandatory policy-format-1 profile block and fail-closed defaults;
- default CLI hiding, `--show-disallowed`, display-only `--capability`, and
  `hpc capabilities` inspection;
- one startup-bound profile per MCP process, allowed-only discovery, filtered
  `full`, and the restart requirement after policy changes;
- the distinction between profile policy, SSH/Slurm/Unix authorization, and
  restricted-agent delegation; and
- the operator-only status of `hpc run`.

The README, configuration and command references, MCP guide, plugin guide,
reference-set guide, restricted-agent guide, root design record, and MCP status
plan point to the same delivered model. The MCP documentation includes a
two-process/two-profile client example. The Python `hpc_tools.plugins` extension
contract is explicitly separate from the Codex skills/plugin distribution.

## Role templates and reference publishing

`examples/capability-profiles.toml` contains four wholly fictional profiles
across the Atlas and Borealis example centers:

- C0 installed reference context with no scopes or remote roots;
- C1 file inspection and staging with distinct list/read/write roots;
- C2 monitoring, accounting, quotation, validation, and bounded log reads; and
- C3 lifecycle management with staging but deliberately no general read,
  delete, or install authority.

The file parses with the production configuration loader and its profile help
surfaces were exercised without contacting a cluster. It is clearly marked as
a template rather than a durable site or user record.

Administrator reference publishing is documented as knowledge distribution,
not policy distribution. Importing or attaching an archive does not create a
capability block, change SSH settings, install credentials, grant filesystem
roots, or authorize submission.

## Skill and packaging boundary

All ten interactive skills now inspect `hpc capabilities` and filtered help
before choosing remote operations. Shared guidance instructs the agent to stop
and report a missing level, scope, root, or site feature. It explicitly forbids
using `hpc run`, raw SSH, direct Slurm commands, or direct filesystem commands
as an automatic denial workaround. Intentional operator-shell use remains
documented only for a profile with `remote-shell.execute`.

The existing package configuration already includes
`hpc_tools/data/filesystem_helper.py` through core package data and keeps
FastMCP in the optional `mcp` extra. WP11 adds regression assertions for that
split rather than changing correct packaging metadata. Final wheel/sdist and
independent-install testing belongs to WP12.

## Acceptance evidence

The following checks were run from the repository root:

```text
mkdocs build --strict
  PASS; strict site built with no warnings

python3 tools/validate_plugin.py .
  PASS; plugin manifest validated

python3 tools/validate_skills.py .
  PASS; 10 interactive skills, 1 restricted-agent skill, and 5 shared references

python3 -m py_compile hpc_tools/*.py hpc_tools/plugins/*.py \
  hpc_tools/plugins/cxx/*.py hpc_tools/plugins/python/*.py \
  hpc_tools/plugins/r/*.py hpc_tools/commands/*.py hpc_tools/mcp/*.py \
  tests/*.py tools/*.py
  PASS

.venv/bin/python -m unittest discover -s tests
  PASS; 435 tests, 1 skipped

git diff --check
  PASS
```

The four example profiles also returned status 0 from `hpc capabilities` or
profile-filtered `--help` using the supported `.venv` installation.

The literal `python3 -m unittest discover -s tests` command used the bare
system Python 3.10 environment, which lacks the declared `tomlkit` dependency;
it ran 149 tests and reported 28 import errors, all rooted in that missing
package. The supported project environment completed the full suite above.

`python3 tools/check_repo_hygiene.py .` continues to report the pre-existing
`.ruff_cache`, `build`, `hpc_tools.egg-info`, and bytecode cache trees. WP11
does not delete unrelated checkout artifacts. These environment/hygiene results
are reported explicitly and are not product-test failures.
