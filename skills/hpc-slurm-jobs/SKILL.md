---
name: hpc-slurm-jobs
description: Monitor, create, submit, and follow Slurm jobs on a configured remote HPC system through hpc-tools. Use when the user asks about queue state, squeue, pending/running jobs, writing Slurm job scripts, validating with sbatch --test-only, submitting jobs, checking sacct, inspecting job output, or summarizing Slurm job results.
---

# HPC Slurm Jobs

## Remote Access

Use the installed `hpc` CLI for remote commands:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

Before giving conceptual advice or preparing a real submission, read the shared
reference that matches the decision:

- [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
  partitions, QoS, array limits, job-script defaults, and probe jobs;
- [`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
  for charge accounts, quote-before-submit, stale quotes, and pilot-first cost
  handling;
- [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for storage,
  local scratch, search hygiene, and artifact handling.

## Queue Monitoring

If the profile defines `queue_command`, use it for a site-specific occupancy
overview:

```bash
hpc --profile <profile> queue
```

Interpret site-specific occupancy output cautiously. In summaries, call out free
capacity, unavailable capacity, and pending jobs by cluster/partition only when
the command output supports those conclusions.

Use `hpc jobs` for the user's jobs:

```bash
hpc --profile <profile> jobs
```

`hpc jobs` defaults to `--cluster all` so federated Slurm profiles show jobs
across all visible clusters. For cluster-specific jobs, include `--cluster`
when needed:

```bash
hpc --profile <profile> jobs --cluster <cluster>
hpc --profile <profile> job <jobid> --cluster <cluster>
```

## Hardware and Site Context

Before choosing resources or I/O paths for a job script, use
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) and
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md), then check
whether the selected profile exposes local hardware/site context:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
```

Use local references to map requested resources to node types, partitions, and
storage choices. Use source URLs when the user asks for current details or when
the local reference appears stale.

If jobs do not start, Slurm commands fail, storage disappears, or OnDemand
sessions behave unexpectedly, check the configured `status_url` from `hpc
--profile <profile> hardware --source` before changing scripts or resource
requests. Maintenance windows can reserve compute nodes, interrupt storage, or
temporarily break Slurm commands.

When documentation is missing or uncertain, install the bundled probe script
with `hpc --profile <profile> install-hardware-probe --directory <remote-dir>`.
Pass required site directives with options such as `--account`, `--cluster`,
`--partition`, `--qos`, `--time`, or `--cpus-per-task`. Submit it through
`hpc submit`, then use the output to update a profile hardware/storage
reference. If Intel MLC is available on the node, the probe also records memory
bandwidth and latency information. MLC can take several minutes, so increase
the probe script's `#SBATCH --time` when needed. For meaningful MLC results,
request an entire node with `#SBATCH --exclusive` and, when the site enforces
CPU cgroups, set partition-specific `#SBATCH --cpus-per-task` to the full node
core count. For long-queued probe jobs, if the profile defines `email`, offer
`--mail-notifications`; this adds `#SBATCH --mail-type=END,FAIL` only. Use
`--mail-user <address>` when the user provides a different notification address.

## Accounts and Credits

Use [`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
before writing final account directives or submitting jobs. When the profile
exposes accounting helpers, inspect them before writing or submitting jobs that
use `#SBATCH --account=<account>`:

```bash
hpc --profile <profile> balance
hpc --profile <profile> statement --account <account>
hpc --profile <profile> statement --account <account> --start <YYYY-mm-dd> --end <YYYY-mm-dd>
hpc --profile <profile> quote srun -M <cluster> -p <partition> -A <account> -t <HH:MM:SS> <resource-options>
```

Use `balance` to identify accessible accounts and available or reserved credits,
`statement` to inspect transactions for a specific account, and `quote` to
estimate maximum credit cost. If these commands are not present in help, the
selected profile does not define the corresponding accounting commands.

When creating a job script, do not assume `#SBATCH --account=...` is required.
Include it only when the target site/profile requires an account, the user
provides an account, an
existing project template uses one, or accounting helpers indicate that jobs
are charged to accounts. On systems that do not use credits/accounts, omit the
account directive.

## Job Scripts

Use this generic single-node batch template, adapting account, cluster,
partition, reservation, resources, modules, and commands to the target site.
The account and reservation lines are optional:

```bash
#!/bin/bash -l
#SBATCH --job-name=<job-name>
#SBATCH --account=<account>  # omit unless the site requires an account
#SBATCH --clusters=<cluster>
#SBATCH --partition=<partition>
#SBATCH --reservation=<reservation>  # omit unless a reservation is required
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:10:00
#SBATCH --output=%x-%j.out
# Optional when the user wants completion/failure email:
#SBATCH --mail-user=<email>
#SBATCH --mail-type=END,FAIL

set -euo pipefail

module purge
# module load <required-module/version>

# For local scratch workflows, use the site-provided node-local scratch variable
# when available, stage inputs in, run there, and stage outputs back to
# persistent storage. Use trap-based cleanup/stage-out for partial results when
# useful.

# job commands
```

Prefer `#!/bin/bash -l` so the environment is initialized before module loads.
For compiled-code jobs, follow the module and reproducibility guidance in
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md). Discover
and verify candidate versions with `hpc module-spider <tool>` or a remote
`module avail` query before pinning them.

## Long Jobs and Checkpointing

When a job may exceed the partition `MaxTime`, first check whether the workload
can be decomposed into independent jobs or a Slurm array. If the application has
native checkpoint/restart support, prefer that over wrapper-level checkpointing.

For software that does not support checkpointing, check whether DMTCP is
available through the site module stack before recommending an exception to
walltime policy:

```bash
hpc --profile <profile> module-spider DMTCP
```

If DMTCP is available, treat it as a candidate that must be tested with a small
pilot job on the target partition. Load the same cluster/partition module and
DMTCP module in the job script, write checkpoints to durable or staged storage,
and verify that the application restarts correctly before relying on it for a
long production run. DMTCP is transparent for many user-space programs, but it
can fail or be unsuitable for some MPI, accelerator, licensed, networked, or
filesystem-heavy applications.

If DMTCP is not available or the pilot restart fails, report that the remaining
options are reducing runtime, decomposing the workflow externally, using another
system with a longer limit, or asking the site admins for an exception or
reservation. On charge-accounting systems, quote and re-quote any pilot,
restart, or extended run whenever the walltime, partition, account, node count,
CPU count, GPU request, or job count changes.

Validate before submission:

```bash
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir>
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir> \
    --cluster <cluster> --partition <partition> --reservation <reservation>
```

For real submissions where this preflight should be part of the command, use:

```bash
hpc --profile <profile> submit --validate-first <jobscript> --directory <remote-dir>
```

`sbatch --test-only` validates submission parsing; it does not prove that module
loads or runtime commands work on the allocated node.

Before actual submission on a site with credit accounting, run `hpc quote` when
the profile defines `sam_quote_command`, using the same account and resource
directives as the job script. Show the estimated maximum credit cost to the
user and get confirmation before submitting the job.

## Submission and Follow-Up

For workflows that submit multiple similar jobs, use a pilot-first submission
pattern. Submit one representative job or one array element first, wait for it
to complete successfully, and inspect its accounting plus output before
submitting the remaining jobs. This is especially important when many jobs share
the same script, module setup, repository path, or build step: a single path,
module, permission, or runtime error can otherwise fail every job and waste
credits, queue capacity, and diagnostic time. Only skip the pilot when the user
explicitly accepts the risk or the workload is already known to run unchanged on
the target system.

On sites with charge accounting, pilot-first does not replace cost checks. Quote
the pilot before submitting it, then quote the remaining jobs again after the
pilot succeeds and before submitting the larger batch. If the benchmark size,
walltime, CPU/GPU count, partition, account, array range, or job count changes,
the earlier quote is stale. Present the updated maximum cost and get
confirmation before submitting the remaining jobs.

Use `hpc submit` overrides for pilots and small resource checks, for example:

```bash
hpc --profile <profile> submit <jobscript> --directory <remote-dir> \
    --array 4 --time 00:05:00 --cpus-per-task 4
hpc --profile <profile> submit cuda-device-properties.slurm \
    --directory <remote-dir> \
    --cluster <cluster> --partition <gpu-partition> --account <account> \
    --reservation <reservation> --gpus-per-node 1 --time 00:10:00
```

Submit from the job directory:

```bash
hpc --profile <profile> submit <jobscript> --directory <remote-dir>
```

Immediately record the job ID and cluster from `sbatch` output. Follow up with:

```bash
hpc --profile <profile> sacct <jobid>
hpc --profile <profile> sacct <jobid> --cluster <cluster>
```

`hpc submit` appends successful real submissions to the local append-only
submission event log. Use it to resume after long queue waits or after restarting
the Codex session. Update the log through `hpc submissions`; do not edit
`submissions.jsonl` directly unless the CLI is unavailable or broken:

```bash
hpc --profile <profile> submissions list
hpc --profile <profile> submissions observe
hpc submissions mark-collected <run-id> --path <results-path>
hpc submissions mark-analysed <run-id> --path <report-path>
hpc submissions close <run-id> --reason done
```

For CUDA device-property probes, treat `device-properties.txt` as the result
artifact and the consolidated profile hardware report as the analysis artifact
after cache, shared-memory, register, and launch-limit data are summarized. Once
the durable report is updated, mark the run collected, mark it analysed, and
close it so `hpc submissions list` reflects only remaining work. If a failed or
invalid run was only used to diagnose the cause before a corrected rerun
succeeded, close the failed run with a superseded reason instead of leaving it
in triage.

The default `submissions list` view hides runs with a `closed` event and shows
active work that still needs observation, result collection, analysis, or
triage. Use `hpc submissions list --all` to replay the full history.

If a job leaves the queue quickly, check accounting and inspect the output file
in the submission directory:

```bash
hpc --profile <profile> run 'cd <remote-dir> && ls -ltr && tail -n 80 <output-file>'
```

For benchmark or sweep results, avoid doing iterative analysis through many
small remote commands. Once jobs complete, transfer compact result artifacts
such as CSV, JSON, logs, and metadata to the local workspace, then aggregate,
plot, and inspect them locally. Remote summarization is useful for a quick
sanity check or for very large data that should stay on the cluster, but local
analysis is usually faster and more reproducible for small benchmark outputs.

Summarize state, exit code, elapsed time, node if known, and the key output or
failure cause.
