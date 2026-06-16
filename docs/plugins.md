# Plugin System

`hpc-tools` now supports a small plugin system so workflow-specific commands do
not have to accumulate in the core CLI.

## Scope Split

Keep the core CLI focused on:

- remote command execution
- profile and config handling
- reference-set management
- Slurm quoting, submission, accounting, and submission logs
- generic module discovery

Move workflow-specific helpers into plugins, for example:

- R package dependency scanning and install-job generation
- Python environment checks and environment bootstrapping
- Julia package and project helpers
- container-oriented workflow helpers

## Current State

The first implementation slice provides:

- plugin discovery through the `hpc_tools.plugins` entry-point group
- a local `hpc plugins list` command
- a local `hpc plugins info <name>` command
- bundled `python` and `r` plugins with local scan commands

The bundled `python` and `r` plugins are packaged with the core distribution so
the plugin contract is exercised immediately in development and release
installs.

The bundled Python plugin covers:

- `hpc python scan`
- `hpc python inspect-deps`
- `hpc python check`
- `hpc python plan-install`
- `hpc python submit-install`
- `hpc python verify-install`

The bundled R plugin covers:

- `hpc r scan`
- `hpc r check`
- `hpc r plan-install`
- `hpc r submit-install`
- `hpc r verify-install`

## Plugin API

Plugins register top-level subcommands through a narrow Python interface:

- `name`
- `description`
- `register(subparsers, profile)`
- `requires_profile(argv)`

This keeps the first API intentionally small. Plugins should rely on core helper
modules for SSH, Slurm, config, and submission-log behavior instead of
reimplementing that infrastructure.

## Packaging

Use Python entry points:

```ini
[options.entry_points]
hpc_tools.plugins =
    python = hpc_tools.plugins.python_support:get_plugin
    r = hpc_tools.plugins.r_support:get_plugin
```

External plugins should use the same group name and can be installed into the
same `pipx` environment with `pipx inject`.

## R Plugin Follow-On Work

The current R plugin covers:

1. local dependency scanning from scripts, sourced files, `DESCRIPTION`, and
   `renv.lock`
2. remote package visibility checks under a selected module stack
3. generation of architecture-aware Slurm install scripts for missing packages
4. staging, quoting, validating, submitting, and logging install jobs
5. verification of completed install jobs from their output files

When an R package install fails because of a non-R dependency, use package
metadata such as CRAN `SystemRequirements` to identify the missing library or
tool, check whether the site provides it as a module, and include that module in
both the install job and later runtime job scripts. JAGS-related R packages are
a common example: the R package may need a `JAGS` module loaded before install
and when running scripts that use the package.

Follow-on R work should continue in the plugin layer rather than expanding the
core CLI. The next likely additions are:

- package-source presets for common ecosystems such as INLA
- explicit system-dependency/module hints for package families such as JAGS
- richer parsing of dynamic package loading patterns

## Python Plugin Follow-On Work

The current Python plugin covers:

1. local dependency scanning from `import` statements
2. dependency-file inspection for `requirements.txt`, recursive requirement
   includes, simple `pyproject.toml` dependency lists, and `environment.yml`
   conda/pip sections
3. remote import checks under an explicit module stack
4. generation of Slurm install scripts that create or update a virtualenv
5. staging, quoting, validating, submitting, and logging install jobs
6. verification of completed install jobs from their output files

`hpc python plan-install` reuses dependency-file inspection so requirements
files, simple pyproject dependencies, and nested `environment.yml` `pip:`
entries can feed the import check and generated install job. Conda dependencies
from `environment.yml` are surfaced as notes instead of being pip-installed.

For small missing packages, prefer a venv created with
`python -m venv --system-site-packages` after loading the same site Python and
bundle modules that will be used at runtime. This preserves site-provided
scientific packages such as NumPy, SciPy, and Matplotlib while adding only the
missing package. Treat the successful install module stack as part of the
runtime contract: load the same modules before activating the venv in later job
scripts.

Follow-on Python work should continue in the plugin layer rather than expanding
the core CLI. Likely additions are:

- conda or micromamba environment checks
- environment export and recreate helpers
- architecture-appropriate wheel or build guidance
- job-script snippets for activating environments
- richer parsing of optional dependencies and package/import-name mismatches

## Notes

- Local-only plugin commands should report `requires_profile(argv) = False` so
  they work without a configured profile.
- Profile-aware plugin commands should defer to the same config and SSH
  mechanisms that the core CLI already uses.
- Closed submission runs should remain hidden from `hpc submissions list` even
  when later metadata events are appended; the submission-log fix added during
  this plugin slice is covered by regression tests.
