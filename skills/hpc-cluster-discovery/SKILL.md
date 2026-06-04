---
name: hpc-cluster-discovery
description: Discover and summarize hardware, scheduler, storage, module, and node-class information for a configured remote HPC system through hpc-tools. Use when the user asks what hardware a cluster has, how partitions or node types differ, whether documentation matches observed nodes, how to run or interpret the hardware-probe Slurm script, or how to create concise cluster reference notes from live probes.
---

# HPC Cluster Discovery

## Remote Access

Use the installed `hpc` CLI for remote commands:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Discovery Order

Start with configured profile context when it exists:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
hpc --profile <profile> queue
```

Treat local references and live command output as complementary:

- Use references to identify expected clusters, partitions, node classes,
  filesystems, accounts, and policy constraints.
- Use live commands and probe output to confirm what a real allocation exposes.
- Call out mismatches explicitly instead of silently choosing one source.

For scheduler details that affect where probes run, use the Slurm skill. For
storage, quota, modules, or conda details, use the filesystem/environment skill.
For cloning or placing probe scripts on the remote system, use the deploy/build
skill.

## Partition and Accounting Limits

For scheduler limits, query Slurm live rather than relying only on hardware
references. Partition properties such as walltime, total nodes, default memory,
and partition QoS usually come from `scontrol show partition`:

```bash
hpc --profile <profile> run 'scontrol -M <cluster> show partition <partition>'
hpc --profile <profile> run 'sinfo -M <cluster> -p <partition> -o "%P|%a|%l|%D|%N"'
hpc --profile <profile> run 'sinfo -M <cluster> -p <partition> -N -o "%N|%c|%m|%G|%t" | sed -n "1,12p"'
```

Read these fields carefully:

- `MaxTime`: maximum walltime for a job in the partition.
- `DefaultTime`: walltime used when the job does not request one.
- `MaxNodes`: partition-level per-job node cap; `UNLIMITED` still means the
  request is practically bounded by `TotalNodes`, availability, account policy,
  and QoS.
- `TotalNodes` and `TotalCPUs`: current partition capacity known to Slurm.
- `DefMemPerCPU` and `MaxMemPerCPU`: memory defaults and limits when the site
  uses per-CPU memory accounting.
- `QoS` and `DenyQos`: QoS policy attached to, or excluded from, the partition.

Per-user or per-account submit limits are usually not stored on the partition.
Check QoS and associations:

```bash
hpc --profile <profile> run 'sacctmgr -n -P show qos <qos> format=Name,MaxJobsPU,MaxSubmitJobsPU,MaxTRESPU,GrpJobs,GrpSubmitJobs,GrpTRES,MaxWall'
hpc --profile <profile> run 'sacctmgr -n -P show assoc where cluster=<cluster> user=$USER format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES'
hpc --profile <profile> run 'sacctmgr -n -P show assoc where cluster=<cluster> user=$USER partition=<partition> format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES'
```

When reporting a submit limit, state whether it came from QoS
(`MaxSubmitJobsPU`), a user/account association (`MaxSubmitJobs`), or a group
limit (`GrpSubmitJobs`). If a field is empty, do not infer a limit from it.

## Job Array Limits

Array size is a controller configuration setting, not normally a partition
field. Query it from Slurm config:

```bash
hpc --profile <profile> run 'scontrol -M <cluster> show config | grep -Ei "MaxArraySize|MaxJobCount|MaxSubmitJobs|SchedulerParameters"'
```

Interpret `MaxArraySize` as the configured maximum number of array index values.
In Slurm, a value of `N` normally means valid array indexes are `0` through
`N-1`, so the largest simple zero-based array is `--array=0-<N-1>`. Also report
QoS or association submit limits separately, because sites can count array jobs
and array tasks differently for policy purposes.

## Hardware Probe

Use the packaged hardware probe when documentation is missing, ambiguous, stale,
or too coarse for performance-sensitive decisions. Install it into the remote
working directory:

```bash
hpc --profile <profile> install-hardware-probe --directory <remote-dir>
```

The probe collects CPU/cache topology, NUMA layout, memory, mounted
filesystems, block devices, GPU inventory when available, Intel MLC
bandwidth/latency when available, and relevant Slurm environment variables.

Before submitting the probe:

- Adapt site-required `#SBATCH` directives such as account, cluster, partition,
  QoS, reservation, or time limit.
- For meaningful memory-bandwidth results, request a full node with
  `#SBATCH --exclusive`; if the site enforces CPU cgroups, set
  `#SBATCH --cpus-per-task` to the full node core count.
- Increase the time limit if Intel MLC or other probes are slow.
- Do not assume a local script path is visible remotely; run the script from a
  remote working directory or from a remote clone of this repository.

Validate before submission when possible:

```bash
hpc --profile <profile> submit --test-only hardware-probe.slurm --directory <remote-dir>
hpc --profile <profile> submit hardware-probe.slurm --directory <remote-dir>
```

After submission, follow the job with `hpc sacct` and inspect the output
directory named like `hardware-probe-<host>-<jobid>`.

## Probe Result Interpretation

When saved probe output exists, inspect the output directory before proposing a
new probe. The probe writes a directory named like
`hardware-probe-<host>-<jobid>` in the submission directory unless
`HPC_PROBE_OUTPUT_DIR` is set. Useful files include:

- `summary.env`: generation time, hostname, job ID, cluster, partition, node
  list, CPUs granted, submit directory, and node-local scratch variable.
- `lscpu.txt` and `lscpu-cache.txt`: CPU model, socket/core/thread counts,
  instruction flags, cache sizes, and NUMA CPU ranges.
- `numactl-hardware.txt`: NUMA node memory, CPU placement, and distance matrix.
- `memory.txt` and `meminfo.txt`: total memory and kernel memory view.
- `df.txt`, `mounts.txt`, `lsblk.txt`, and `block-devices.txt`: filesystem
  types, mount points, visible block devices, and possible local scratch.
- `nvidia-smi.txt` and `rocm-smi.txt`: GPU inventory or absence of GPU tools.
- `intel-mlc-bandwidth.txt` and `intel-mlc-latency.txt`: local and remote NUMA
  memory bandwidth/latency when MLC ran successfully.
- `hwloc.txt` and `cache/`: detailed topology and shared-cache relationships.

Summarize results by node class or partition, not only by hostname. Include the
evidence source for each claim, especially when comparing CPU generation,
memory capacity, NUMA layout, local storage, GPUs, or measured memory bandwidth.

## Output Style

For cluster discovery reports, keep the result operational:

- State what is known, what was measured, and what remains uncertain.
- Separate login-node observations from compute-node observations.
- Distinguish scheduler allocation limits from physical hardware capacity.
- Avoid recommending hardcoded partitions or paths unless the selected profile
  reference or probe output supports them.
- When the user needs reusable context, propose updates to the profile hardware,
  Slurm, or storage reference files rather than embedding site facts in the
  generic skills.
