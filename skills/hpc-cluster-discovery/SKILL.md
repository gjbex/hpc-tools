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

## Conceptual References

Use [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
partition, QoS, submit-limit, array-limit, job-script, and probe-job
interpretation. Use
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for filesystem,
local scratch, and raw-artifact handling. Use
[`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
before submitting chargeable probe jobs.

## Discovery Order

Start with configured profile context when it exists:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
hpc --profile <profile> queue
```

If live discovery fails or reports surprising scheduler/storage behavior, check
any `status_url` from the profile sources before drawing conclusions from the
failure. Status pages can explain maintenance reservations, storage
interruptions, login-node issues, or temporary Slurm controller problems.

Treat local references and live command output as complementary:

- Use references to identify expected clusters, partitions, node classes,
  filesystems, accounts, and policy constraints.
- Use live commands and probe output to confirm what a real allocation exposes.
- Call out mismatches explicitly instead of silently choosing one source.

For a quick cluster status overview, prefer `hpc status`. It returns the full
status page, quota, balance, and current submission database in one report before
you start drilling into a specific subsystem. Let the assistant summarize the
attention-worthy items when you need a triage view.

For scheduler details that affect where probes run, use the Slurm skill. For
storage, quota, modules, or conda details, use the filesystem/environment skill.
For cloning or placing probe scripts on the remote system, use the deploy/build
skill.

## Partition and Accounting Limits

For scheduler limits, query Slurm live rather than relying only on hardware
references. Partition properties such as walltime, total nodes, default memory,
and partition QoS usually come from `scontrol show partition`:

```bash
hpc --profile <profile> slurm-limits --cluster <cluster> --partition <partition>
```

Read partition fields using
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md), including
`MaxTime`, `DefaultTime`, `MaxNodes`, `TotalNodes`, `TotalCPUs`,
`DefMemPerCPU`, `MaxMemPerCPU`, `QoS`, and `DenyQos`.

Per-user or per-account submit limits are usually not stored on the partition.
Check QoS and associations:

```bash
hpc --profile <profile> slurm-limits --cluster <cluster>
hpc --profile <profile> slurm-limits --cluster <cluster> --partition <partition> --qos <qos>
```

When reporting a submit limit, state whether it came from QoS
(`MaxSubmitJobsPU`), a user/account association (`MaxSubmitJobs`), or a group
limit (`GrpSubmitJobs`). If a field is empty, do not infer a limit from it.

## Job Array Limits

Array size is a controller configuration setting, not normally a partition
field. Query it from Slurm config:

```bash
hpc --profile <profile> slurm-limits --cluster <cluster>
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
hpc --profile <profile> install-probe --kind hardware --directory <remote-dir>
```

The probe collects CPU/cache topology, NUMA layout, memory, mounted
filesystems, block devices, GPU inventory when available, Intel MLC
bandwidth/latency when available, and relevant Slurm environment variables.

Before submitting the probe:

- Adapt site-required `#SBATCH` directives such as account, cluster, partition,
  QoS, reservation, or time limit.
- If a probe may wait in the queue for a long time and the selected profile
  defines `email`, offer `--mail-notifications`; this adds only
  `#SBATCH --mail-type=END,FAIL`, not start notifications. If the user provides
  a different address, use `--mail-user <address>` instead.
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

## CUDA Device-Property Probe

For GPU partitions, complement the full hardware probe with a small CUDA
device-property probe when cache sizes, shared-memory limits, register limits,
compute capability, launch dimensions, or runtime-visible memory bandwidth
matter. `nvidia-smi` is useful for inventory, driver version, MIG state, and
allocated devices, but it does not expose all CUDA programming limits.

Use the packaged or repository CUDA example from a remote working directory
that contains `cuda-device-properties.slurm`, `cuda/CMakeLists.txt`, and
`cuda/device_properties.cu`. Prefer installing the packaged bundle with:

```bash
hpc --profile <profile> install-probe --kind cuda-device-properties --directory <remote-dir>
```

`hpc paths` shows the packaged template and source locations after installation.
If the source exists only locally, stage those small files to a remote project
directory before submitting.

Quote the exact GPU job before submitting on charge-accounting systems, using
the same cluster, partition, account, reservation, walltime, and GPU count:

```bash
hpc --profile <profile> quote srun -M <cluster> -p <partition> \
    -A <account> --reservation=<reservation> -N 1 --ntasks=1 \
    --gpus-per-node=1 -t 00:10:00 true
```

Omit `--reservation` when the target partition does not require one. Validate
and submit through `hpc submit` so the local submission database can track the run:

```bash
hpc --profile <profile> submit --validate-first \
    cuda-device-properties.slurm \
    --directory <remote-dir> \
    --cluster <cluster> --partition <partition> --account <account> \
    --reservation <reservation> --gpus-per-node 1 --time 00:10:00 \
    --job-name cuda-props-<gpu-class>
```

Use a pilot-first workflow when probing several GPU classes: run one known
short job first, confirm it builds and writes `device-properties.txt`, then
submit the remaining classes. If the job fails because `cmake`, `nvcc`, or
CUDA runtime libraries are missing, inspect the captured `cmake-version.txt`,
`nvcc-version.txt`, and build logs, then load explicit site modules in the job
script or submit environment before rerunning.

The CUDA probe writes a directory named like
`cuda-device-properties-<host>-<jobid>` unless
`CUDA_DEVICE_PROPERTIES_OUTPUT_DIR` is set. Useful files include:

- `summary.env`: generation time, hostname, job ID, cluster, partition, node
  list, GPU allocation hints, submit directory, source directory, build
  directory, and node-local scratch variable.
- `cmake-version.txt`, `nvcc-version.txt`, `cmake-configure.txt`, and
  `cmake-build.txt`: build environment and diagnostics.
- `nvidia-smi.txt`: runtime GPU inventory and driver state when available.
- `device-properties.txt`: CUDA runtime and driver versions, visible CUDA
  device count, device name, compute capability, SM count, global memory, L2
  cache, persisting L2 limit, shared-memory limits, register limits, memory
  clock and bus width, theoretical bandwidth, maximum threads per block, block
  dimensions, grid dimensions, and resident thread/block limits per SM.

Treat these CUDA results as allocation-visible device properties. They usually
describe one allocated GPU, not every GPU in the node, and they complement the
full hardware probe's host CPU, NUMA, filesystem, and full-node GPU inventory.

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
- `cuda-device-properties-<host>-<jobid>/device-properties.txt`: CUDA
  programming limits for allocated GPUs, such as L2 cache, shared memory,
  registers, compute capability, and launch dimensions.

When downloading remote probe results for inspection, stage the raw result
directories in `${TMP_DIR}` when that variable is set, otherwise in `/tmp`.
Do not download or store raw probe directories under the profile `.config`
reference directory; raw probe output can be large. Only durable consolidated
reports, such as `probe-hardware-report.md`, should live under
`~/.config/hpc-tools/profiles/<profile>/`.

Summarize results by node class or partition, not only by hostname. Include the
evidence source for each claim, especially when comparing CPU generation,
memory capacity, NUMA layout, local storage, GPUs, CUDA cache/shared-memory
properties, or measured memory bandwidth. After CUDA device-property results
have been folded into the durable report, use `hpc submissions` to update the
local submission database. Do not edit `submissions.sqlite3` directly
unless the CLI is unavailable or broken:

```bash
hpc --profile <profile> submissions mark-collected <run-id> --path <remote-result-path>
hpc --profile <profile> submissions mark-analysed <run-id> --path ~/.config/hpc-tools/profiles/<profile>/probe-hardware-report.md
hpc --profile <profile> submissions close <run-id> --reason "<GPU class> CUDA device properties collected and consolidated into probe hardware report"
```

If an earlier probe submission failed but its logs were enough to identify the
problem and a corrected rerun later succeeded, close the failed run with a
superseded reason through `hpc --profile <profile> submissions close` so it does not remain as
active triage work.

If the resulting reference notes are meant to be reused across multiple users
of the same cluster, package them with `hpc references create <name>` and
`hpc references export <name>` instead of keeping them only under one user's
profile-local reference directory.

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
