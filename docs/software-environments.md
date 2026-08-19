# Software environments and dependencies

On an HPC system, installing every dependency into a private environment is
usually a poor default. Site modules may already provide optimized scientific
libraries, MPI, CUDA, compilers, and matching language packages. Duplicating
them can waste quota, create thousands of files, bypass tuned libraries, or mix
incompatible binary stacks.

hpc-tools supports a module-first workflow:

1. discover dependencies locally;
2. inspect the site module catalogue;
3. check the exact runtime stack remotely;
4. install only what remains missing;
5. use a short compute-node installation job when compilation or architecture
   matters;
6. verify the evidence printed by that job;
7. preserve the module and environment contract for later runs.

The bundled Python, R, and C/C++ helpers are CLI extensions. Confirm that they
are installed before following this chapter:

```console
hpc plugins list
hpc plugins info python
hpc plugins info r
hpc plugins info cxx
```

## Choose the smallest suitable environment

| Approach | Prefer it when | Main risks or limits |
| --- | --- | --- |
| Site modules only | The complete runtime is already available and compatible | Module defaults can change; pin versions. |
| Modules plus Python venv | A few pip packages are missing from a strong site Python stack | The venv remains tied to the Python and binary modules used to create it. |
| Modules plus an R user library | A few CRAN or Bioconductor packages are missing | Compiled packages can be OS-, CPU-, R-, and toolchain-specific. |
| Conda or micromamba environment | The project needs conda-specific binaries or a tightly pinned binary stack | Large metadata footprint, slower startup, duplication of site libraries. |
| Apptainer container | A large or repeatedly rebuilt stack must be reused consistently | Image build, provenance, bind mounts, accelerator support, and site policy still need attention. |

Do not choose solely by familiarity from a laptop. Check storage quotas,
file-count limits, target node architecture, network policy, and the site's
recommended software stack first.

## Inspect the remote software catalogue

Search Lmod without changing an environment:

```console
hpc --profile example module-spider Python
hpc --profile example module-spider SciPy-bundle
hpc --profile example module-spider R-bundle-CRAN
hpc --profile example module-spider CMake
```

Then check a candidate stack using explicit versions. The exact import or
package check is stronger evidence than a module name:

```console
hpc --profile example run \
    'module load Python/3.13.1 SciPy-bundle/2025.03 && python --version'
```

Module availability on a login node does not guarantee that the module is
appropriate for every compute partition. Native packages can depend on CPU
features, CUDA versions, MPI implementations, and shared libraries supplied by
the module stack.

## Python dependencies

### Scan imports and dependency files

Scan a local script or project directory:

```console
hpc python scan analysis.py
hpc python scan src/
```

The scan finds straightforward `import` and `from ... import ...` statements
and reports their source locations. It cannot fully resolve dynamic imports,
optional extras, plugin discovery, or conditional dependencies.

Inspect declared project dependencies separately:

```console
hpc python inspect-deps .
```

This inspects supported requirements files, simple `pyproject.toml`
dependencies, and `environment.yml` content. It reports conda dependencies,
nested pip dependencies, channels, Python pins, and likely native-library
hints. Conda dependencies are reported for interpretation; they are not
silently converted into pip installations.

Treat lock files and maintained dependency declarations as stronger evidence
than imports alone. Conversely, do not blindly run `pip install -r
requirements.txt` if half the scientific stack is already supplied by
compatible modules.

Package distribution names and import names can differ. For example:

| Distribution name | Import name |
| --- | --- |
| `scikit-learn` | `sklearn` |
| `PyYAML` | `yaml` |
| `opencv-python` | `cv2` |
| `beautifulsoup4` | `bs4` |

The remote check is import-based, while pip installation uses distribution
names. Inspect the plan whenever these names differ.

Dependency files let `plan-install` apply its known import-to-distribution
mappings. An explicit `--package` is primarily an import check and can become
the pip name in a generated plan. When the names differ and no supported
dependency file supplies the distribution name, review and correct the written
installation script before submission.

### Check the real remote stack

Repeat `--module` in load order for the complete intended runtime:

```console
hpc --profile example python check analysis.py \
    --module Python/3.13.1 \
    --module SciPy-bundle/2025.03 \
    --module matplotlib/3.10.1
```

Add a dependency missed by static inspection with a repeated `--package`:

```console
hpc --profile example python check analysis.py \
    --module Python/3.13.1 \
    --package sklearn \
    --package yaml
```

The result separates imports into available and missing groups. A missing
import under one module stack does not prove that the package is absent from
the cluster; search compatible bundle modules before planning a private
installation.

### Plan a small venv installation

When only a few packages remain missing, generate a local Slurm installation
script:

```console
hpc --profile example python plan-install . \
    --module Python/3.13.1 \
    --module SciPy-bundle/2025.03 \
    --venv /data/researcher/projects/model/.venv-icelake-py313 \
    --partition cpu-icelake \
    --arch-guard icelake \
    --output install-python-packages.slurm
```

`plan-install` performs the remote availability check and writes a script only
when packages remain missing. It refuses to overwrite the output unless you
pass `--force`.

Supply a resolved absolute remote path to `--venv`. The current generator
quotes that value as a literal shell assignment; a value such as
`$VSC_DATA/project/.venv` is not expanded in the generated script. Resolve the
site variable first and inspect the written `VENV=` line.

By default, the generated venv uses `--system-site-packages` so that it can
reuse the loaded module stack. Use `--no-system-site-packages` only when you
have a concrete reason to isolate the venv from site packages; doing so may
force pip to rebuild large scientific dependencies. The module stack used to
create the venv remains part of its runtime contract either way.

The generated script creates or updates the named venv; it does not remove
packages left by an earlier install. Use a new environment path when changing
Python, compiler, architecture, or binary-module families instead of mutating
an old environment into an ambiguous mixture.

Place reusable environments in project or data storage when home quotas and
file counts are tight. Keep temporary builds and package caches on node-local
or scratch storage. Avoid `pip install --user`: one user site shared by several
Python module versions is difficult to reproduce and can silently mix
incompatible packages.

### Submit and verify the installation

Preview the complete remote staging, quote, validation, and submission path:

```console
hpc --profile example --dry-run python submit-install \
    --directory '$VSC_DATA/projects/model/install' \
    --account project123 \
    --partition cpu-icelake \
    install-python-packages.slurm
```

Then make the real submission:

```console
hpc --profile example python submit-install \
    --directory '$VSC_DATA/projects/model/install' \
    --account project123 \
    --partition cpu-icelake \
    install-python-packages.slurm
```

This command writes the local script into the remote directory. If the profile
has a quote helper, it quotes the job unless `--skip-quote` is supplied. It
runs `sbatch --test-only` and then submits the real job by default. There is no
confirmation pause after successful validation. `--no-validate-first` removes
that safety check and should be exceptional.

Staging uses the local basename by default and overwrites a remote script with
the same name. Use a dedicated directory or `--remote-name`, and preview the
operation, when preserving an earlier installation plan matters.

After the job completes, verify the markers in its remote output:

```console
hpc --profile example python verify-install \
    --job-output '$VSC_DATA/projects/model/install/python-package-install-123456.out' \
    --package sklearn \
    --package yaml \
    --require-venv-fragment .venv-icelake-py313
```

`verify-install` reads and parses the completed job log. It does not activate
the venv and retry the imports live. Check the job's scheduler state and full
output as well, especially when compilation emitted warnings.

Load the same modules before activating the venv in every runtime job:

```bash
module load Python/3.13.1 SciPy-bundle/2025.03
source /data/researcher/projects/model/.venv-icelake-py313/bin/activate
python analysis.py
```

## R dependencies

### Discover and check packages

Scan local R code:

```console
hpc r scan analysis.R
hpc r scan R/
```

The scanner recognizes common static uses of `library()`, `require()`,
`requireNamespace()`, and namespace operators. Review `renv.lock`,
`DESCRIPTION`, `NAMESPACE`, and maintained package lists too; dynamic package
names and conditional loads can escape a static scan.

Select an R module and compatible bundle modules, then check the actual remote
namespace resolution:

```console
hpc --profile example r check analysis.R \
    --module R/4.5.0 \
    --cran-bundle R-bundle-CRAN/2025.03 \
    --bioc-bundle R-bundle-Bioconductor/3.21-R-4.5.0
```

Add explicit packages with repeated `--package`. The decisive question is
whether `requireNamespace()` succeeds under this exact module combination, not
whether a bundle has a promising name.

Before installing a missing package, inspect native and external requirements.
Failures mentioning headers, libraries, configure checks, or tools often need
an additional site module such as JAGS, GDAL, NetCDF, HDF5, or a compiler.
Those modules may also be required whenever the installed package is loaded.

The plan command exposes options for the R module and the two bundle modules,
but not arbitrary external dependency modules. Add any verified JAGS, GDAL,
compiler, or similar `module load` lines to the generated script and review it
before submission.

### Generate an architecture-aware install job

```console
hpc --profile example r plan-install analysis.R \
    --module R/4.5.0 \
    --cran-bundle R-bundle-CRAN/2025.03 \
    --bioc-bundle R-bundle-Bioconductor/3.21-R-4.5.0 \
    --partition cpu-icelake \
    --arch-guard icelake \
    --output install-r-packages.slurm
```

The default library path is designed for architecture-aware VSC variables.
The current generated script also explicitly requires `VSC_DATA`,
`VSC_OS_LOCAL`, `VSC_ARCH_LOCAL`, and `EBVERSIONR`. Therefore
`--library-root-template` alone does not make this installer portable to a
non-VSC cluster. On another site, use `r scan` and `r check`, then prepare a
site-specific installation job or container until the generator supports that
environment. Do not impose the VSC layout on an unrelated system.

For old research environments, a required package may have disappeared from
the current CRAN index. `--archive-package PKG=URL` can put an explicit source
archive into the generated plan. `--extra-repo NAME=URL` can add a repository
such as a project-specific or INLA repository. Treat both URLs and versions as
reproducibility inputs and review them before execution.

The generated installer uses `install.packages()` with CRAN and any explicitly
added repositories. It does not automatically route a missing Bioconductor
package through `BiocManager`. Prefer a compatible Bioconductor bundle; if that
does not contain the package, adapt and review the installation logic rather
than assuming the generated CRAN-style command is sufficient.

Submit the generated script with the same guarded workflow:

```console
hpc --profile example r submit-install \
    --directory '$VSC_DATA/projects/model/install' \
    --account project123 \
    --partition cpu-icelake \
    install-r-packages.slurm
```

The command stages the local script remotely, quotes when configured, validates
with Slurm, submits, and records a successful real submission locally. It is a
chargeable scheduler action, not a planning command.

Verify the recorded namespace and library-path evidence:

```console
hpc --profile example r verify-install \
    --job-output '$VSC_DATA/projects/model/install/r-package-install-123456.out' \
    --package DESeq2 \
    --package dplyr \
    --require-lib-fragment icelake
```

As with Python, this parses the job output; it does not perform a fresh remote
load. Preserve the R module, bundle modules, external dependency modules,
`.libPaths()`, and `sessionInfo()` as part of the runtime contract.

## C and C++ dependencies

Scan local CMake and source files for dependency hints:

```console
hpc cxx scan .
hpc cxx scan CMakeLists.txt --json
```

The scanner recognizes CMake `find_package()` and `FetchContent_Declare()`
calls plus a small catalogue of common headers. It marks dependencies such as
MPI, OpenMP, CUDA, BLAS, LAPACK, FFTW, HDF5, NetCDF, PETSc, Trilinos, and
Kokkos as HPC-sensitive.

This is an orientation tool, not a package resolver. It does not evaluate
CMake conditionals, discover every transitive dependency, test ABI
compatibility, or install anything. Confirm dependencies with the build system,
module catalogue, and a real configure step.

For a supported small dependency, render a pinned, overridable CMake snippet:

```console
hpc cxx fetchcontent CLI11 --project-option-prefix SIMULATION
```

Supported candidates currently include CLI11, Catch2, doctest, fmt,
nlohmann_json, and spdlog. Review the emitted repository and tag before adding
the snippet to a project. Prefer site modules, Spack, or centrally built
packages for HPC-sensitive libraries; fetching a second MPI, CUDA, HDF5, or
BLAS stack into one build is a common route to ABI and performance problems.

FetchContent also assumes network access during configuration unless sources
are pre-populated or overridden. Cluster compute nodes are often
network-restricted, so keep an offline or mirrored source strategy.

Continue with [Deploying and building software remotely](remote-builds.md) for
toolchain selection, configuration, compilation, and testing.

## Capture a reproducible environment record

For any environment reused beyond an experiment, retain:

- the cluster profile and node architecture;
- exact module names and versions in load order;
- the Python executable and `pip list`/`pip freeze`, or R `.libPaths()` and
  `sessionInfo()`;
- dependency declarations and lock files;
- the generated installation script and its Slurm job output;
- external repositories, archives, and source checksums where practical;
- compiler, CUDA, MPI, and native-library versions;
- the environment path and storage policy;
- import or namespace verification results.

A successful install is not enough. Run a small application-level test under
the same modules, node class, and job environment that production work will
use. Then update the local lifecycle record as described in
[Tracking work from submission to analysis](submissions.md).

## Diagnose installation failures

| Failure | Check first | Safer response |
| --- | --- | --- |
| Package appears missing | Exact remote import/namespace check under all intended modules | Search compatible bundles before installing. |
| Compiler or header missing | Full build log and module catalogue | Load a compatible toolchain or native dependency module. |
| Binary loads on one node class only | CPU architecture, OS, module stack, shared-library links | Build separate architecture-qualified environments. |
| Home quota or inode limit reached | `hpc quota` and `hpc storage inspect` | Move the environment and caches to approved project/data/scratch locations. |
| Dependency download fails | Cluster network policy, mirrors, cached sources | Prepare an offline source strategy; repeated retries will not create network access. |
| Verification says `UNKNOWN` or missing | Correct job-output path and generated marker block | Inspect the entire log and scheduler state before rerunning. |
| Environment grows into a large fragile stack | Native dependencies, rebuild frequency, startup metadata load | Move to a reviewed Apptainer workflow rather than layering more packages. |

Do not solve a failed installation by broadening permissions, installing into
the system Python or R tree, or adding unreviewed repositories. The failure log
usually identifies which layer—language package, native library, compiler,
network, storage, or architecture—needs attention.
