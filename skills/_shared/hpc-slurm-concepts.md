# HPC Slurm Concepts

Use this reference for scheduler concepts that should apply across Slurm-backed
clusters. Action skills still own the concrete `hpc` commands.

## Site Context Before Resource Choices

Before choosing partitions, memory, CPU counts, GPU directives, account
directives, cluster flags, or I/O paths for a job script, inspect available
hardware, Slurm, and storage references when the selected profile exposes them.

Use local references to map requested resources to node types and partitions.
Use live Slurm commands to confirm details that affect submission, because
partition capacity, QoS, and association policy can drift.

Do not hardcode site-specific partitions, accounts, filesystem paths, or module
names in generic skills.

## Partition, QoS, and Submit Limits

Partition properties such as walltime, total nodes, default memory, and
partition QoS usually come from `scontrol show partition` or a profile wrapper
around it.

Read these fields carefully:

- `MaxTime`: maximum walltime for a job in the partition.
- `DefaultTime`: walltime used when the job does not request one.
- `MaxNodes`: partition-level per-job node cap; `UNLIMITED` is still bounded by
  capacity, availability, account policy, and QoS.
- `TotalNodes` and `TotalCPUs`: current partition capacity known to Slurm.
- `DefMemPerCPU` and `MaxMemPerCPU`: memory defaults and limits when the site
  uses per-CPU memory accounting.
- `QoS` and `DenyQos`: QoS policy attached to, or excluded from, the partition.

Per-user or per-account submit limits usually come from QoS or associations,
not the partition itself. When reporting a submit limit, state whether it came
from QoS (`MaxSubmitJobsPU`), a user/account association (`MaxSubmitJobs`), or
a group limit (`GrpSubmitJobs`). If a field is empty, do not infer a limit from
it.

## Job Array Limits

Array size is normally a controller configuration setting. Interpret
`MaxArraySize=N` as the maximum number of array index values. In Slurm, a value
of `N` usually means valid array indexes are `0` through `N-1`, so the largest
simple zero-based array is `--array=0-<N-1>`.

Keep this separate from submit-job limits, because sites can count one array
job, all array elements, pending elements, or running elements differently for
policy purposes.

## Job Script Defaults

Prefer `#!/bin/bash -l` so the environment is initialized before module loads.
Use the module system for compilers, CMake, MPI, CUDA, and similar build/runtime
tools when the site provides them. Prefer explicit module versions over generic
module names so job scripts remain reproducible.

Validate Slurm parsing before submission with `sbatch --test-only` or the
profile's equivalent wrapper. A parse-only validation does not prove that module
loads or runtime commands will work on the allocated node.

## Long Runtime and Checkpointing

When expected runtime is longer than a partition's `MaxTime`, prefer native
application checkpoint/restart or workload decomposition into separate jobs. If
the application cannot checkpoint itself, DMTCP can be a useful transparent
checkpoint/restart wrapper when the site provides it as a module. Treat DMTCP as
workload-specific: verify module availability, run a short pilot on the target
partition, store checkpoints where they survive job termination, and confirm a
real restart before depending on it for production.

If neither native checkpointing, DMTCP, nor external decomposition works, the
remaining path is an admin-supported exception, reservation, dedicated resource,
or a system with a longer walltime policy.

## Probe Jobs

Submit one probe per representative node class or partition, not one per node.
For meaningful memory-bandwidth results, request a full node with
`#SBATCH --exclusive`; when the site enforces CPU cgroups, set
`#SBATCH --cpus-per-task` to the full node core count. Increase walltime when
Intel MLC or site tools need more time.
