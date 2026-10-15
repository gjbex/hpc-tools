---
name: hpc-slurm-job-arrays
description: Run and manage embarrassingly parallel Slurm job-array workflows on configured HPC systems through hpc-tools, especially when the user mentions atools, parameter exploration, many input files, array bookkeeping, rerunning failed tasks, aggregating per-task output, or resumable MapReduce-style batch work.
---

# HPC Slurm Job Arrays

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

Use [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
array limits, submit limits, and scheduler semantics. Use
[`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md) for
charge-account and quote-before-submit rules. Use
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for
shared-filesystem pressure, local scratch, and artifact handling.

## Scope

Use this skill when the workload is embarrassingly parallel: one executable or
analysis repeated over many parameter combinations or many independent input
files. Typical triggers are:

- Slurm job arrays;
- `atools`, `aenv`, `alog`, `arange`, `areduce`, `aload`, or `acreate`;
- parameter sweeps or Cartesian product experiments;
- many-input-file processing with one task per file;
- bookkeeping questions such as "which tasks failed?" or "how do I resume only
  the unfinished tasks?".

Use `hpc-slurm-jobs` for generic single jobs, validation, accounting, and
submission mechanics. Use this skill when the array orchestration itself is the
main problem.

## Array Contract

Before writing or submitting the array job, define:

- what one task does and whether tasks are independent;
- how tasks are enumerated: explicit CSV rows, generated parameter grid, or
  input-file manifest;
- which fields each task needs, for example input path, output path, seed, or
  algorithm parameters;
- the expected per-task runtime and I/O pattern;
- where centralized logs, task outputs, and aggregated results will live;
- whether failed tasks should be rerun exactly as-is or regenerated from a new
  manifest.

Prefer an explicit manifest file over shell-generated implicit numbering when
the task metadata matters later. A CSV manifest makes retries, provenance, and
aggregation easier.

## Array and Submit Limits

Before choosing the final array range or concurrency cap, check the profile's
Slurm reference for array and submit limits:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> slurm-limits --cluster <cluster>
hpc --profile <profile> slurm-limits --cluster <cluster> --partition <partition>
```

Look for controller-wide limits such as `MaxArraySize`, `MaxJobCount`, and
`MaxSubmitJobs`, plus QoS or association limits such as `MaxJobsPU`,
`MaxSubmitJobsPU`, `MaxJobs`, `MaxSubmitJobs`, `GrpJobs`, and
`GrpSubmitJobs`. If the reference is missing or stale, use `hpc slurm-limits`
to collect live limits before sizing the array. Interpret `MaxArraySize` and
submit-job limits using
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md); for a
zero-based array, the largest simple range is normally `--array=0-<N-1>`.
When the intended sweep is larger than the visible limits, split it into
batches, add a concurrency cap such as `%<limit>`, or ask the user which subset
to run first.

## Task Enumeration

For simple plain-Slurm arrays, map `SLURM_ARRAY_TASK_ID` to a manifest row or
file index.

When `atools` is available, prefer its higher-level workflow:

- use `aenv` to expose the CSV row for the current task as environment
  variables;
- use `alog` to record task start and end status in one central log;
- use `arange` to summarize progress and compute the retry range;
- use `areduce` to aggregate per-task outputs after completion;
- use `aload` to inspect task runtime distribution and load balance;
- use `acreate` to adapt an existing job script when users already have one.

`atools` was designed for this exact problem: job arrays with parameter or
input bookkeeping layered on top of the scheduler's task-ID mechanism.

## Manifest Design

Keep manifests simple and explicit. Good columns are:

- `task_id` or an implicit row number;
- `input_path`;
- `output_path`;
- parameter columns such as `alpha`, `beta`, `seed`, or `threshold`;
- optional grouping columns when multiple logical tasks will later be reduced.

Store the manifest and the job script together in the remote project directory
so retries can reuse the same inputs. Do not regenerate the manifest differently
between the pilot and the full run unless the user explicitly wants a different
experiment.

## Script Pattern

For a plain Slurm array without `atools`, use `SLURM_ARRAY_TASK_ID` to select
the current row and keep task outputs partitioned by task ID. For an
`atools`-based script, let `aenv` populate the task-specific variables and call
`alog` at task start and end.

For very short tasks, prefer a stepped array that assigns one chunk to each
Slurm array element, for example `--array=1-2000:25%20`. Inside the job, treat
the real `SLURM_ARRAY_TASK_ID` as the chunk start, derive the chunk size from
`SLURM_ARRAY_TASK_STEP` with a fallback, and loop over the contained manifest
rows. When using `aenv`, run each row in a subshell, temporarily export
`SLURM_ARRAY_TASK_ID=<row>`, then `source <(aenv --data params.csv)` so `aenv`
selects the row's parameter values:

```bash
chunk_start="${SLURM_ARRAY_TASK_ID}"
chunk_size="${SLURM_ARRAY_TASK_STEP:-25}"
chunk_end=$((chunk_start + chunk_size - 1))
if ((chunk_end > SLURM_ARRAY_TASK_MAX)); then
    chunk_end="${SLURM_ARRAY_TASK_MAX}"
fi

for row in $(seq "$chunk_start" "$chunk_end"); do
    (
        export SLURM_ARRAY_TASK_ID="$row"
        source <(aenv --data params.csv)

        alog start "row-${row}"
        ./run_one_instance \
            --alpha "$ALPHA" \
            --beta "$BETA" \
            --seed "$SEED" \
            --output "results/row-${row}.json"
        alog done "row-${row}"
    )
done
```

Use the subshell so row-specific `aenv` variables do not leak between
instances. Verify whether the site's `aenv` treats `SLURM_ARRAY_TASK_ID=1` as
the first data row after the CSV header or uses zero-based indexing before
submitting the full sweep.

The core requirements are:

- deterministic mapping from array index to task metadata;
- unique output path per task to avoid collisions;
- explicit exit-status propagation so failures are observable;
- lightweight per-task logging or metadata capture.

If the user already has a working job script, prefer adapting it rather than
rewriting from scratch.

## Runtime and I/O Hygiene

Array jobs amplify overhead and filesystem pressure. Use
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for storage and
local scratch decisions.

Keep these rules:

- do not launch arrays of tasks that each run only a few minutes if setup
  dominates runtime;
- as a rule of thumb from the `atools` docs, prefer tasks long enough to
  amortize scheduler and environment overhead, roughly 30 minutes or more;
- if tasks are shorter, bundle multiple manifest rows into one array element;
  for `atools`, a stepped array such as `--array=1-2000:25%20` plus the
  temporary `SLURM_ARRAY_TASK_ID` override pattern keeps one `params.csv` while
  still using `aenv` for each row;
- avoid many tiny random reads or writes on shared storage;
- use node-local scratch for temporary task files when the site exposes it, and
  stage compact results back;
- aggregate many small outputs into fewer durable files when possible;
- limit array concurrency when the filesystem or license server would be
  stressed, for example `--array=1-200%5`.

Use `hpc-filesystem-environment` when the bottleneck is storage layout or local
scratch policy rather than the array logic.

## Accounts, Quotes, and Validation

Array submissions can multiply cost quickly. Use
[`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md).
On charge-accounting sites:

- inspect accounts first with `hpc --profile <profile> balance` and
  `hpc --profile <profile> statement --account <account>`;
- ask which account to use if several are available;
- quote before submission with the real array shape included;
- re-quote if walltime, resources, array size, or concurrency limit changes.

For example:

```bash
hpc --profile <profile> quote srun -M <cluster> -p <partition> \
    -A <account> -t <HH:MM:SS> -N <nodes> -n <tasks> \
    -c <cpus-per-task> <memory-or-gpu-options>
```

Validate before submitting:

```bash
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir> --array 1-10
hpc --profile <profile> submit --validate-first <jobscript> --directory <remote-dir> --array 1-10
```

## Submission Strategy

Use pilot-first submission for arrays:

1. Submit one representative task or a very small array slice.
2. Wait for completion.
3. Inspect task output, centralized logs, and expected result files.
4. Re-quote the full workload if the final array size or resource shape changed.
5. Submit the remaining tasks only after the pilot proves the mapping, modules,
   output paths, and runtime assumptions.

For real submissions, use `hpc submit` so the local submission database
captures the run:

```bash
hpc --profile <profile> submit <jobscript> --directory <remote-dir> --array 1-250
hpc --profile <profile> submissions list
hpc --profile <profile> submissions observe
```

Record the manifest path, array range, concurrency cap, job ID, and output-log
naming convention immediately after submission.

## Monitoring and Resume

When not using `atools`, monitor the array with the normal Slurm tools:

```bash
hpc --profile <profile> jobs --cluster <cluster>
hpc --profile <profile> sacct <jobid> --cluster <cluster>
hpc --profile <profile> job <jobid> --cluster <cluster>
```

When using `atools`, prefer `arange` for bookkeeping:

- `arange --summary` to see progress and completion state;
- `arange --list_failed` or `--list_completed` to enumerate task ranges;
- plain `arange ...` to emit the unfinished range;
- `arange --redo` to include failed tasks after a bug fix or environment fix.

This is the key value of the workflow: rerun only the necessary task IDs rather
than the whole experiment.

## Result Collection

Keep per-task outputs machine-readable and easy to aggregate. Good patterns are:

- one output file per task under a dedicated results directory;
- one metadata sidecar per task only when needed for debugging;
- one later aggregation step that produces compact CSV, JSON, Parquet, HDF5, or
  similarly structured output.

When `atools` is used, prefer `areduce` for the aggregation step. Transfer the
compact aggregated artifact locally for analysis instead of repeatedly parsing
many remote files through the shell.

If the user wants timing or load-balance diagnostics across tasks, use `aload`
after completion and summarize skew, stragglers, and node imbalance.

## Failure Triage

When an array partially fails, first classify the failure:

- deterministic bad-input or task-specific failure;
- shared configuration bug affecting every task;
- filesystem or path collision;
- missing modules, environment activation, or executable path issues;
- scheduler resource mismatch such as insufficient memory or walltime.

If the root cause is shared, fix it before any broad retry. If the failure is
task-specific, rerun only the affected task IDs.

After collection and analysis, update the local submission lifecycle:

```bash
hpc --profile <profile> submissions mark-collected <run-id> --path <results-path>
hpc --profile <profile> submissions mark-analysed <run-id> --path <analysis-path>
hpc --profile <profile> submissions close <run-id> --reason done
```

Close invalid or superseded array attempts once their role in the workflow is
understood so that profile's `submissions list` stays focused on work that still needs
attention.
