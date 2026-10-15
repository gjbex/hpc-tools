# WP12 acceptance and handoff

Status: complete on 2026-10-15.

WP12 closes the capability implementation with executable local acceptance,
independent installed-distribution checks, and CI integration. It grants no new
authority and performs no live cluster install or Slurm submission.

## Acceptance scenarios

`tools/run_capability_acceptance.py` is the stable entry point for all nine
scenarios required by the [capability implementation plan](../implementation-plan.md).
It runs 27 deliberately selected
tests:

1. A site administrator exports reference material and a new user imports,
   attaches, and reads it under C0 without SSH, HTTP, Slurm, or rediscovery.
2. C1 root grants independently control listing, reading, writing/staging,
   deletion, confinement, and overwrite behavior.
3. C2 can inspect jobs and perform quotation/test-only validation, while
   submission, cancellation, and `--validate-first` escalation are denied.
4. C3 follows the MCP quote, validation, confirmation, scope, and recorded
   submission chain; malformed, dry-run, and mismatched evidence is rejected.
5. CLI help hides denied commands by default, can explain them with
   `--show-disallowed`, and denies direct invocation before effects.
6. Two profile-bound MCP processes expose different allowed tools/resources;
   restarts pick up policy changes, while alternate selectors and guessed URIs
   cannot escape the bound profile snapshot.
7. Bundled composite plugin workflows authorize before staging, and an
   external plugin without supported capability metadata is rejected.
8. Restricted-agent policy intersects with manifest authority, preserves
   cleanup/reconciliation, and never exposes general filesystem tools.
9. Missing, empty, unknown-version, and otherwise invalid profile policies fail
   closed rather than creating an unrestricted surface.

The acceptance module adds process-level fixtures with temporary fake `ssh`,
`squeue`, `sbatch`, and `scancel` executables plus a loopback HTTP server. It
also exercises C1 list/read/write/delete roots as four distinct grants. The
fixtures assert both permitted output and the absence of out-of-scope writes,
submission, or cancellation effects. All paths, configuration, archives, logs,
and profile records are temporary.

## Installed-distribution acceptance

`tools/check_capability_distribution.py` requires both a wheel and source
archive and creates two independent temporary pipx homes outside the checkout.
It verifies that imports originate in each pipx environment rather than the
working tree.

- The wheel is installed without extras. The CLI works under C0, the packaged
  `hpc_tools/data/filesystem_helper.py` is present, and `mcp` is absent.
- The source archive is installed with the `mcp` extra. Its CLI works under C2
  and an actual MCP stdio client starts the installed `hpc-mcp` executable.
- The protocol probe lists and invokes tools/resources for separate C0 and C2
  profiles, checks that trusted selectors are absent, proves alternate
  arguments cannot change the bound context, rejects a guessed cross-profile
  URI, and confirms submission is not exposed at either ceiling.

The pipx warnings about same-named commands in the user's normal `PATH` are
expected: every check invokes the exact executable in its temporary pipx home,
and the temporary homes are removed afterward. The checker neither replaces
nor modifies the user's normal installation.

The repository CI now installs the build and pipx tooling, runs the 27-case
acceptance tier, builds both distribution formats, and runs the same installed
checker. This makes the handoff checks durable rather than relying only on this
workstation's results.

## Acceptance evidence

The following focused and installed checks were run from the repository root:

```text
.venv/bin/python tools/run_capability_acceptance.py
  PASS; 9 scenarios, 27 tests

.venv/bin/python -m unittest discover -s tests -p test_capability_acceptance.py
  PASS; 3 process-level acceptance tests

env UV_CACHE_DIR=/tmp/hpc-tools-wp12-uv-cache uv build \
  --out-dir /tmp/hpc-tools-wp12-dist-final
  PASS; wheel and source archive built

python3 tools/check_capability_distribution.py \
  --wheel /tmp/hpc-tools-wp12-dist-final/hpc_tools-0.1.0-py3-none-any.whl \
  --sdist /tmp/hpc-tools-wp12-dist-final/hpc_tools-0.1.0.tar.gz
  PASS; wheel_cli_only, packaged_filesystem_helper, and
  sdist_optional_mcp_protocol

.venv/bin/python -m unittest discover -s tests
  PASS; 439 tests
```

The repository-required completion checks produced these literal results:

```text
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
  PASS; 439 tests

mkdocs build --strict
  PASS; strict site built with no warnings

git diff --check
  PASS
```

The literal `python3 -m unittest discover -s tests` command used the bare
system Python 3.10 environment, which lacks the declared `tomlkit` dependency.
It ran 151 tests and reported 29 import errors, all rooted in that missing
package. The supported project environment completed all 439 tests above.

`python3 tools/check_repo_hygiene.py .` reports the checkout's existing
`.ruff_cache`, `build`, `hpc_tools.egg-info`, and bytecode cache trees. They
were preserved rather than deleting unrelated working-tree artifacts. This is
a release-cleanliness limitation, reported separately from the passing
functional, documentation, and installed-distribution checks.

## Evidence boundaries

- **Unit/integration:** the scenario runner and supported-environment full suite
  use temporary local state and fake endpoints.
- **Installed distribution:** both wheel and source archive are independently
  installed outside the checkout; installed import provenance is asserted.
- **Optional MCP protocol:** an installed stdio server is exercised through a
  real MCP client, not a mocked FastMCP registry.
- **Documentation:** README and CI command coverage have regression assertions;
  strict MkDocs and repository validators are part of final validation.
- **Live cluster:** unrun by design. WP12 authorizes neither a real cluster
  installation nor an actual Slurm submission, and none was performed.

No release version, Git tag, publication archive, or DOI was created; those are
release decisions outside the work package.
