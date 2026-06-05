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

For cluster-specific jobs, include `--cluster` when needed:

```bash
hpc --profile <profile> jobs --cluster <cluster>
hpc --profile <profile> run 'squeue -M <cluster> -j <jobid> -o "%.18i %.9P %.40j %.8u %.2t %.10M %.10l %.6D %R"'
```

## Hardware and Site Context

Before choosing partitions, memory, CPU counts, GPU directives, account
directives, cluster flags, or I/O paths for a job script, check whether the
selected profile exposes local hardware/site context:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
```

Use local hardware references to map requested resources to node types and
partitions. Use storage references to choose appropriate scratch filesystems for
parallel I/O and to avoid home/data filesystems that are not intended for heavy
job I/O. For workloads with many frequent small-file reads/writes, consider
local node scratch when available, but include stage-in, stage-out, and failure
handling because local scratch disappears when the job allocation ends. Use the
site-provided node-local scratch variable when one exists, and remember that
local scratch capacity may be shared with other jobs on the node rather than
reserved by the scheduler. Use source URLs when the user asks for current
details or when the local reference appears stale. Do not hardcode site-specific
partitions or filesystem paths in this skill.

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

Some Slurm sites require credits on an account before jobs can run. When the
profile exposes accounting helpers, inspect them before writing or submitting
jobs that use `#SBATCH --account=<account>`:

```bash
hpc --profile <profile> balance
hpc --profile <profile> statement --account <account>
hpc --profile <profile> statement --account <account> --start <YYYY-mm-dd> --end <YYYY-mm-dd>
hpc --profile <profile> quote srun -M <cluster> -p <partition> -A <account> -t <HH:MM:SS> <resource-options>
```

Use `balance` to identify accessible accounts and available or reserved credits.
Use `statement` to inspect transactions for a specific account. Use `quote` to
estimate the maximum credit cost before submitting a job when the site provides
a quote command. Include the same Slurm resource options that will be used for
submission, such as cluster, partition, walltime, node count, CPU count, memory,
and GPU requests. Present the quote to the user before submitting, because
credits can have monetary value. If these commands are not present in help, the
selected profile does not define the corresponding accounting commands.

If the user has access to multiple credit accounts, ask which account to charge
before submitting a job or generating a final submission script. Do not choose
an account only because it has enough balance or appeared in a previous job.
Credits can have monetary value, and account usage is often used for project
reporting, so charging the correct account matters even for small test or probe
jobs.

When creating a job script, do not assume `#SBATCH --account=...` is required.
Include it only when the target site/profile requires an account, the user
provides an account, an existing project template uses one, or accounting
helpers indicate that jobs are charged to accounts. On systems that do not use
credits/accounts, omit the account directive.

## Job Scripts

Use this generic single-node batch template, adapting account, cluster,
partition, resources, modules, and commands to the target site. The account line
is optional:

```bash
#!/bin/bash -l
#SBATCH --job-name=<job-name>
#SBATCH --account=<account>  # omit unless the site requires an account
#SBATCH --clusters=<cluster>
#SBATCH --partition=<partition>
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
For compiled-code jobs, do not assume the system image compiler is suitable;
HPC images often keep `/usr/bin/gcc`, `/usr/bin/g++`, or CMake older than the
project requires. Use the module system for compilers, CMake, MPI, and similar
build/runtime tools when the site provides them. Prefer explicit module
versions, such as `<compiler-module/version>` or `<cmake-module/version>`, over
generic module names so job scripts remain reproducible. Discover and verify
candidate versions with `hpc module-spider <tool>` or a remote `module avail`
query before pinning them.

Validate before submission:

```bash
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir>
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

Use `hpc submit` overrides for pilots and small resource checks, for example:

```bash
hpc --profile <profile> submit <jobscript> --directory <remote-dir> \
    --array 4 --time 00:05:00 --cpus-per-task 4
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
