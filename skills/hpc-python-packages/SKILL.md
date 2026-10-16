---
name: hpc-python-packages
description: Verify whether a Python script can import packages from site Python modules or bundle modules on a configured HPC profile, and plan a small virtualenv install only for packages still missing.
---

# HPC Python Packages

## Remote Access

Inspect the selected profile before using remote commands:

```bash
hpc --profile <profile> capabilities
hpc --profile <profile> --help
```

For policy denials, profile selection, optional helpers, login-gate handling,
`--dry-run`, and remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

Use [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) when choosing
venv, cache, or temporary build locations. Use
[`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
before submitting chargeable compute-node install jobs. Use
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
module-version and job-script reproducibility guidance.

For VSC clusters, keep this workflow aligned with the VSC Python package
management guidance:
<https://docs.vscentrum.be/compute/software/installing_software/python_package_management.html>.

## Goal

Before the user submits a Python job, determine whether the script's imports are
already satisfied by site modules. On many clusters, packages such as `numpy`,
`scipy`, `matplotlib`, `pandas`, or other scientific libraries are already
provided through Python or bundle modules. Do not reinstall those large packages
into a personal environment unless the site stack cannot satisfy them.

The deliverable is a concrete import status summary:

- imports satisfied by the selected Python and bundle modules;
- imports still missing after the best available module stack is loaded;
- the exact module stack that must be loaded before activating any venv;
- the recommended virtualenv path and install method when local packages are
  still required;
- any package/import-name mismatches that need manual review.

## Discovery Order

Start by identifying imports locally from the script or project files. Use the
bundled `hpc python scan` plugin command when it is available:

```bash
hpc python scan <script-or-project-dir>
```

When the project has dependency files, inspect them before choosing an install
strategy:

```bash
hpc python inspect-deps <script-or-project-dir>
```

For profile-aware workflows, prefer the plugin commands when they cover the
task:

```bash
hpc --profile <profile> python check <script-or-project-dir> --module <Python-or-bundle-module>
hpc --profile <profile> python plan-install <script-or-project-dir> --module <Python-or-bundle-module> --venv <remote-venv> --partition <partition> --output install-python-packages.slurm
hpc --profile <profile> python submit-install install-python-packages.slurm --directory <remote-dir> --account <account>
hpc --profile <profile> python verify-install --job-output <remote-job-output> --package <import-name>
```

Repeat `--module` for every module in the runtime stack. For example, a site
may provide `numpy` and `scipy` through a scientific bundle and `matplotlib`
through a separate module; both modules must be loaded before checking imports,
creating the venv, and running the final job.

`hpc python plan-install` consumes the same dependency-file inspection used by
`inspect-deps`: requirements files, simple pyproject dependencies, and nested
`environment.yml` `pip:` entries are included in the import check and install
plan. Conda dependencies from `environment.yml` are reported as notes, not
silently pip-installed.

If the plugin is unavailable or the scan needs manual confirmation, fall back to
fast local searches and dependency files:

```bash
rg -n '^(from|import) ' <script-or-project-dir>
rg -n 'requirements|dependencies|pip install|venv|conda|micromamba' <script-or-project-dir>
```

If the project contains `requirements.txt`, `requirements-*.txt`,
`pyproject.toml`, `setup.cfg`, `environment.yml`, or lock files, use those as
stronger dependency sources than ad hoc imports. Call out dynamic imports,
optional extras, import/package-name differences, and conditional imports.
Prefer `hpc python inspect-deps` for this pass; it reports requirements,
simple pyproject dependencies, conda dependencies, nested pip dependencies,
channels, Python version pins, and likely binary/runtime dependencies.

## Requirements Files

When a project has `requirements.txt`, treat it as the dependency source of
truth for discovery and status checks, but do not blindly turn it into
`pip install -r requirements.txt`. First check which requirements are already
satisfied by the selected site Python and bundle modules.

If the requirements file includes large packages that the site already provides,
such as `numpy`, `scipy`, `matplotlib`, or `pandas`, keep those satisfied by
modules and install only the packages still missing into the venv. This avoids
duplicating or overriding the site scientific stack.

Using `python -m pip install -r requirements.txt` inside the venv is reasonable
when the file is intentionally scoped to user-installed packages, or when live
checks show the site modules do not satisfy the project. For mixed scientific
projects, prefer splitting requirements into site-provided dependencies and
user-installed dependencies, or pass explicit `--package <import-name>` entries
for the missing imports that should be installed.

## Conda Environment Files

When a project has `environment.yml`, treat it as a stronger dependency source
than imports, but do not automatically run `conda env create -f
environment.yml`. First inspect the `dependencies:` list, nested `pip:` entries,
Python version pins, channels, and binary stack requirements such as CUDA, MPI,
HDF5, GDAL, or compiler/runtime packages.

If the file mostly names packages already available through site modules, such
as Python, `numpy`, `scipy`, `matplotlib`, or `pandas`, prefer the same
modules-plus-venv workflow used for `requirements.txt`: load the site modules,
create a venv with `--system-site-packages`, and install only missing pip-only
packages.

Use conda or micromamba only when the YAML depends on conda-specific packages,
hard binary version pins, or package combinations the site module stack cannot
reasonably reproduce. In that case, inspect site guidance first with
`hpc --profile <profile> site-env`, install into project/data storage rather
than home when the environment will be large, and avoid creating many-file
conda environments on quota-sensitive filesystems without checking storage
constraints.

For mixed YAML files, separate the interpretation:

- site modules for Python and large scientific/runtime libraries when they
  satisfy the project;
- venv pip installs for small pip-only packages still missing;
- conda or micromamba only for the parts that truly require conda-managed
  binaries.

## Package/Import Name Mismatches

Keep package names and import names separate. The runtime check is import-based,
but pip installation is package-name based. Many packages match directly, but
common exceptions include `scikit-learn` -> `sklearn`, `PyYAML` -> `yaml`,
`opencv-python` -> `cv2`, and `beautifulsoup4` -> `bs4`.

When a dependency file names a package whose import name differs, verify both
names explicitly. Use the package name for pip install planning and pass the
import name with `--package <import-name>` when checking the runtime
environment. For example, check `sklearn` even when the requirement line says
`scikit-learn`.

## Check Remote Modules

Search software through Lmod before recommending a user install:

```bash
hpc --profile <profile> module-spider Python
hpc --profile <profile> module-spider Python-bundle-PyPI
hpc --profile <profile> module-spider SciPy-bundle
hpc --profile <profile> module-spider <package-or-tool>
```

Inspect full module names when a candidate exists:

```bash
hpc --profile <profile> module-spider <full-module-name>
```

Prefer explicit module versions in job scripts. Verify the actual runtime
environment with the same module loads that the user will use in the job:

```bash
hpc --profile <profile> run 'module load <module> <bundle-module> && python --version && python -m pip --version'
hpc --profile <profile> run 'module load <module> <bundle-module> && python3 -m pip list -v'
hpc --profile <profile> run 'module load <module> <bundle-module> && python -c "import importlib.util; print(importlib.util.find_spec(\"<import-name>\"))"'
```

Do not claim a package is unavailable based only on `module spider`. The
decisive check is whether `python` with the chosen module stack can resolve the
import with `importlib.util.find_spec()`.

## Venv Recommendation

When only a few packages are missing, prefer a virtualenv layered on the site
modules:

```bash
module load <module> <bundle-module>
python -m venv --system-site-packages <remote-venv>
source <remote-venv>/bin/activate
python -m pip install <missing-package>
python -c "import <missing-import>"
```

This keeps large site-provided packages such as `numpy`, `scipy`, and
`matplotlib` out of the user install while adding only the missing package, such
as `mmh3`. Treat the module stack used to create the venv as part of the
runtime contract: load the same modules before activating the venv in every
later job.

Avoid `pip install --user` for HPC jobs. A user-site install is shared across
multiple Python module versions and can silently mix incompatible packages. A
named venv tied to the selected module stack is easier to reason about and
remove.

For VSC clusters, the normal pip install line should use `--no-cache-dir` to
avoid stale cache effects and unnecessary cache growth. For packages with
native build dependencies supplied by loaded modules, consider
`--no-build-isolation` so pip uses the compilers and build dependencies from
the module environment instead of trying to build in an isolated environment.

## Venv Location

When the relevant remote project directory is clear, create the venv inside
that project tree, for example `<project>/.venv-<cluster-or-module-stack>`.
This keeps dependencies, code, and project-specific reproducibility evidence
together and makes cleanup straightforward.

If the target project directory is not clear from the script path, dependency
files, or user request, ask the user where the venv should live before planning
the install. Do not guess between home, scratch, data, and project storage when
the choice affects quotas, lifetime, or collaboration.

Use project/data storage rather than home for large environments or
environments that will be reused by batch jobs. Keep pip cache and temporary
build directories in node-local or scratch temporary storage, not inside the
project venv. Do not put project-specific venvs under `~/.config/hpc-tools`;
that location is for reusable hpc-tools profile references.

## Architecture-Specific Environments

On VSC clusters and other heterogeneous systems, create the venv on a node with
the same microarchitecture as the nodes that will run the Python job. Native
scientific Python packages may compile or install architecture-specific code
even when the top-level package is imported from Python.

Use `${VSC_ARCH_LOCAL}` to record the current microarchitecture and include it
in the venv name when useful, for example `<project>/venv-${VSC_ARCH_LOCAL}`.
If the same project will run on multiple node architectures, create a separate
venv for each architecture and load the matching module stack before activating
each venv.

When a project already has a `requirements.txt` file and optionally a
`modules.txt` file, use those files as evidence for the module stack and pip
dependencies, but still verify which packages are already provided by loaded
modules before installing. The `hpc python plan-install` workflow remains useful
when you need a generated Slurm install job, import-status checks,
account-aware submission, or dependency inspection before installation.

When the site provides a `uv` module and the project is already using `uv`, it
can be a reasonable alternative package manager. Apply the same module-first,
architecture-specific, no-home-venv, and runtime-module-stack rules.

## Runtime Job Snippet

The final Slurm job should load the same modules before activating the venv.
Use explicit module versions when possible:

```bash
module load <module> <bundle-module> <native-dependency-module>
source <remote-venv>/bin/activate
python -c "import <import-name>"
python <script.py>
```

Load modules before activating the venv so the venv sees the same Python,
shared libraries, and site packages that were present during installation.

## Compute-Node Install Workflow

When packages may compile native extensions or the install involves many
packages, prefer a short Slurm install job on the target partition over a
login-node install. Login nodes often have process runtime limits, and long or
parallel package installs can create load that affects other users. Keep
login-node installs for small, quick, pure-Python additions only; otherwise use
a batch install job. Use a pilot-first process:

1. choose and verify the exact Python and bundle modules;
2. generate a small install job for the intended partition and CPU class;
3. create the venv with `--system-site-packages` unless the user explicitly
   wants isolation from site packages;
4. install only the packages still missing after module checks;
5. place pip cache and build artifacts in `${VSC_SCRATCH_NODE}`, `${TMPDIR}`, or
   `/tmp`, not in durable config directories;
6. end the job with explicit `importlib.util.find_spec()` verification for each
   missing package;
7. quote the pilot job when the site uses credits;
8. submit with validation first;
9. after completion, inspect the job output and confirm the venv path and
   import status.

Use:

```bash
hpc --profile <profile> python plan-install <target> --module <module> --venv <remote-venv> --partition <partition> --output install-python-packages.slurm
hpc --profile <profile> python submit-install install-python-packages.slurm --directory <remote-dir> --account <account>
hpc --profile <profile> python verify-install --job-output <remote-job-output> --package <import-name>
```

The generated install script should print the loaded module list, Python
executable, Python version, temporary build root, and import status lines. Those
lines are the evidence that the venv was created under the intended stack.

## Native Extension Build Requirements

If a package build fails because headers, libraries, compilers, CUDA, MPI, HDF5,
GDAL, BLAS/LAPACK, GEOS, PROJ, NetCDF, or command-line build tools are missing,
inspect the build log before retrying. Map the missing component to site modules
with:

```bash
hpc --profile <profile> module-spider <dependency>
```

Load compiler, CMake, CUDA, MPI, HDF5, GDAL, and other native dependency modules
during the install job when the package requires them. Keep the successful
module stack in later runtime jobs too; native Python extensions may link
against libraries provided by those modules.

## Container Fallback

If the dependency stack is large, repeatedly rebuilt, or causes unacceptable
filesystem load at install time or batch-job startup, prefer an Apptainer
container over another ad hoc venv. Use the container when the user needs a
stable, reusable environment that bundles Python plus native system libraries
and package dependencies together.

The same module-first checks still matter: verify what the project needs, then
decide whether the right answer is a venv layered on site modules or a
container built from those dependencies. When recommending a container, point
the user at the site/container workflow that creates the image from a package
list or environment spec. If the user already has an Apptainer definition
file, use `hpc write-container --kind generic` or
`hpc install-container --kind generic` so the recipe is built in a Slurm
job instead of on the login node.

## Reproducibility Capture

For installs that will be reused, keep enough evidence to recreate the
environment. The install job output should capture:

- `module list`;
- `python --version`;
- `python -c "import sys; print(sys.executable); print(sys.path)"`;
- `python -m pip list`;
- `python -m pip freeze`;
- the venv path and whether it used `--system-site-packages`;
- import verification for every required import name.

Store the job output or a short environment note next to the project or run
metadata. Avoid storing this durable run evidence under `~/.config/hpc-tools`
unless it is a reusable profile reference rather than project-specific state.

## Output

Summarize the result in three groups:

- available through the selected Python environment;
- missing and likely requiring a venv install;
- uncertain because the import is dynamic, optional, or has a package/import
  name mismatch.

When installation is required, also report:

- the exact module stack used for verification;
- the venv path;
- whether the venv uses `--system-site-packages`;
- the activation snippet for later job scripts.

## Limits

The plugin's static scan resolves straightforward `import`, `from ... import`,
`requirements.txt`, and simple `pyproject.toml` dependencies. It cannot fully
resolve dynamic imports, optional extras, or all package/import-name mismatches.
Use `--package <import-name>` to add explicit imports when needed.

For packages whose PyPI name differs from the import name, check both names
manually before installing. The runtime check is import-based; pip installation
is package-name based.
