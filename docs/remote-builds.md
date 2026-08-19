# Deploying and building software remotely

Remote deployment with hpc-tools means creating or inspecting a source
checkout on the cluster, selecting a reproducible toolchain, and running
bounded build and test commands. It is not an automated release system and it
does not synchronize a local working tree with the cluster.

The core building blocks are:

- `hpc projects` and `hpc storage inspect` for placement;
- `hpc clone` for a new remote Git checkout;
- `hpc repo status` for read-only inspection;
- `hpc module-spider` for toolchain discovery;
- `hpc run` for an explicitly supplied remote command;
- `hpc submit` when a substantial build or test belongs on a compute node;
- `hpc cxx` for limited local C/C++ dependency assistance.

Because `hpc run` passes an arbitrary command to the remote login shell, it
cannot protect you from a destructive or badly quoted command. Preview it and
keep each operation narrow.

## Choose the remote location

Before cloning, inspect the configured project root and storage context:

```console
hpc --profile example projects
hpc --profile example quota
hpc --profile example storage inspect '$VSC_DATA/projects'
```

Choose storage based on its contract, not just available bytes:

- source and reproducible build instructions belong in durable project or data
  storage;
- build trees can be large and metadata-heavy, so check file-count quotas;
- temporary compilation files can use approved scratch or node-local storage;
- final executables must remain reachable from the compute nodes that run
  them;
- purgeable scratch is not the only copy of source or irreplaceable artifacts.

A profile's `projects_dir` is a convenience default, not proof that every
project belongs there.

## Clone a repository

Preview the remote clone:

```console
hpc --profile example --dry-run clone \
    https://github.com/example/simulation.git \
    --branch main \
    --directory '$VSC_DATA/projects' \
    --name simulation
```

Then run it:

```console
hpc --profile example clone \
    https://github.com/example/simulation.git \
    --branch main \
    --directory '$VSC_DATA/projects' \
    --name simulation
```

`hpc clone` performs a real `git clone` on the remote host. This is usually
preferable to copying a local working tree: Git preserves the upstream URL,
branch structure, and commit identity, while avoiding local build artifacts and
uncommitted files.

It also means that the login node needs repository access. Private
repositories require an approved authentication method, and compute or login
nodes may have restricted outbound network access. Do not put access tokens in
the hpc-tools profile or command history.

Verify the result:

```console
hpc --profile example repo status \
    --directory '$VSC_DATA/projects/simulation'
```

Record the exact commit before building:

```console
hpc --profile example run \
    'git -C "$VSC_DATA/projects/simulation" rev-parse HEAD'
```

## Inspect before updating

`hpc repo status` is intentionally read-only. hpc-tools does not automatically
pull, merge, clean, reset, or discard remote work.

Before an update, inspect:

```console
hpc --profile example repo status \
    --directory '$VSC_DATA/projects/simulation'
```

Stop if the worktree contains changes you do not understand. They may be
remote edits, generated configuration worth preserving, or another user's
work. Also identify the current branch and intended upstream; “update” is
ambiguous when a checkout is detached, tracks a feature branch, or has diverged.

For a clean checkout that is intentionally tracking `origin/main`, preview a
fast-forward-only update:

```console
hpc --profile example --dry-run run \
    'git -C "$VSC_DATA/projects/simulation" pull --ff-only origin main'
```

Then run the same command without `--dry-run`. `--ff-only` refuses to create an
implicit merge commit. It does not protect uncommitted files from every
possible upstream change, which is why the status check comes first.

For published or benchmarked work, prefer checking out a reviewed tag or exact
commit rather than allowing a moving branch to define the build. Never use a
hard reset or cleanup command as a generic update strategy.

Continue with [Benchmarking on Slurm](benchmarking.md) when builds will be
compared for performance, or [Container workflows](containers.md) when the
reviewed inputs should produce an Apptainer image.

## Select a toolchain

Search for the required tools and libraries:

```console
hpc --profile example module-spider GCC
hpc --profile example module-spider CMake
hpc --profile example module-spider OpenMPI
hpc --profile example module-spider CUDA
```

Inspect exact versions in one remote shell:

```console
hpc --profile example run \
    'module purge && module load GCC/14.2.0 CMake/3.31.3 && gcc --version && cmake --version'
```

Use compatible modules from one toolchain generation. Mixing an application
built with one compiler or MPI implementation with another runtime stack can
cause link errors, crashes, or subtle performance problems. `module purge` is
a useful clean start where the site supports it, but some sites require
baseline modules; follow local guidance.

The system compiler on a login image may be older than the project requires.
Conversely, the newest available compiler is not automatically the safest
choice for a production dependency stack. Match the project's language
standard, tested toolchains, site libraries, and target node architecture.

## Inspect C and C++ dependencies

Run the local static helper before configuring a CMake project:

```console
hpc cxx scan /path/to/local/simulation
```

It identifies a bounded set of CMake and header dependency hints and marks
HPC-sensitive libraries. Use the result to search modules and inspect the
project's real CMake options. It cannot resolve conditional or transitive
dependencies and does not test ABI compatibility.

For a supported small dependency, `hpc cxx fetchcontent` emits a pinned,
overridable snippet. It does not edit the project:

```console
hpc cxx fetchcontent fmt --project-option-prefix SIMULATION
```

Review the output before integrating it. FetchContent is a poor default for
MPI, CUDA, BLAS/LAPACK, HDF5, NetCDF, PETSc, and similar site-sensitive stacks.
Even small fetched dependencies require a source mirror or pre-populated cache
when cluster network access is restricted.

See [Software environments and dependencies](software-environments.md) for the
full decision process.

## Configure an out-of-source build

Use a separate build directory so generated files do not obscure source state:

```console
hpc --profile example --dry-run run \
    'module purge && module load GCC/14.2.0 CMake/3.31.3 && cmake -S "$VSC_DATA/projects/simulation" -B "$VSC_DATA/projects/simulation/build-gcc14-release" -DCMAKE_BUILD_TYPE=Release'
```

After inspecting the preview, run it without `--dry-run`. A dedicated build
directory makes it possible to keep Debug, Release, sanitizer, CPU-specific,
and toolchain-specific configurations separate.

For single-configuration generators, choose `CMAKE_BUILD_TYPE` deliberately:

- `Debug` supports diagnosis but can be much slower;
- `Release` enables optimization but may remove useful diagnostics;
- `RelWithDebInfo` is often a practical performance-investigation build.

Do not inject site-specific optimization flags blindly. Start with the
project's supported configuration, compiler warnings, and portable release
settings. Add architecture-specific flags only when the resulting binary's
deployment boundary is explicit and validated on the target node class.

Capture the configure output. A successful configure is where CMake records
which compiler, libraries, headers, and package configurations it actually
selected.

## Build without overloading the login node

For a small, policy-compliant build:

```console
hpc --profile example run \
    'module purge && module load GCC/14.2.0 CMake/3.31.3 && cmake --build "$VSC_DATA/projects/simulation/build-gcc14-release" --parallel 4'
```

Use a modest explicit parallelism value. `--parallel $(nproc)` on a shared
login node can consume far more CPU and memory than site policy allows. The
first build may also download or compile dependencies and be much more
expensive than an incremental rebuild.

Use a Slurm build job when the build is large, highly parallel, architecture-
specific, GPU-dependent, or likely to exceed login-node limits. A minimal build
job can load the same modules and run the same configure/build commands:

```bash
#!/bin/bash -l
#SBATCH --job-name=simulation-build
#SBATCH --account=project123
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=00:30:00
#SBATCH --output=%x-%j.out

set -euo pipefail

module purge
module load GCC/14.2.0 CMake/3.31.3
module list

source_dir="$VSC_DATA/projects/simulation"
build_dir="$source_dir/build-gcc14-release"

git -C "$source_dir" rev-parse HEAD
cmake --version
gcc --version
cmake -S "$source_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --parallel "$SLURM_CPUS_PER_TASK"
```

Quote, validate, and pilot this job through the normal
[Slurm workflow](slurm-jobs.md). Compilation is a real workload and may consume
allocation credits. Build into persistent storage unless the job also stages
the required artifacts back from node-local scratch before exit.

## Test at the right execution layer

A build is not verified merely because compilation succeeds. Use progressively
more realistic checks:

1. run focused unit tests allowed on the login node;
2. run serial or lightweight integration tests under the build module stack;
3. submit tests that require GPUs, MPI ranks, large memory, or meaningful CPU
   time to Slurm;
4. run one small scientific example and check its output, not just its exit
   status.

For a small CTest suite:

```console
hpc --profile example run \
    'module purge && module load GCC/14.2.0 CMake/3.31.3 && ctest --test-dir "$VSC_DATA/projects/simulation/build-gcc14-release" --output-on-failure'
```

Keep build and runtime modules aligned. Dynamically linked programs can compile
successfully and later fail because the required compiler runtime, MPI, CUDA,
or scientific library module was not loaded in the job script.

Do not treat a quick login-node run as a performance result. Node type,
contention, CPU frequency, affinity, and scheduler placement differ from a
controlled compute-node allocation.

## Preserve build provenance

For a build that will produce scientific results, retain:

- repository URL and exact commit or signed tag;
- whether the worktree was clean;
- module names and versions in load order;
- compiler, CMake, linker, MPI, and accelerator-toolkit versions;
- configure command, cache, presets, and toolchain file;
- build type and explicit compiler flags;
- dependency source and versions, including fetched commits;
- target cluster, partition, and CPU/GPU class;
- build and test logs;
- install prefix or executable location.

Prefer a short machine-readable preset or checked-in build script over a long
command that exists only in shell history. Do not commit generated build trees
or credentials.

## Diagnose common failures

| Failure | Likely layer | What to inspect |
| --- | --- | --- |
| Compiler lacks the requested language feature | Toolchain selection | Project standard, compiler version, loaded module. |
| CMake cannot find a package | Dependency discovery | `hpc cxx scan`, module catalogue, `CMAKE_PREFIX_PATH`, configure log. |
| Undefined references | Link interface or ABI mismatch | Link line, imported targets, compiler/MPI/library families. |
| Shared library missing at runtime | Runtime environment | Loaded modules, RPATH, `ldd`, job environment. |
| Build killed on login node | Site resource policy or memory pressure | Login limits; move a bounded build to Slurm. |
| FetchContent download fails | Network restriction or source drift | Mirrors, pinned source, pre-populated dependency directory. |
| Build works on one partition only | Architecture or accelerator dependency | Compiler flags, native packages, CUDA/ROCm stack, node class. |
| Tests pass locally but fail in Slurm | Execution-context difference | Working directory, modules, environment variables, filesystems, allocated resources. |
| Rebuild is unexpectedly slow | Build tree or filesystem behavior | Incremental state, metadata load, dependency rebuilds, build parallelism. |

Preserve the first complete failure log before changing the toolchain or
dependency set. Repeatedly adding modules or flags without understanding the
failure can produce an environment that builds once but cannot be recreated.

## Completion checklist

A remote build is ready for use when:

- the checkout location and storage lifecycle are appropriate;
- the exact source revision is known and local changes are accounted for;
- toolchain and dependency versions are explicit;
- configuration and compilation succeed under a policy-compliant workload;
- focused tests and one representative runtime test pass;
- compute-node-only features have been tested through Slurm;
- the runtime job loads the libraries used by the build;
- build and test provenance is retained;
- update and cleanup responsibilities are clear.

hpc-tools does not provide a generic uninstall or remote cleanup command.
Remove build trees or checkouts only through an explicit, separately reviewed
site operation after confirming the exact target and retention requirements.
