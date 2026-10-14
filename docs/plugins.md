# Plugin System

`hpc-tools` now supports a small plugin system so workflow-specific commands do
not have to accumulate in the core CLI.

## Scope Split

Keep the core CLI focused on:

- remote command execution
- profile and config handling
- reference-set management
- Slurm quoting, submission, accounting, and submission databases
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
- bundled `benchmark`, `cxx`, `python`, and `r` plugins with local analysis and scan commands

The bundled `benchmark`, `cxx`, `python`, and `r` plugins are packaged with the core distribution so
the plugin contract is exercised immediately in development and release
installs.

The bundled benchmark plugin covers:

- `hpc benchmark summarize`
- `hpc benchmark compare`

The bundled C/C++ plugin covers:

- `hpc cxx scan`
- `hpc cxx fetchcontent`

Use `hpc cxx scan` to inspect CMake files and common C/C++ includes for
dependency hints. It marks dependencies such as MPI, OpenMP, HDF5, BLAS/LAPACK,
CUDA, PETSc, Trilinos, Kokkos, and NetCDF as HPC-sensitive dependencies: prefer
site modules, Spack, or site-provided packages for those. Use
`hpc cxx fetchcontent` only for small, lightweight dependencies such as CLI11, Catch2, doctest, fmt,
nlohmann_json, or spdlog, and keep the generated CMake option overridable for
network-restricted cluster builds.

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

Plugins register top-level subcommands through a versioned Python interface:

- `name`
- `description`
- `contract_version = 1`
- `operations`, a non-empty tuple of `OperationDescriptor` values
- `register(subparsers, profile)`
- `requires_profile(argv)`

Every leaf parser registered by the plugin must set an `operation_id`, and its
full CLI path and operation ID must exactly match one declared descriptor. An
external plugin may declare CLI bindings only, may use only the default
operation resolver, must keep each binding below its own top-level command, and
must not collide with a core operation ID. Missing metadata, an unknown
contract version, or an undeclared/mismatched command rejects the plugin. The
rejected command is not registered. `hpc plugins list` shows its contract as
`rejected`, while `hpc plugins info NAME` reports the contract error.

For example, a C1 read-only plugin operation can declare:

```python
from hpc_tools.capabilities import CapabilityLevel
from hpc_tools.operation_registry import OperationDescriptor
from hpc_tools.plugin_system import PLUGIN_CONTRACT_VERSION

class ExamplePlugin:
    name = "example"
    description = "Example cluster inspection"
    contract_version = PLUGIN_CONTRACT_VERSION
    operations = (
        OperationDescriptor(
            id="example.inspect",
            minimum_level=CapabilityLevel.CLUSTER_DISCOVERY,
            scopes=(),
            effects=("remote-read",),
            cli=("example inspect",),
            profile_required=True,
        ),
    )
```

The CLI authorizes the declared operation before dispatch. Profile-free local
analysis is limited to C0 descriptors with no scopes, site features, path
bindings, or effects beyond local reads/execution. Plugins should rely on core
helpers for bounded filesystem access, SSH, Slurm, config, and submission
records instead of reimplementing that infrastructure.

The metadata contract governs trusted installed Python code; it is not a
sandbox. Python imports happen before metadata can be inspected, so a malicious
plugin or import-time side effect remains under the authority of the local
Python environment. Install only plugins you trust.

## Packaging

Use Python entry points:

```ini
[options.entry_points]
hpc_tools.plugins =
    benchmark = hpc_tools.plugins.benchmark_support:get_plugin
    cxx = hpc_tools.plugins.cxx_support:get_plugin
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

Python and R `submit-install` commands are authorized as one compound C3
operation before the local script is read or uploaded. Staging uses the bounded
filesystem helper and the profile's `remote_roots.write` grants; it refuses an
existing remote script unless `--force` is explicit. `verify-install` reads the
output through the same helper under `remote_roots.read`. Dry runs validate
paths and render the later quote/validation/submission commands without
uploading, submitting, logging, or writing a local plan file.

Python and R package checks are classified as remote execution, not passive
file reads. Module loading and language package discovery can run module or
package initialization code. Their operation descriptors deliberately record
`remote-execute`; a plugin must not relabel such checks to evade policy.

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

On VSC clusters, keep Python venvs out of home, create them in the relevant
project/data/scratch location, and include the target microarchitecture when the
cluster is heterogeneous. The generated install script already uses
`--no-cache-dir` and can guard on `VSC_ARCH_LOCAL`; for project workflows based
on `requirements.txt` plus `modules.txt`, inspect those files before choosing
the module stack and package install list.

If the package set is large or the batch-job startup load matters more than the
build cost, prefer an Apptainer container that freezes the Python or R stack
instead of extending the same shared-filesystem install again. If the user
already has a definition file, point them at `hpc write-container --kind
generic` or `hpc install-container --kind generic` so they can build that
recipe inside a Slurm job.

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
  when later metadata events are appended; the submission-database fix added during
  this plugin slice is covered by regression tests.
