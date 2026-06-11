# HPC Benchmark Methodology

Use this reference for conceptual benchmark design, timing choices, scaling
interpretation, and result hygiene. Action skills still own remote deployment,
Slurm submission, accounting, monitoring, and artifact transfer.

## Benchmark Contract

Before timing, define and record:

- executable, source revision, build type, compiler, and module versions;
- exact command line and problem size;
- measured quantity, such as program-reported kernel time or end-to-end wall
  time;
- warmup count and measured run count;
- intended active thread count and any scheduler allocation used only to satisfy
  memory, GPU, or placement policy;
- affinity settings such as `OMP_NUM_THREADS`, `OMP_PROC_BIND`, `OMP_PLACES`,
  and runtime schedule variables;
- local and remote host or node names;
- account, cluster, partition, reservation, QoS, memory, walltime, and CPU/GPU
  request when submitting remotely.

Do not compare runs with different problem sizes unless the user explicitly
asks for weak scaling or throughput.

## Scaling Metrics

When computing speedup or parallel efficiency, collect a same-system baseline
at one active thread:

```text
speedup(p) = T1 / Tp
efficiency(p) = speedup(p) / p
```

Keep active threads separate from allocated CPUs. If a site requires a larger
CPU allocation to receive enough memory, allocate what the scheduler requires
but set and record `OMP_NUM_THREADS=1` for the one-thread baseline.

Separate absolute runtime comparison from scaling efficiency:

- absolute runtime says which system was faster for a fixed command;
- speedup and efficiency say how well each system used additional active
  threads or ranks;
- weak scaling or throughput needs a different interpretation and should be
  labelled explicitly.

## Timing Hygiene

Build optimized executables before timing. Prefer the repository's existing
build workflow and avoid adding a new harness unless repeated manual commands
are becoming error-prone.

Choose a problem size whose measured runtime is long enough to be meaningful
for the user's request. If the program reports an internal kernel time, verify
that this internal time, not just outer wall-clock time, satisfies the runtime
target.

For OpenMP or threaded programs, record at least:

```bash
OMP_NUM_THREADS=<threads>
OMP_PROC_BIND=<close-or-spread>
OMP_PLACES=cores
```

## Result Hygiene

Store benchmark outputs as compact CSV or JSON artifacts under a named results
directory. Include metadata with host, date, command, environment variables,
compiler/module versions, build information, and source revision.

Transfer compact artifacts locally for analysis when possible. Iterative
analysis through many small remote shell commands is usually slower and less
reproducible than local analysis of collected CSV, JSON, and logs.
