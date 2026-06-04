# wICE Probe Hardware Report

Source data: `examples/probe-results/wice/*`, generated on 2026-06-03 from
allocated compute nodes with `examples/job-scripts/hardware-probe.slurm`.

This is a comparative report across the probed wICE CPU node classes. Keep it
as a single report while the number of probed classes is small; the side-by-side
view is more useful than separate files. Split into one report per hardware
type only if the notes grow into detailed tuning guidance, benchmark history,
or failure notes for each node class.

## Summary

| Probe partition | Host | CPU model | CPUs | NUMA | Visible memory | Local scratch | GPU tools |
|---|---|---|---:|---:|---:|---:|---|
| `batch` | `p33c30n3` | Intel Xeon Platinum 8360Y | 72 | 2 | 251 GiB | 600 GB | none found |
| `batch_icelake` | `r33c27n1` | Intel Xeon Platinum 8360Y | 72 | 2 | 251 GiB | 600 GB | none found |
| `bigmem` | `k28l07` | Intel Xeon Platinum 8360Y | 72 | 4 | 2.0 TiB | 600 GB | none found |
| `hugemem` | `s28l08` | Intel Xeon Platinum 8360Y | 72 | 2 | 7.9 TiB | 600 GB | none found |

All sampled nodes expose 72 logical CPUs with one hardware thread per core:
2 sockets, 36 cores per socket, SMT disabled. The thin CPU partitions and memory
partitions share the same CPU model in this probe set; the important differences
are memory capacity, NUMA layout, and operational partition policy.

## Node Class Details

### Thin CPU: batch and batch_icelake

Observed partitions `batch` and `batch_icelake` are effectively the same
hardware class in the sampled probe output:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core.
- NUMA: 2 NUMA domains, 36 CPUs per NUMA domain.
- Memory: about 251 GiB visible to Linux; NUMA domains report about
  128.6 GB and 129.0 GB each.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`.
- Block device: Intel 960 GB SSD class device backing the local scratch volume.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 176 GB/s local NUMA
bandwidth and about 55.7 GB/s remote NUMA bandwidth for both sampled nodes.

Use these partitions for normal CPU jobs that fit within the standard memory
envelope. Prefer NUMA-aware placement or first-touch initialization for memory
bandwidth-sensitive jobs.

### Big Memory: bigmem

Observed `bigmem` node `k28l07` has the same CPU model and core count as the
thin CPU nodes, but a different memory topology:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core.
- NUMA: 4 NUMA domains, 18 CPUs per NUMA domain.
- Memory: about 2.0 TiB visible to Linux; each NUMA domain reports about
  516 GB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 164 GB/s within
nearby NUMA domains and about 55.8 GB/s to more distant NUMA domains. The
4-domain layout means placement matters more than on the thin CPU nodes for
large shared-memory jobs.

Use `bigmem` when memory capacity, not extra CPU throughput, is the reason for
the allocation.

### Huge Memory: hugemem

Observed `hugemem` node `s28l08` is a very large memory node with the same CPU
model and core count:

- CPU: `2 x Intel Xeon Platinum 8360Y`, 36 cores per socket.
- Logical CPUs: 72, one thread per core.
- NUMA: 2 NUMA domains, 36 CPUs per NUMA domain.
- Memory: about 7.9 TiB visible to Linux; each NUMA domain reports about
  4.13 TB.
- Local scratch: 600 GB logical volume mounted at `/local_scratch`.
- Block devices: Intel 960 GB SSD class device and Samsung 960 GB NVMe class
  device were visible; the scratch logical volume is 600 GB.
- GPU tools: neither `nvidia-smi` nor `rocm-smi` was found.

Measured Intel MLC read-only bandwidth matrix showed about 149 GB/s local NUMA
bandwidth and about 55.7 GB/s remote NUMA bandwidth. The local bandwidth is
lower than the thin CPU sample, so do not assume the huge-memory node is a
faster CPU node. Use it for capacity-bound workloads.

## Performance-Relevant Observations

- All sampled CPU nodes have AVX-512-capable Ice Lake CPUs.
- SMT is disabled in the sampled allocations.
- Thin CPU and `batch_icelake` probes showed two NUMA domains with half the
  cores and half the memory in each domain.
- `bigmem` showed four NUMA domains; memory placement and process/thread
  binding are more important there.
- `hugemem` showed two very large NUMA domains and lower local MLC bandwidth
  than the thin CPU samples.
- The probe ran Intel MLC without permission to modify prefetchers, so treat
  bandwidth values as useful comparative signals rather than definitive
  benchmark claims.
- Local scratch was consistently exposed as a 600 GB logical volume, despite
  the underlying boot/storage devices being larger.

## Refresh Procedure

Use the hardware probe script from a remote working directory:

```bash
hpc --profile <profile> submit --test-only hardware-probe.slurm --directory <remote-dir>
hpc --profile <profile> submit hardware-probe.slurm --directory <remote-dir>
```

For each result directory named `hardware-probe-<host>-<jobid>`, inspect:

- `summary.env` for host, partition, cluster, job ID, CPU allocation, and
  scratch variable.
- `lscpu.txt` for CPU model, core/socket/thread counts, cache sizes, and flags.
- `numactl-hardware.txt` for NUMA domains, CPU placement, and domain memory.
- `memory.txt` and `meminfo.txt` for Linux-visible memory.
- `lsblk.txt`, `df.txt`, and `mounts.txt` for local scratch and filesystem
  layout.
- `intel-mlc-bandwidth.txt` and `intel-mlc-latency.txt` for comparative memory
  behavior when MLC is available.
- `nvidia-smi.txt` and `rocm-smi.txt` for GPU inventory or absence.

When updating this report, keep measured observations separate from site
documentation and Slurm policy. Probe output describes the sampled allocated
nodes; it does not by itself prove every node in a partition is identical.
