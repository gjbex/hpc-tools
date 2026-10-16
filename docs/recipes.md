# End-to-end recipes

These recipes connect the task-focused chapters into common user journeys.
They intentionally do not repeat every option or site-specific decision. Follow
the linked chapter when a step needs explanation, and replace every example
profile, cluster, account, module, and path with verified values.

Each recipe uses the same control points:

1. identify the profile, cluster, directory, and authorized account;
2. inspect live site context and durable references;
3. preview remote changes;
4. validate a small representative operation;
5. scale only from evidence;
6. retain output and lifecycle provenance.

## Use an existing Slurm account with a profile

A profile does not contain or grant a Slurm account. It describes how to reach
the site and which helpers and references are available. Account choice remains
explicit for each quote or submission.

1. Create a minimal profile in `~/.config/hpc-tools/config.toml`:

    ```toml
    default_profile = "example"

    [profiles.example]
    ssh_target = "example-login"
    default_cluster = "example-cluster"

    [profiles.example.capabilities]
    version = 1
    max_level = "job-lifecycle"
    scopes = [
        "accounting.read",
        "job.validate",
        "remote-filesystem.list",
        "remote-filesystem.read",
        "remote-workspace.write",
    ]

    [profiles.example.capabilities.remote_roots]
    list = ["$VSC_DATA/projects"]
    read = ["$VSC_DATA/projects"]
    write = ["$VSC_DATA/projects"]
    ```

2. Verify access and current associations:

    ```console
    hpc --profile example --dry-run doctor
    hpc --profile example doctor
    hpc --profile example slurm-limits --cluster example-cluster
    ```

3. Determine which account is authorized for this project from site records or
   the allocation owner. Do not infer authorization from an account name or
   non-zero balance.

4. Supply the account explicitly when quoting and submitting:

    ```console
    hpc --profile example quote sbatch \
        --account=project123 \
        --cluster=example-cluster \
        pilot.sbatch

    hpc --profile example submit \
        --directory '$PROJECT/simulation' \
        --account project123 \
        --cluster example-cluster \
        --test-only \
        pilot.sbatch
    ```

5. Run a real pilot only after reviewing the quote and validation. See
   [Configuring cluster profiles](configuration.md) and [Running Slurm
   jobs](slurm-jobs.md).

## Onboard a poorly documented cluster

1. Establish direct SSH access independently of hpc-tools.
2. Create only the minimal profile and run `doctor`.
3. Inspect the login environment, Slurm controller, partitions, associations,
   QoS, storage, quotas, and module catalogue.
4. Record unknowns rather than copying policy from another site.
5. Run packaged probes only as small Slurm jobs on representative node classes.
6. Keep raw probe output in project storage and consolidate sourced summaries
   under the profile reference directory.
7. Review completion criteria before calling the profile usable.

Start with [Onboarding a new cluster](onboarding.md). Use [Probes and cluster
discovery](probes.md) only after scheduler policy and probe resources are
understood.

An undocumented fact is not permission to guess. Ask site support about account
policy, allowed partitions, quotas, container builds, network access, and data
retention when those choices affect cost, security, or data loss.

## Deploy, build, and test a CMake project

1. Inspect the destination filesystem and quota:

    ```console
    hpc --profile example storage inspect '$VSC_DATA/projects'
    hpc --profile example quota
    ```

2. Preview and clone the repository:

    ```console
    hpc --profile example --dry-run clone \
        https://github.com/example/simulation.git \
        --directory '$VSC_DATA/projects' \
        --name simulation

    hpc --profile example clone \
        https://github.com/example/simulation.git \
        --directory '$VSC_DATA/projects' \
        --name simulation
    ```

3. Inspect the remote worktree and exact revision before updating it:

    ```console
    hpc --profile example repo status \
        --directory '$VSC_DATA/projects/simulation'
    ```

4. Find compatible compiler, CMake, MPI, CUDA, and library modules. Configure
   an out-of-source build with an explicit build type.
5. Compile conservatively on the login node only when site policy permits;
   submit a build job for expensive or parallel builds.
6. Run unit tests at the build layer and a representative application test in
   a compute allocation.
7. Retain the commit, dirty state, modules, compiler, CMake options, dependency
   revisions, build log, and test result.

The complete workflow and cautious `hpc run` examples are in [Deploying and
building software remotely](remote-builds.md). `hpc run` is arbitrary remote
execution: review it more carefully than a bounded inspection command.

## Prepare missing Python packages

1. Scan local source and declared dependencies:

    ```console
    hpc python scan analysis.py
    hpc python inspect-deps .
    ```

2. Search site Python and bundle modules.
3. Check imports under the intended remote module stack:

    ```console
    hpc --profile example python check analysis.py \
        --module Python/3.13.1 \
        --module SciPy-bundle/2025.02
    ```

4. Plan a small project virtual environment only for imports still missing.
   Review the generated install script, native dependencies, target
   architecture, storage, and network requirements.
5. Preview and submit the installation job, then parse its output with the
   verification command.
6. Run an application-level import and smoke test under the same modules and
   node class as production.

See [Software environments and dependencies](software-environments.md) for
`plan-install`, `submit-install`, and `verify-install` examples. An import scan
is a dependency hint, not a complete or pinned environment specification.

## Prepare missing R packages

1. Scan the script or project:

    ```console
    hpc r scan analysis.R
    ```

2. Search the site R and bundle modules before installing anything.
3. Run `hpc r check` with the intended R, bundle, and external dependency
   modules.
4. Separate missing CRAN or Bioconductor packages from system libraries,
   compilers, geospatial libraries, MPI, CUDA, and other native dependencies.
5. Generate and review an architecture-aware install job.
6. Submit a pilot installation and verify `.libPaths()`, package namespaces,
   external modules, and `sessionInfo()` from its output.

Follow the R workflow in [Software environments and
dependencies](software-environments.md). Do not try to solve a missing native
library by repeatedly reinstalling the R package into a larger user library.

## Run and track a GPU job

1. Inspect current GPU partitions, limits, and representative hardware:

    ```console
    hpc --profile example slurm-limits \
        --cluster example-cluster \
        --partition gpu
    hpc --profile example hardware
    ```

2. Write a small batch script with explicit account, partition, GPU count,
   CPUs, memory, time, logs, module or container, and output path.
3. Quote the exact GPU shape, then run `submit --test-only`.
4. Submit a short real pilot. Verify device visibility, application correctness,
   peak device/host memory, CPU/GPU balance, and output.
5. Scale only the dimension supported by the pilot. Re-quote and revalidate
   after any resource or array change.
6. Observe the job and complete the local lifecycle:

    ```console
    hpc --profile example jobs --cluster example-cluster
    hpc --profile example sacct 123456 --cluster example-cluster
    hpc --profile example submissions observe <run-id>
    hpc --profile example submissions mark-collected <run-id> --path <results-path>
    hpc --profile example submissions mark-analysed <run-id> --path <report-path>
    hpc --profile example submissions close <run-id> --reason done
    ```

See [Running Slurm jobs](slurm-jobs.md). Scheduler acceptance and GPU
visibility do not prove that the application uses the GPU efficiently.

## Execute a resumable parameter sweep

1. Create an immutable manifest with stable task IDs, inputs, outputs, and
   parameters.
2. Make one array index select exactly one row or one deterministic chunk.
3. Use `%A` and `%a` in logs and distinct output paths for every task.
4. Validate and run two representative indices with concurrency one.
5. Check correctness, runtime, memory, retry semantics, and shared I/O.
6. Quote and submit the full array with an evidence-based concurrency cap:

    ```console
    hpc --profile example submit \
        --directory '$VSC_DATA/projects/simulation' \
        --array '0-999%20' \
        sweep.sbatch
    ```

7. Record per-task application status separately from the parent campaign
   record. Retry explicit failed IDs only after fixing shared defects.
8. Aggregate into a new artifact and verify completeness against the original
   manifest.

See [Job arrays and parameter sweeps](job-arrays.md). The hpc-tools submission
log tracks the campaign, not an independent lifecycle for every element.

## Benchmark across thread counts

1. Write the performance question and fixed workload before running jobs.
2. Select one node class, optimized build, correctness condition, timer
   boundary, warm-up policy, repetitions, and placement policy.
3. Align `--cpus-per-task`, active threads, and binding.
4. Pilot the single-thread baseline and one candidate configuration.
5. Run the reviewed sweep, keeping one measurement row per repetition and
   enough metadata to establish comparability.
6. Collect compact CSV, JSON, or JSONL artifacts locally:

    ```console
    hpc benchmark summarize benchmarks/baseline.csv
    hpc benchmark compare \
        benchmarks/baseline.csv \
        benchmarks/candidate-8.csv \
        --candidate-threads 8
    ```

7. Interpret variability and correctness before reporting speedup or
   efficiency. Retain excluded values and failed attempts.

See [Benchmarking on Slurm](benchmarking.md). The benchmark extension analyses
local results; it neither launches jobs nor establishes comparability.

## Build an Apptainer image through Slurm

1. Confirm that a container is justified and review site policy for Apptainer,
   fakeroot, network access, cache, temporary storage, and final image storage.
2. Write or install a starter bundle:

    ```console
    hpc write-container --kind generic container-build

    hpc --profile example --dry-run install-container \
        --kind generic \
        --directory '$VSC_DATA/projects/simulation/container-build'
    ```

3. Review and version the definition, labels, dependency inputs, base image,
   and build wrapper.
4. Quote, validate, and submit the wrapper as a small build job.
5. Record build logs and the SIF checksum.
6. Test the image in a representative allocation with explicit binds and the
   intended CPU, GPU, or MPI integration.
7. Build updates under new versioned names; retain the known-good image until
   replacement passes.

See [Container workflows](containers.md). The hpc-tools helper installs build
files; it does not build the image or submit the build job.

## Share a cluster reference set

1. Review the profile's hardware, Slurm, and storage Markdown for provenance,
   dates, scope, and personal information.
2. If another reference set is attached, confirm which context will be
   snapshot.
3. Create, show, validate, and read the new versioned set:

    ```console
    hpc --profile example references create example-cluster-2026-08
    hpc references show example-cluster-2026-08
    hpc references validate example-cluster-2026-08
    ```

4. Export it, inspect the archive, and communicate an independent checksum
   when integrity matters.
5. The recipient imports, reads, compares with current site sources, and only
   then attaches it.

See [Cluster references and sharing](reference-sets.md). Structural validation
does not establish freshness, correctness, authorship, or trust.

## Resume unfinished work after a restart

1. List active local records:

    ```console
    hpc --profile example submissions list
    ```

2. Work from `PROFILE`, `CLUSTER`, `JOBID`, `STATE`, and `ACTION`.
3. For `observe`, query with the record's profile. For `collect`, inspect and
   retain results before recording their path. For `analyse`, produce and
   review the analysis artifact. For `triage`, preserve logs before rerunning
   or closing.
4. Use `list --all` for audit history.

The submission database is local to the configuration tree and is not synchronized between
machines. It is an index, not a result backup or scheduler database. See
[Tracking work from submission to analysis](submissions.md).
