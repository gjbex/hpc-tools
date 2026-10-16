# Probes and cluster discovery

Cluster documentation tells you what should be available. Live scheduler
queries tell you what can be requested now. A compute-node probe tells you what
one actual allocation exposes. Good discovery uses all three and records where
they disagree.

Do not run a probe merely because it exists. A probe is justified when
documentation is missing, stale, too coarse, or insufficient for a concrete
compatibility or performance decision. It is a Slurm job, can consume credits,
and may run commands that site policy restricts.

## Choose the evidence source

| Question | Best starting evidence |
| --- | --- |
| What partitions and limits exist now? | `hpc slurm-limits` and live Slurm output |
| Which account, QoS, or reservation may I use? | Allocation records and authoritative site policy |
| Which node classes should exist? | Profile references and site hardware documentation |
| What did one allocation actually expose? | Hardware or CUDA probe output |
| Is the cluster or storage currently impaired? | Configured status page and focused live checks |
| How fast is my application? | A controlled application benchmark, not an inventory probe |

Start with configured context:

```console
hpc --profile example hardware
hpc --profile example hardware --source
hpc --profile example slurm-limits --cluster example-cluster
hpc --profile example site-env
hpc --profile example storage inspect '$VSC_DATA'
```

References are durable background; live output can be transient. A status-page
incident can explain a failed query, while an old reference can explain the
intended node classes. Neither should be silently treated as superior when the
evidence conflicts.

## Select representative allocations

Probe node classes, not arbitrary hostnames. Identify differences that can
change compatibility, placement, or performance:

- CPU generation, socket count, cores, hardware threads, and instruction sets;
- NUMA topology and memory capacity;
- GPU vendor, model, memory, and accelerator generation;
- local block devices and node-local scratch;
- interconnect or partition-specific placement;
- compiler, CUDA, ROCm, and runtime availability.

One probe per materially distinct class is usually enough. Probing every node
adds cost and produces data that is difficult to maintain. If a supposedly
uniform class returns inconsistent results, investigate the discrepancy before
broadening the campaign.

Use `slurm-limits` to confirm that the requested partition and resource shape
are valid. Establish the account and quoting rules as described in
[Running Slurm jobs](slurm-jobs.md).

## Understand the packaged probes

hpc-tools currently packages two probe kinds:

| Kind | Purpose | Installed assets |
| --- | --- | --- |
| `hardware` | CPU, cache, NUMA, memory, filesystems, block devices, GPU inventory, topology tools, and optional Intel MLC results | One `hardware-probe.slurm` script |
| `cuda-device-properties` | CUDA runtime and device programming properties for an allocated NVIDIA GPU | Slurm script, CMake file, and CUDA source |

Show the installed package paths:

```console
hpc paths
```

The hardware probe tolerates individual missing utilities so that one absent
tool does not discard all other evidence. Consequently, a completed job can
contain error text or absent measurements. Read the individual files; Slurm
`COMPLETED` means the script reached its end, not that every optional probe
succeeded.

## Write a probe locally

Print the hardware template for review:

```console
hpc write-probe --kind hardware
```

Or write it to a local file with verified Slurm directives:

```console
hpc --profile example write-probe \
    --kind hardware \
    --account project123 \
    --cluster example-cluster \
    --partition cpu \
    --time 00:30:00 \
    --cpus-per-task 64 \
    hardware-probe.slurm
```

Writing a local file does not contact the cluster. Existing output is protected
unless `--force` is supplied. Inspect the generated script before transferring
or submitting it.

The CUDA probe is a bundle and therefore requires an output directory:

```console
hpc write-probe \
    --kind cuda-device-properties \
    cuda-device-probe
```

Review all three files in the bundle. In particular, the packaged CUDA Slurm
script contains example CMake and CUDA module versions. They are not portable
defaults. Replace them with versions verified for the target cluster, or adapt
the script's documented module-loading control deliberately.

Use local generation when the probe needs review, source control, or
site-specific edits before it reaches the cluster. hpc-tools does not provide a
general-purpose file-transfer command; use an approved transfer method for an
adapted local bundle.

## Install a packaged probe remotely

When the packaged assets are already suitable, preview the remote write:

```console
hpc --profile example --dry-run install-probe \
    --kind hardware \
    --directory '$VSC_DATA/probes' \
    --account project123 \
    --cluster example-cluster \
    --partition cpu \
    --time 00:30:00 \
    --cpus-per-task 64
```

Then install them:

```console
hpc --profile example install-probe \
    --kind hardware \
    --directory '$VSC_DATA/probes' \
    --account project123 \
    --cluster example-cluster \
    --partition cpu \
    --time 00:30:00 \
    --cpus-per-task 64
```

`install-probe` creates the permitted remote directory and publishes probe
assets through the bounded filesystem helper. Executable scripts use mode
`0700`; other files use `0600`. Each file is staged and atomically published,
and existing files are preserved unless `--force` is present. Check the
directory and filenames carefully before intentional replacement.

The convenience alias `install-hardware-probe` installs the same hardware
kind. Prefer the generic command when documenting a workflow that may also use
the CUDA probe.

For email on completion or failure, either supply a verified address:

```console
hpc --profile example install-probe \
    --kind hardware \
    --directory '$VSC_DATA/probes' \
    --mail-user researcher@example.edu
```

or use `--mail-notifications` when the profile contains the correct `email`
field. The generated directives request `END,FAIL`, not start notifications.

## Request a meaningful CPU allocation

The hardware template requests one node, one task, and exclusive access. Keep
the exclusive request when measuring full-node memory behavior. On sites that
enforce CPU cgroups, also request the full physical core count through
`--cpus-per-task`; otherwise Intel Memory Latency Checker (MLC) may see only a
partial CPU set.

This distinction matters:

- topology and model information can still be useful from a partial
  allocation;
- aggregate memory bandwidth is not a credible full-node maximum unless the
  allocation can drive the whole node;
- shared-node contention can distort latency and bandwidth;
- simultaneous multithreading and NUMA placement affect interpretation.

If policy or cost prevents a full-node allocation, run a smaller probe only
for the questions it can answer and label the limitation. Do not publish the
result as full-node performance.

Intel MLC is optional and may be unavailable, restricted, or slow. Increase
walltime when needed. Its output characterizes synthetic memory behavior, not
application speed.

## Validate, quote, and submit

Assuming the packaged hardware probe is installed remotely, preview and ask
Slurm to validate it:

```console
hpc --profile example --dry-run submit \
    --directory '$VSC_DATA/probes' \
    --test-only \
    hardware-probe.slurm

hpc --profile example submit \
    --directory '$VSC_DATA/probes' \
    --test-only \
    hardware-probe.slurm
```

Quote the exact shape first when the site supports charging estimates. Then
submit one representative pilot:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/probes' \
    hardware-probe.slurm
```

Avoid `--validate-first` when you require a human review point after validation;
it submits immediately when the test succeeds. The successful real submission
is added to the local submission database.

Follow the job using its Slurm ID:

```console
hpc --profile example job 123456 --cluster example-cluster
hpc --profile example sacct 123456 --cluster example-cluster
```

Do not submit probes for all classes until the pilot creates the expected
output directory and useful files.

## Run the CUDA device-properties probe

Install the bundle only after checking its module assumptions:

```console
hpc --profile example --dry-run install-probe \
    --kind cuda-device-properties \
    --directory '$VSC_DATA/probes/cuda-h100'
```

The template requests one GPU per node. Some sites instead require a typed
GRES, GPU QoS, reservation, or another GPU option. The install command does not
make those policy decisions for you. Adapt the script or use reviewed
submission overrides that match site guidance.

The probe directive options exposed by `write-probe` and `install-probe` are
currently rendered into the hardware script only. They do not modify the CUDA
bundle. For CUDA, either generate and adapt the bundle locally before transfer,
or use supported `hpc submit` overrides for account, cluster, partition,
reservation, time, and GPU shape. If the site requires a QoS or different
module commands, edit and review the script itself.

The job configures and compiles a small CUDA program in node-local scratch when
available, then copies the executable and reports into the durable output
directory. It captures build diagnostics so module and compiler failures can
be distinguished from runtime device failures.

Its results normally describe the GPU visible to the allocation, not every GPU
physically installed in the node. MIG configuration, visibility controls, and
allocation policy can change that view.

## Read hardware probe output

By default the hardware probe creates:

```text
hardware-probe-<host>-<jobid>/
```

Key artifacts include:

| Artifact | Interpretation |
| --- | --- |
| `summary.env` | Job, cluster, partition, node, CPU allocation, submit directory, and node-scratch context |
| `lscpu.txt`, `lscpu-cache.txt` | CPU model, sockets, cores, threads, flags, caches, and NUMA CPU ranges |
| `numactl-hardware.txt` | NUMA memory, CPU membership, and distance matrix |
| `memory.txt`, `meminfo.txt` | User-friendly and kernel views of memory |
| `df.txt`, `mounts.txt` | Visible filesystems, types, capacity, and mount layout |
| `lsblk.txt`, `block-devices.txt` | Visible block devices; presence alone does not establish an approved scratch path |
| `nvidia-smi.txt`, `rocm-smi.txt` | GPU inventory or diagnostic failure text |
| `hwloc.txt`, `cache/` | Detailed topology and cache-sharing evidence |
| `intel-mlc-*.txt` | Optional synthetic NUMA bandwidth and latency measurements |

Start with `summary.env`. Confirm that the job actually ran on the intended
cluster, partition, node class, and CPU allocation before interpreting the
remaining files.

Errors inside files are evidence too. For example, `command not found` in
`numactl-hardware.txt` means that topology was not collected with that utility;
it does not mean the node has no NUMA topology. An empty GPU tool result is not
proof that a partition contains no accelerators unless the allocation and
visibility were also verified.

## Read CUDA probe output

By default the CUDA probe creates:

```text
cuda-device-properties-<host>-<jobid>/
```

Important files include:

- `summary.env` for allocation, source, build, and scratch locations;
- `cmake-version.txt` and `nvcc-version.txt` for toolchain identity;
- `cmake-configure.txt` and `cmake-build.txt` for diagnostics;
- `nvidia-smi.txt` for allocation-visible driver and device inventory;
- `device-properties.txt` for CUDA runtime and driver versions, device name,
  compute capability, streaming multiprocessor count, global memory, L2 cache,
  persisting-L2 limit, shared-memory and register limits, memory clock and bus
  width, theoretical bandwidth, launch dimensions, and residency limits.

Theoretical bandwidth is derived from reported device properties. It is not a
measured application or memory-copy result. Likewise, architectural limits do
not predict occupancy without the kernel's register, shared-memory, block-size,
and instruction behavior.

## Consolidate evidence into references

Raw probe directories can be large. Keep them with project evidence or in an
appropriate archive, not under `~/.config/hpc-tools`. Put only concise,
sourced summaries in profile references or shared reference sets.

Summarize by node class or partition and record:

- collection date and hpc-tools version;
- Slurm job ID, cluster, partition, and allocation shape;
- hardware facts and the exact artifact supporting each claim;
- which tools were missing or failed;
- whether measurements used full-node exclusive access;
- differences from site documentation;
- unresolved questions and the support contact or evidence needed;
- limits on generalizing from one observed node.

After retaining the raw result and producing a consolidated report, update the
local workflow record:

```console
hpc --profile example submissions mark-collected <run-id> \
    --path '$VSC_DATA/probes/hardware-probe-node-123456'
hpc --profile example submissions mark-analysed <run-id> \
    --path '~/.config/hpc-tools/profiles/example/probe-hardware-report.md'
hpc --profile example submissions close <run-id> \
    --reason 'representative CPU node consolidated into hardware reference'
```

These commands record paths; they do not copy the probe data or report. See
[Tracking work from submission to analysis](submissions.md).

When the hardware, Slurm, and storage summaries are stable enough to share,
package them as described in [Cluster references and
sharing](reference-sets.md). Keep
user-specific account data, balances, submission history, and raw probe output
out of the shared bundle.

## Refresh discovery responsibly

Repeat targeted discovery after a hardware refresh, scheduler-policy change,
module-stack transition, storage migration, or material documentation conflict.
Do not rerun expensive probes on a calendar alone when authoritative evidence
shows that the relevant class has not changed.

A useful discovery report says three things separately:

1. what the site documents;
2. what Slurm currently advertises;
3. what a dated representative allocation exposed.

That separation is more durable than presenting one probe directory as the
truth about an evolving cluster.
