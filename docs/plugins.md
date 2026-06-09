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
- a bundled `r` plugin with `hpc r scan <path>`

The bundled `r` plugin is packaged with the core distribution so the plugin
contract is exercised immediately in development and release installs.

Its current subcommands are:

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

Follow-on R work should continue in the plugin layer rather than expanding the
core CLI. The next likely additions are:

- package-source presets for common ecosystems such as INLA
- richer parsing of dynamic package loading patterns

## Python Plugin Follow-On Work

Once the R plugin pattern is stable, the next likely external plugin is Python
environment support for tasks such as:

- conda or micromamba environment checks
- environment export and recreate helpers
- architecture-appropriate wheel or build guidance
- job-script snippets for activating environments

## Notes

- Local-only plugin commands should report `requires_profile(argv) = False` so
  they work without a configured profile.
- Profile-aware plugin commands should defer to the same config and SSH
  mechanisms that the core CLI already uses.
- Closed submission runs should remain hidden from `hpc submissions list` even
  when later metadata events are appended; the submission-log fix added during
  this plugin slice is covered by regression tests.
