# Container workflows

Containers can make a large software stack easier to rebuild and reuse.
Apptainer is common on HPC systems because it runs without a Docker daemon and
integrates with scheduler allocations and host filesystems. Site policy and the
installed version remain authoritative.

hpc-tools packages starter bundles for building Apptainer SIF images. It can
write a bundle locally or install it remotely. It does not build the image,
install Apptainer, submit the build job, or decide whether an image is allowed.

## Decide whether a container is the right layer

Use a container when a reviewed large native stack must be reused, repeated
language-environment installation causes metadata load, or compatible site
modules cannot provide the dependencies. Prefer modules plus a small project
environment when they already provide the compiler, MPI, CUDA, mathematical
libraries, and runtime. That often integrates better and creates less storage.

A container does not contain the cluster. The host kernel, accelerator driver,
filesystems, scheduler, interconnect, and bind mounts still matter. A laptop
test does not validate the image for target compute nodes.

## Inspect the available bundles

| Kind | Generated files | Starting point |
| --- | --- | --- |
| `agent` | pinned Codex CLI definition, batch wrapper, MCP relay/config, Slurm launcher | Run unattended Codex behind the restricted MCP boundary. |
| `agent-boundary` | minimal definition and MCP relay | Test the container boundary without installing or authenticating an agent. |
| `generic` | `create_apptainer_container.slurm` | Build an existing definition file. |
| `conda` | build script, `environment.yml`, `labels.txt` | Build an image with a packed conda environment. |
| `r` | build script, `apt_packages.txt`, `install_packages.R`, `labels.txt` | Generate a recipe with HPCCM, then build an R image. |

These are editable examples, not maintained application environments. Replace
example packages, labels, base images, and versions. Review all downloads and
commands. `hpc paths` shows the packaged template locations.

## Write a bundle locally

No profile is needed:

```console
hpc write-container --kind generic container-build
hpc write-container --kind agent restricted-codex-build
hpc write-container --kind agent-boundary restricted-boundary-build
hpc write-container --kind conda conda-container-build
hpc write-container --kind r r-container-build
```

The command refuses to overwrite generated files unless `--force` is supplied.
Force can replace your edits. Keep reviewed recipes, environment files, package
lists, labels, and wrappers in version control; keep large SIF files and caches
out of Git.

## Install a bundle remotely

Preview and then perform the write:

```console
hpc --profile example --dry-run install-container \
    --kind generic \
    --directory '$VSC_DATA/projects/simulation/container-build'

hpc --profile example install-container \
    --kind generic \
    --directory '$VSC_DATA/projects/simulation/container-build'
```

This creates the directory and packaged files. It does not transfer your local
definition or customizations. A version-controlled project is usually the
clearest transfer path; see [Deploying and building software
remotely](remote-builds.md).

Remote installation also refuses to replace generated files unless `--force`
is used. Treat force as destructive for those files.

## Review build requirements

Verify:

- the site's Apptainer executable and supported build mode;
- whether unprivileged `--fakeroot` builds are enabled;
- network access to registries and package repositories;
- approved locations for the SIF, cache, and temporary build tree;
- space, inodes, memory, CPUs, and time;
- whether builds must run on a compute node or dedicated service;
- base-image, package, and licence policies.

The packaged scripts request one node, one task, four CPUs, 16 GiB, and one
hour. These are examples; quote and validate a shape based on a pilot.

When `VSC_SCRATCH_NODE` exists, the scripts put temporary files below it. When
`VSC_SCRATCH` exists, they put the cache there. Other sites use different
variables; review and adapt the scripts instead of assuming these paths exist.

## Build from an existing definition

The generic script accepts:

```text
--recipe <definition-file> [--labels <labels-file>] --sif <image.sif>
```

It appends optional labels to a temporary recipe and runs `apptainer build
--fakeroot`. It rejects an existing output image.

`hpc submit` submits a script path but does not pass arguments to it. Put the
reviewed invocation in a Slurm wrapper:

```bash
#!/bin/bash -l
#SBATCH --job-name=build-simulation-image
#SBATCH --account=project123
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=build-%j.out
#SBATCH --error=build-%j.err

set -euo pipefail

module purge
module load Apptainer/1.4.0

./create_apptainer_container.slurm \
    --recipe simulation.def \
    --labels labels.txt \
    --sif simulation-2026-08-19.sif
```

Validate and submit from the remote build directory:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation/container-build' \
    --test-only \
    build-container.sbatch

hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation/container-build' \
    build-container.sbatch
```

Scheduler validation cannot test registry access, fakeroot, package resolution,
or the recipe. A real pilot build is essential.

## Adapt the conda and R starters

The conda starter builds a packed environment from `environment.yml` in a
multi-stage image. Pin dependencies and base images. The example is not a lock
file; mutable channels plus unpinned packages can produce a different image.
Its script accepts `--env`, optional `--labels`, and `--sif`.

The R starter reads system packages from `apt_packages.txt`, installs packages
from `install_packages.R`, and uses HPCCM to generate a recipe. It creates a
temporary Python environment and downloads HPCCM, so Python, venv, `pip`, and
outbound access are required unless the script is adapted. It may also download
R and system packages. Run its `--help` and review the implementation before
writing a wrapper. Do not publish its example maintainer labels as your own.

When HPCCM is used, keep its inputs as the source of truth and regenerate the
definition before every build. Hand edits to generated output will otherwise
be lost or make the build irreproducible.

## Run and validate the image

Test inside a representative allocation with production modules, binds,
hardware, and devices:

```bash
module purge
module load Apptainer/1.4.0

apptainer inspect simulation-2026-08-19.sif
apptainer exec \
    --bind "$PWD/data:/work/data:ro" \
    --bind "$PWD/results:/work/results" \
    simulation-2026-08-19.sif \
    simulation --input /work/data/pilot.nc --output /work/results/pilot.json
```

Use explicit bind paths and modes. Never embed credentials, SSH keys, tokens,
or private configuration in an image layer.

GPU sites may require `--nv` or `--rocm`; these expose host driver components,
so userspace compatibility still matters. Test device visibility and a real
kernel. For MPI, follow site guidance: host/container MPI compatibility is
subtle and can affect correctness or interconnect performance.

## Manage storage and provenance

- Store recipes and dependency inputs in the project repository.
- Use scratch or node-local space for disposable build files.
- Store accepted images in durable project space with versioned names.
- Follow site advice about staging large images for many-job campaigns.
- Record a SIF checksum after a successful build.

For every retained image, capture generator inputs and revision, base-image
digest where available, dependency locks and checksums, tool and module
versions, build job ID and log, image checksum and labels, validation result,
required binds, accelerator flags, and runtime command.

## Update without losing the known-good image

Change canonical inputs, build a new versioned SIF, and repeat application-level
validation. Keep the known-good image until replacement succeeds. Overwriting a
production image can make queued and running jobs observe different content and
makes rollback ambiguous.

Treat imported recipes and images as untrusted. Review commands, sources,
digests, licences, and secrets handling. A successful build proves only that
instructions ran; it does not establish supply-chain trust, numerical
correctness, or performance.
