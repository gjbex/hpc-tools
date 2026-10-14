---
name: hpc-slurm-benchmark
description: Benchmark command-line scientific and HPC executables on configured Slurm systems through hpc-tools. Use when the user wants local-versus-remote performance comparisons, Slurm benchmark jobs, OpenMP or threaded scaling, speedup, parallel efficiency, parameter sweeps, pilot-first benchmark submissions, result collection, or local postprocessing of benchmark CSV/JSON artifacts.
---

# HPC Slurm Benchmark

## Remote Access

Use the installed `hpc` CLI for remote commands:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

Read the shared conceptual references that match the benchmark decision before
giving advice or submitting work:

- [`../_shared/hpc-benchmark-methodology.md`](../_shared/hpc-benchmark-methodology.md)
  for timing hygiene, speedup, parallel efficiency, metadata, and result
  interpretation;
- [`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
  for charge accounts, quote-before-submit, stale quotes, and pilot-first cost
  handling;
- [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for local
  scratch, shared filesystem pressure, and local artifact analysis;
- [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
  partition, QoS, and job-script semantics.

## Scope

Use this skill for end-to-end command-line benchmarking on a Slurm-backed HPC
profile, especially when local results need to be compared with remote jobs or
when a threaded executable needs scaling, speedup, or efficiency estimates.

Use the shared benchmark methodology reference, or the general scientific CLI
benchmark workflow when it is available, for timing-method choices, warmups,
repeat counts, affinity variables, and interpretation. This skill adds the
hpc-tools/Slurm operational contract: profile discovery, charge-account
selection, quoting, job validation, pilot-first submission, monitoring, artifact
collection, and local analysis. For the local analysis step, prefer the bundled
`hpc benchmark summarize` and `hpc benchmark compare` plugin commands when they
fit the artifact format.

## Benchmark Contract

Before submitting jobs, define and record the benchmark contract from
[`../_shared/hpc-benchmark-methodology.md`](../_shared/hpc-benchmark-methodology.md),
including executable, revision, build, command, problem size, measured quantity,
repeat count, active thread count, affinity settings, host/node, and Slurm
resource request. Do not compare runs with different problem sizes unless the
user explicitly asks for weak scaling or throughput. When computing speedup or
parallel efficiency, collect a same-system baseline at one active thread:

If submission, queue state, storage access, or job starts look abnormal, check
the profile `status_url` from `hpc --profile <profile> hardware --source`
before treating the run as a benchmark result or retuning resource requests.

```text
speedup(p) = T1 / Tp
efficiency(p) = speedup(p) / p
```

If a site requires a larger CPU allocation to receive enough memory, keep active
threads separate from allocated CPUs. For example, allocate enough CPUs or memory
for the job, but set and record `OMP_NUM_THREADS=1` when collecting a one-thread
baseline.

## Local Baseline

Build an optimized executable locally before timing, following
[`../_shared/hpc-benchmark-methodology.md`](../_shared/hpc-benchmark-methodology.md).
Prefer the repository's existing build workflow and do not add a new benchmark
harness unless repeated manual commands are becoming error-prone.

For OpenMP or threaded programs, run at least:

```bash
OMP_NUM_THREADS=<threads> \
OMP_PROC_BIND=<close-or-spread> \
OMP_PLACES=cores \
<other-runtime-env> \
<command>
```

Store local benchmark outputs as compact CSV or JSON artifacts under a named
results directory, with enough metadata for local and remote comparison.

## Remote Preparation

Check profile and site context before writing or submitting benchmark jobs:

```bash
hpc --profile <profile> --help
hpc --profile <profile> hardware
hpc --profile <profile> projects
```

Verify the remote checkout or deployment path before submitting. Do not assume
that the local current working directory maps to the remote job directory:

```bash
hpc --profile <profile> repo status --directory <remote-dir>
```

If the software is not deployed yet, use the deploy/build workflow first. Build
inside the job when compute-node modules, CPU generation, or filesystem placement
matter. For compiled code, use pinned site module versions when available rather
than system-image compilers.

Use [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for scratch
and artifact-placement decisions. Avoid iterative analysis through many small
remote commands; transfer compact artifacts locally and summarize them in the
local workspace.

## Accounts, Quotes, and Validation

When the profile exposes accounting helpers, inspect accounts before submission:

```bash
hpc --profile <profile> balance
hpc --profile <profile> statement --account <account>
```

If multiple charge accounts are available, follow
[`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md) and
ask which account to use. Do not pick one only because it has credits or
appeared in an earlier job.

Before every real submission on a charge-accounting site, quote the exact job
shape and present the estimate to the user:

```bash
hpc --profile <profile> quote srun -M <cluster> -p <partition> \
    -A <account> -t <HH:MM:SS> -N <nodes> -n <tasks> \
    -c <cpus-per-task> <memory-or-gpu-options>
```

A quote becomes stale when any resource-shape input changes: problem size,
walltime, node count, task count, CPUs, memory, GPU request, partition, cluster,
reservation, QoS, job count, or array range. Re-quote and present the new maximum
cost before submitting.

Validate Slurm parsing before submission:

```bash
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir>
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir> \
    --cluster <cluster> --partition <partition> --reservation <reservation>
```

For real benchmark submissions, prefer the streamlined preflight path when the
job shape is final:

```bash
hpc --profile <profile> submit --validate-first <jobscript> --directory <remote-dir>
```

`--validate-first` runs `sbatch --test-only` with the same options, stops if the
validation fails, and submits only after validation succeeds. If validation fails
without enough detail, capture the remote `sbatch` output explicitly through
`hpc run`. Treat allocation failures as resource, partition, account, QoS,
reservation, memory, or availability problems to diagnose, not as benchmark
failures.

## Submission Strategy

For sweeps or repeated jobs, use pilot-first submission:

1. Submit one representative case or array element.
2. Wait for completion.
3. Inspect `sacct`, output, and result CSV.
4. Re-quote the remaining workload if the job shape or job count changes.
5. Submit the remaining cases only after the pilot proves path, modules,
   scheduler options, and runtime configuration.

Use `hpc submit` for real submissions so the local submission database can
be used to resume work:

```bash
hpc --profile <profile> submit <jobscript> --directory <remote-dir>
hpc --profile <profile> submissions list
hpc --profile <profile> submissions observe
```

Record the job ID, cluster, node, account, and output file name immediately after
submission.

## Monitoring and Collection

Monitor queue and accounting state with:

```bash
hpc --profile <profile> jobs --cluster <cluster>
hpc --profile <profile> sacct <jobid> --cluster <cluster>
hpc --profile <profile> job <jobid> --cluster <cluster>
```

For failures, inspect accounting and the Slurm output file before changing the
script. Useful checks include exit code, elapsed time, allocation CPUs, requested
memory, maximum RSS, node list, loaded modules, and the recorded runtime
environment.

After completion, transfer compact artifacts locally. Prefer CSV/JSON timing
files plus Slurm output logs. When using the hpc-tools submission database, update the
submission lifecycle after collection and analysis, or propose doing so when the
user may want to keep the active database focused:

```bash
hpc --profile <profile> submissions mark-collected <run-id> --path <results-path>
hpc --profile <profile> submissions mark-analysed <run-id> --path <analysis-path>
hpc --profile <profile> submissions close <run-id> --reason done
```

Close failed, invalid, or superseded benchmark attempts with a reason once their
status is understood, so that profile's `submissions list` reflects only work that still
needs action.

## Analysis

Aggregate results locally. For each system and configuration, report mean,
stdev, min, max, run count, and any dropped or failed runs. For scaling, report
speedup and parallel efficiency from same-system baselines. For local-versus-HPC
comparisons, separate absolute runtime comparison from scaling efficiency:

- absolute runtime answers which system ran the selected configuration faster;
- speedup and efficiency answer how well each system used additional active
  threads relative to its own one-thread baseline.

Call out caveats that affect interpretation, such as different remote nodes for
baseline and threaded runs, scheduler-imposed memory-to-CPU coupling, active
threads differing from allocated CPUs, thermal throttling locally, noisy short
runs, or first-run build costs excluded from timing.

## Common Failure Modes

- Remote job cannot find the benchmark script: verify `<remote-dir>` and submit
  from the actual directory containing the script.
- All array tasks fail the same way: a pilot was skipped or did not validate the
  real path/module/runtime setup.
- Timings are too short or noisy: increase problem size or repeat count before
  interpreting speedup.
- A one-thread remote baseline runs out of memory: request enough memory, and if
  the scheduler allocates extra CPUs for that memory, explicitly set the active
  thread count to one.
- A quote is invalidated by a later override: re-quote with the final override
  set before submitting.
- Slurm validation reports an unavailable node configuration: check live
  partition state, reservations, QoS/account association, memory limits, and
  whether a reservation or constraint is required.
- A CUDA device-property probe fails before producing `device-properties.txt`:
  inspect `cmake-version.txt`, `nvcc-version.txt`, `cmake-configure.txt`, and
  `cmake-build.txt`, then load explicit CMake/CUDA modules or rerun with a
  corrected submit environment before launching the remaining GPU classes.
