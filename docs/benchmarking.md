# Benchmarking on Slurm

A useful benchmark answers a defined performance question under controlled
conditions. A successful job with a wall-clock number is not enough: build,
workload, node type, placement, thread count, warm-up, repetitions, and the
measurement boundary all affect the result.

hpc-tools supports two distinct parts of the workflow:

- profile, discovery, quote, validation, submission, and accounting commands
  help run the campaign on Slurm;
- `hpc benchmark summarize` and `hpc benchmark compare` analyse collected CSV,
  JSON, or JSONL timing artifacts locally.

The benchmark extension does not submit jobs, design a scaling experiment, or
prove that measurements are comparable.

## Start with a performance question

Examples of answerable questions are:

- Does revision B reduce elapsed time for the same simulation and result?
- How does one fixed problem scale from 1 to 32 CPU threads?
- Which process/thread placement is fastest without changing the result?
- Is container startup material compared with application runtime?

Avoid an undefined goal such as "benchmark the program." It encourages
collecting numbers first and inventing an interpretation later.

## Define the benchmark contract

Record:

- application revision and dirty-worktree state;
- compiler, build type, optimization flags, linked libraries, and modules;
- exact command, inputs, configuration, problem size, and correctness check;
- cluster, partition, node and accelerator type;
- Slurm nodes, ranks, CPUs, memory, GPUs, and time limit;
- active threads or ranks and their placement;
- warm-ups, repetitions, and an outlier policy;
- measurement name, unit, start/end boundary, date, job IDs, and node names.

Use an optimized build for application performance. Include compilation only
when build time is the quantity under study. A faster run with a different
problem, tolerance, precision, or output policy is not a speedup.

## Choose a scaling experiment

For strong scaling, keep the problem fixed while increasing active resources.
With single-resource mean time `T1` and mean time `Tp` on `p` resources:

```text
speedup(p)    = T1 / Tp
efficiency(p) = speedup(p) / p
```

For weak scaling, increase the problem with resources so work per resource
remains approximately fixed. Report a clearly defined weak-scaling metric; do
not label `T1/Tp/p` as weak-scaling efficiency.

Efficiency is meaningful only when `p` is the active resource count relative
to a comparable baseline. Allocated but idle CPUs do not count as useful
threads. Cross-system ratios are not conventional parallel efficiency.

## Control placement and execution

Keep node class, software, workload, and measurement method fixed unless one is
the experimental variable. For a threaded CPU program, align allocation and
runtime:

```bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8

export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:?}
export OMP_PLACES=cores
export OMP_PROC_BIND=close

srun --cpu-bind=cores ./simulate --config benchmark.toml
```

Binding options are runtime- and site-dependent. Verify actual placement; do
not assume a plausible setting was honoured. For MPI or hybrid jobs, record
ranks per node, threads per rank, launcher settings, and mapping. For GPUs,
record model, count, CPU allocation, binding, driver/runtime context, and
whether transfers and initialization lie inside the timed region.

## Design repetitions and outputs

Use an unmeasured warm-up when caches, JIT compilation, device initialization,
imports, or metadata affect the first iteration. Run enough measured
repetitions to expose variability. Repeat very short work inside an allocation
so scheduler and startup overhead do not dominate.

Write one row per repetition. A minimal accepted CSV is:

```csv
variant,threads,run,seconds
baseline,1,1,82.41
baseline,1,2,81.97
baseline,1,3,82.16
```

Prefer an unambiguous measurement name such as `seconds`, `duration`,
`runtime`, or `elapsed`, and use one unit per comparison. The analyser cannot
detect seconds-versus-milliseconds errors or failed correctness checks.

Keep metadata beside measurements:

```text
benchmarks/2026-08-19/
├── contract.md
├── baseline.csv
├── candidate-8-threads.csv
├── environment.txt
├── job-123456.out
└── job-123457.out
```

Compact tables are easier to analyse than thousands of small files. Retain raw
logs for provenance, but do not make the parser infer values from human-oriented
Slurm output.

## Run a pilot before the sweep

Use [Probes and cluster discovery](probes.md) to select hardware and [Running
Slurm jobs](slurm-jobs.md) to prepare the script. Run one baseline and one
candidate configuration. Prove that the intended inputs and executable are
used, placement matches allocation, correctness checks pass, the timer has the
intended boundary and unit, and output rows are complete.

Only then quote and submit the sweep. Arrays can run independent configurations,
but cap concurrency to reduce node and filesystem variability. See [Job arrays
and parameter sweeps](job-arrays.md).

## Summarize local results

After collecting files locally:

```console
hpc benchmark summarize benchmarks/2026-08-19/baseline.csv
hpc benchmark summarize \
    benchmarks/2026-08-19/baseline.csv \
    benchmarks/2026-08-19/candidate-8-threads.csv
```

Output includes the selected measurement column, count, arithmetic mean,
minimum, maximum, sample standard deviation, and source count. One measurement
has a standard deviation of zero.

Supported inputs are CSV with a header, JSONL objects, JSON objects or lists,
and JSON objects containing a `runs`, `results`, `records`, or `samples` list.
Directories are searched recursively for `.csv`, `.json`, and `.jsonl` files.

For `summarize`, a directory produces one summary per supported file. It does
not group rows by variant or thread count within a file. Split configurations
into separate files or use a suitable analysis script.

Machine-readable output is available:

```console
hpc benchmark summarize benchmarks/2026-08-19/baseline.csv --json
```

Review the selected key and count. Non-numeric values in the measurement column
are ignored, so an unexpectedly small count indicates malformed or failed rows.

## Compare a baseline and candidate

```console
hpc benchmark compare \
    benchmarks/2026-08-19/baseline.csv \
    benchmarks/2026-08-19/candidate-8-threads.csv \
    --candidate-threads 8
```

The command computes baseline mean divided by candidate mean. With
`--candidate-threads`, it also divides that speedup by the supplied count to
report efficiency. If a target is a directory, `compare` combines records from
all supported files below it; keep unrelated experiments elsewhere.

The command trusts the thread count and does not check units, resources,
problem sizes, correctness, distributions, or whether the baseline used one
thread. Its result is arithmetic over selected rows, not an automatic
scientific conclusion.

## Interpret variability before speedup

Mean, range, and standard deviation are orientation statistics. Show individual
values or a distribution when small differences affect a decision. Investigate
warm-up effects, node variation, filesystem activity, frequency scaling, load
imbalance, affinity, failed checks, and changed timing boundaries.

Define an outlier rule before seeing which points favour the conclusion. Report
exclusions and retain original data. Do not choose the minimum as "the
performance" unless best-case latency was explicitly the metric.

## Retain and close the campaign

Keep the contract, source revision, build provenance, raw measurements,
summaries, failed attempts, and analysis code. Mark superseded attempts rather
than deleting them.

```console
hpc submissions mark-collected <run-id> --path 'benchmarks/2026-08-19'
hpc submissions mark-analysed <run-id> \
    --path 'benchmarks/2026-08-19/report.md'
hpc submissions close <run-id> \
    --reason 'scaling report reviewed; raw data retained'
```

These commands record paths; they do not copy or validate artifacts. A
benchmark is complete when its question can be answered from reviewable
evidence, including limitations—not when the fastest number has been found.

