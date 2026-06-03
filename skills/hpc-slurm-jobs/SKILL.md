---
name: hpc-slurm-jobs
description: Monitor, create, submit, and follow Slurm jobs on a configured remote HPC system through hpc-tools. Use when the user asks about queue state, squeue, pending/running jobs, writing Slurm job scripts, validating with sbatch --test-only, submitting jobs, checking sacct, inspecting job output, or summarizing Slurm job results.
---

# HPC Slurm Jobs

## Remote Access

Use the installed `hpc` CLI. Prefer `--profile <name>` when the user names a
cluster/profile; otherwise use the configured default profile:

```bash
hpc --profile <profile> run '<command>'
```

Commands run through the profile's configured login shell. If SSH prints a
firewall or login-gate URL, wait for the user to complete it, then retry.

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
directives, or cluster flags for a job script, check whether the selected
profile exposes local hardware/site context:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
```

Use local hardware references to map requested resources to node types and
partitions. Use source URLs when the user asks for current hardware details or
when the local reference appears stale. Do not hardcode site-specific partitions
in this skill.

## Accounts and Credits

Some Slurm sites require credits on an account before jobs can run. When the
profile exposes accounting helpers, inspect them before writing or submitting
jobs that use `#SBATCH --account=<account>`:

```bash
hpc --profile <profile> balance
hpc --profile <profile> statement --account <account>
hpc --profile <profile> statement --account <account> --start <YYYY-mm-dd> --end <YYYY-mm-dd>
```

Use `balance` to identify accessible accounts and available or reserved credits.
Use `statement` to inspect transactions for a specific account. If these
commands are not present in help, the selected profile does not define the
corresponding accounting commands.

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

set -euo pipefail

module purge
# module load <required modules>

# job commands
```

Prefer `#!/bin/bash -l` so the environment is initialized before module loads.
Only add explicit cluster modules when testing shows the login shell alone is
insufficient or the user wants that explicit dependency.

Validate before submission:

```bash
hpc --profile <profile> submit --test-only <jobscript> --directory <remote-dir>
```

`sbatch --test-only` validates submission parsing; it does not prove that module
loads or runtime commands work on the allocated node.

## Submission and Follow-Up

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

Summarize state, exit code, elapsed time, node if known, and the key output or
failure cause.
