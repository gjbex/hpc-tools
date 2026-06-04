# KU Leuven Tier-2 Probe Hardware Report

This file consolidates hardware-probe output stored under
`examples/probe-results/`. It started as the wICE Probe Hardware Report and now
also records completed probes for Mindwell and Genius.

Source data:

- `examples/probe-results/wice/*`
- `examples/probe-results/mindwell/*`
- `examples/probe-results/genius/*`

Probe output describes sampled allocated nodes. It does not prove that every
node in a partition is identical, and it should be read alongside the hardware
and Slurm reference files.

## Probe Coverage

| Cluster | Probe partition | Host | Job ID | CPU model | CPUs | NUMA | Visible memory | Local scratch | GPU inventory |
|---|---|---|---:|---|---:|---:|---:|---:|---|
| `wice` | `batch` | `p33c30n3` | `60161002` | Intel Xeon Platinum 8360Y | 72 | 2 | 251 GiB | 600 GB | none found |
| `wice` | `batch_icelake` | `r33c27n1` | `60161003` | Intel Xeon Platinum 8360Y | 72 | 2 | 251 GiB | 600 GB | none found |
| `wice` | `batch_sapphirerapids` | `q16c05n3` | `60161400` | Intel Xeon Platinum 8468 | 96 | 8 | 251 GiB | 600 GB | none found |
| `wice` | `bigmem` | `k28l07` | `60161005` | Intel Xeon Platinum 8360Y | 72 | 4 | 2.0 TiB | 600 GB | none found |
| `wice` | `hugemem` | `s28l08` | `60161006` | Intel Xeon Platinum 8360Y | 72 | 2 | 7.9 TiB | 600 GB | none found |
| `wice` | `gpu_h100` | `s16g18` | `60161009` | AMD EPYC 9334 | 64 | 2 | 755 GiB | 600 GB | 4 x NVIDIA H100 80GB HBM3 |
| `mindwell` | `bigmem` | `p11c20l2` | `10027543` | Intel Xeon 6972P | 192 | 6 | 1.5 TiB | 600 GB | none found |
| `genius` | `gpu_p100` | `r22g38` | `59208385` | Intel Xeon Gold 6140 | 36 | 2 | 187 GiB | 200 GB | 4 x Tesla P100-SXM2-16GB |

Outstanding submitted probes as of the last local update:

- Mindwell `batch_graniterapids`: job `10027542`, pending when last checked.
- Mindwell `gpu_b200`: job `10027552`, pending when last checked.
- Genius `gpu_v100`: job `59208386`, pending when last checked.

## wICE CPU Nodes

### Ice Lake Thin CPU: `batch` and `batch_icelake`

Observed partitions `batch` and `batch_icelake` are effectively the same
hardware class in the sampled probe output:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core; SMT is disabled.
- NUMA: 2 NUMA domains, 36 CPUs per NUMA domain.
- Memory: about 251 GiB visible to Linux; NUMA domains report about 128.6 GB
  and 129.0 GB each.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`; the job
  scratch variable pointed at `/tmp`.
- Block device: Intel 960 GB SSD class device backing the local scratch volume.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 176 GB/s local NUMA
bandwidth and about 55.7 GB/s remote NUMA bandwidth for both sampled nodes.

Use these partitions for normal CPU jobs that fit within the standard memory
envelope. Prefer NUMA-aware placement or first-touch initialization for memory
bandwidth-sensitive jobs.

### Sapphire Rapids Thin CPU: `batch_sapphirerapids`

Observed node `q16c05n3` differs substantially from the Ice Lake thin nodes:

- CPU: `2 x Intel Xeon Platinum 8468`, 48 cores per socket.
- Logical CPUs: 96, one thread per core; SMT is disabled.
- NUMA: 8 NUMA domains, 12 CPUs per NUMA domain.
- Memory: about 251 GiB visible to Linux; each NUMA domain reports about
  31.9-32.3 GB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`, backed by a
  Samsung 960 GB NVMe class device.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 60-62 GB/s within
near NUMA domains and about 56 GB/s to farther domains. The 8-domain layout
means thread and memory placement matter for shared-memory jobs.

### Big Memory: `bigmem`

Observed `bigmem` node `k28l07` has the same CPU model and core count as the
Ice Lake thin CPU nodes, but a different memory topology:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core.
- NUMA: 4 NUMA domains, 18 CPUs per NUMA domain.
- Memory: about 2.0 TiB visible to Linux; each NUMA domain reports about
  516 GB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 164 GB/s within
nearby NUMA domains and about 55.8 GB/s to more distant NUMA domains. Use
`bigmem` when memory capacity, not extra CPU throughput, is the reason for the
allocation.

### Huge Memory: `hugemem`

Observed `hugemem` node `s28l08` is a very large memory node with the same CPU
model and core count as the Ice Lake thin nodes:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core.
- NUMA: 2 NUMA domains, 36 CPUs per NUMA domain.
- Memory: about 7.9 TiB visible to Linux; each NUMA domain reports about
  4.13 TB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`.
- Block devices: Intel 960 GB SSD class device and Samsung 960 GB NVMe class
  device were visible.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 149 GB/s local NUMA
bandwidth and about 55.7 GB/s remote NUMA bandwidth. The local bandwidth is
lower than the thin CPU sample, so do not assume the huge-memory node is a
faster CPU node. Use it for capacity-bound workloads.

## wICE GPU Nodes

### H100 GPU: `gpu_h100`

Observed node `s16g18`:

- CPU: `2 x AMD EPYC 9334`, 32 cores per socket.
- Logical CPUs: 64, one thread per core.
- NUMA: 2 NUMA domains, 32 CPUs per NUMA domain.
- Memory: about 755 GiB visible to Linux.
- GPUs: 4 x `NVIDIA H100 80GB HBM3`; MIG was reported as disabled.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`, backed by a
  Samsung 960 GB NVMe class device.

Intel MLC was present but did not produce bandwidth or latency matrices on this
node; the captured output only reported hugepage requirements. Do not compare
this H100 node against Intel CPU nodes using MLC data from this probe.

## Mindwell Nodes

### Big Memory: `bigmem`

Observed node `p11c20l2`:

- CPU: `2 x Intel Xeon 6972P`, 96 cores per socket.
- Logical CPUs: 192, one thread per core; SMT is disabled.
- NUMA: 6 NUMA domains, 32 CPUs per NUMA domain.
- Memory: about 1.5 TiB visible to Linux; each NUMA domain reports about
  258 GB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`, backed by a
  3.5 TB Samsung NVMe device.
- GPU tools: `nvidia-smi` was not found.

Measured Intel MLC read-only bandwidth matrix showed about 190-195 GB/s within
near NUMA domains and about 79-95 GB/s to farther domains. MLC peak injection
read bandwidth was about 1.17 TB/s. The 6-domain NUMA layout is performance
relevant for bandwidth-sensitive jobs.

This probe does not cover the standard Mindwell `batch_graniterapids` or
`gpu_b200` partitions yet; those jobs were still pending when this report was
updated.

## Genius GPU Nodes

### P100 GPU: `gpu_p100`

Observed node `r22g38`:

- CPU: `2 x Intel Xeon Gold 6140`, 18 cores per socket.
- Logical CPUs: 36, one thread per core; SMT is disabled.
- NUMA: 2 NUMA domains, 18 CPUs per NUMA domain.
- Memory: about 187 GiB visible to Linux.
- GPUs: 4 x `Tesla P100-SXM2-16GB`.
- Local scratch: 200 GB logical volume mounted at `/local_scratch`; the job
  scratch variable pointed at `/tmp`.

Measured Intel MLC read-only bandwidth matrix showed about 114 GB/s local NUMA
bandwidth and about 51 GB/s remote NUMA bandwidth. The P100 nodes are much
older than the wICE H100 and Mindwell classes; treat them as legacy GPU
capacity.

The Genius `gpu_v100` probe was still pending when this report was updated.

## Cross-Cluster Observations

- All sampled CPU-only Intel nodes had SMT disabled.
- Local scratch was exposed through `/local_scratch`; `summary.env` reported
  `scratch_node=/tmp` in these jobs, so scripts should use the site-provided
  variable rather than assuming a single path.
- wICE Ice Lake thin, big-memory, and huge-memory nodes share the same CPU
  generation but not the same NUMA and memory topology.
- wICE Sapphire Rapids thin nodes provide more cores but expose an 8-domain
  NUMA topology with much smaller memory per domain.
- Mindwell big-memory nodes have a substantially higher aggregate MLC bandwidth
  than the probed wICE Intel nodes, but also a more complex 6-domain topology.
- GPU inventory is only meaningful when `nvidia-smi.txt` successfully captured
  devices. CPU-only partitions record absence of `nvidia-smi`, not absence of
  all possible accelerators on the whole cluster.
- The probe ran Intel MLC without permission to modify prefetchers on Intel
  nodes, so treat bandwidth and latency values as comparative signals rather
  than definitive benchmark results.

## Refresh Procedure

Use the hardware probe script from a remote working directory:

```bash
hpc --profile <profile> install-hardware-probe --directory <remote-dir>
hpc --profile <profile> submit --test-only hardware-probe.slurm --directory <remote-dir>
hpc --profile <profile> submit hardware-probe.slurm --directory <remote-dir>
```

For long-queued probes, add `--mail-notifications` when the profile has an
`email` field and the user wants `END,FAIL` notifications.

For each result directory named `hardware-probe-<host>-<jobid>` or
`hardware-probe-<partition>-<host>-<jobid>`, inspect:

- `summary.env` for host, partition, cluster, job ID, CPU allocation, and
  scratch variable.
- `lscpu.txt` for CPU model, core/socket/thread counts, cache sizes, and flags.
- `numactl-hardware.txt` for NUMA domains, CPU placement, and domain memory.
- `memory.txt` and `meminfo.txt` for Linux-visible memory.
- `lsblk.txt`, `df.txt`, and `mounts.txt` for local scratch and filesystem
  layout.
- `intel-mlc-bandwidth.txt` and `intel-mlc-latency.txt` for comparative memory
  behavior when MLC produces matrices.
- `nvidia-smi.txt` and `rocm-smi.txt` for GPU inventory or absence.

When updating this report, keep measured observations separate from site
documentation and Slurm policy.
