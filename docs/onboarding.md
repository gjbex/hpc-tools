# Onboarding a new cluster

Onboarding is complete when you can choose appropriate resources, validate a
small job, and explain the important site constraints to another user. A
successful SSH connection is only the starting point.

The intended result is:

- a working [cluster profile](configuration.md);
- verified knowledge of partitions, accounts, QoS rules, storage, modules, and
  representative node classes;
- durable hardware, Slurm, and storage references with source links;
- an explicit list of facts that remain unknown or require confirmation.

Do not infer policy from generic Slurm knowledge. Site documentation and live
scheduler output take precedence, and account authorization must never be
guessed.

## Before you start

You need:

- an active cluster account and a working SSH configuration;
- `hpc` installed locally; see [Installation and maintenance](installation.md);
- permission to run read-only scheduler queries;
- a small allocation or test account before submitting probes;
- a local directory outside this repository for durable references.

Run `hpc paths` to see the intended configuration and reference locations.

## 1. Create and verify a minimal profile

Create a profile containing only the connection target:

```toml
default_profile = "example"

[profiles.example]
ssh_target = "example-login"
```

Check the SSH command before connecting, then run the diagnostic:

```console
hpc --profile example --dry-run doctor
hpc --profile example doctor
```

`doctor` checks the remote identity and whether core Slurm commands are
available. Resolve SSH, shell initialization, and missing-command problems
before collecting further evidence. If the cluster is not Slurm-based, the
operational workflows documented here do not apply without an extension.

## 2. Discover the Slurm shape

Start with the scheduler rather than with a job script copied from another
cluster:

```console
hpc --profile example slurm-limits
```

At a multi-cluster site, narrow the query if necessary:

```console
hpc --profile example slurm-limits --cluster example-cluster
```

Record at least:

- cluster and controller names;
- partitions and their intended workloads;
- default and maximum run times;
- node, task, CPU, memory, and GPU limits;
- available QoS names and the limits they impose;
- array-size and concurrent-task limits;
- reservations or special partitions relevant to your work.

The command reports live scheduler information, but visibility depends on site
permissions. A missing association or QoS entry does not prove that none
exists. Compare the output with authoritative site documentation and record
any discrepancy.

## 3. Establish account and charging rules

Determine which Slurm account, cluster, partition, and QoS combinations you
are authorized to use. Possible evidence includes:

- site allocation or account portals;
- documented site commands;
- visible Slurm associations;
- a minimal `sbatch --test-only` validation;
- confirmation from cluster support.

Some sites restrict `sacctmgr`, so absence of output is not authorization to
invent an account name. Mark the account as unknown until it is confirmed.

If the site provides accounting helpers, add only the verified commands to the
profile:

```toml
[profiles.example]
ssh_target = "example-login"
sam_balance_command = "site-balance"
sam_statement_command = "site-statement"
sam_quote_command = "site-quote"
```

Then inspect the available commands:

```console
hpc --profile example --help
hpc --profile example balance
```

Where quoting is supported, quote the exact resource shape. The quote command
requires an explicit account:

```console
hpc --profile example quote sbatch \
    --account=project123 \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=4 \
    --time=00:10:00 \
    job.sh
```

A quote estimates or reports cost; it does not prove that the account is
authorized. Re-quote after changing the shape, duration, or number of jobs.

## 4. Map storage and quotas

Discover the login environment and inspect candidate paths:

```console
hpc --profile example site-env
hpc --profile example storage inspect '$HOME'
hpc --profile example storage inspect '$VSC_DATA'
```

Quote remote variables so that your local shell does not expand them. If the
site has a quota command, configure and run it:

```toml
quota_command = "quota -s"
```

```console
hpc --profile example quota
```

For each filesystem, record:

- its intended role: home, project, scratch, archive, or node-local temporary
  storage;
- quota and file-count limits;
- backup or purge policy;
- performance guidance, especially for many small files;
- whether compute nodes can access it;
- environment variables or canonical paths used by the site.

`storage inspect` is deliberately bounded. It reports useful context without
recursively walking a large filesystem. It neither diagnoses every storage
problem nor removes data.

If the cluster provides a stable project root, add it to the profile:

```toml
projects_dir = "$VSC_DATA/projects"
```

## 5. Understand modules and language environments

Record how the site initializes its module system and which compiler, MPI,
CUDA, Python, R, and Apptainer modules are relevant. Search for a module without
assuming that an unversioned default is stable:

```console
hpc --profile example module-spider gcc
hpc --profile example module-spider cuda
```

Prefer explicit versions in reproducible job scripts. Also record module
prerequisites and incompatible combinations. A module that appears in a search
may still be unavailable on a particular partition or unsuitable for binaries
built with a different compiler or MPI implementation.

For project-specific dependencies, keep environments in an appropriate project
or data filesystem rather than repeatedly installing them from compute jobs.

## 6. Identify representative hardware

Consult site documentation first. Then identify distinct node classes, not
every individual node. Relevant distinctions can include:

- CPU model or generation;
- sockets, cores, hardware threads, and NUMA layout;
- memory capacity and bandwidth characteristics;
- GPU model, count, memory, and compute capability;
- local scratch devices;
- interconnect generation or topology.

Probe one representative node for each class that materially affects software
compatibility or performance. A probe is a Slurm job and may consume allocation
or incur cost.

### Install and validate a CPU probe

Preview the remote write first:

```console
hpc --profile example --dry-run install-probe \
    --kind hardware \
    --directory '$VSC_DATA/hpc-probes'
```

Install the scripts only after checking the destination:

```console
hpc --profile example install-probe \
    --kind hardware \
    --directory '$VSC_DATA/hpc-probes'
```

Use `--force` only when you intend to overwrite an existing installed probe.
The generated script can include verified site settings:

```console
hpc --profile example install-probe \
    --kind hardware \
    --directory '$VSC_DATA/hpc-probes' \
    --account project123 \
    --partition cpu \
    --time 00:15:00 \
    --cpus-per-task 64
```

Validate it before a real submission:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/hpc-probes' \
    --test-only \
    hardware_probe.sbatch
```

Hardware probes may use tools whose results depend on allocation shape. For
example, a meaningful full-node memory-bandwidth probe can require all CPUs and
exclusive access under cgroup-enforced sites. If you cannot obtain that shape,
label the measurement as partial rather than treating it as a node maximum.

### Add a GPU capability probe

For NVIDIA GPU nodes, install the CUDA device-properties probe as well:

```console
hpc --profile example install-probe \
    --kind cuda-device-properties \
    --directory '$VSC_DATA/hpc-probes'
```

It records device properties such as compute capability, memory, cache and
shared-memory limits, register capacity, and launch dimensions. This
information helps assess compatibility; it does not replace an application
benchmark.

The packaged CUDA bundle contains example module versions, and probe directive
options currently customize only the hardware template. Review and adapt the
CUDA script for the site, or apply supported account, cluster, partition,
reservation, time, and GPU overrides when submitting it. A QoS or different
module stack must be edited into the script.

You can also write probe templates locally with `hpc write-probe` and inspect
or adapt them before transfer. Use the installed probe commands for onboarding
when possible so the workflow does not depend on this repository checkout.

## 7. Consolidate durable references

Keep raw probe output in a project or evidence directory, not in the `hpc-tools`
repository. Summarize stable, user-relevant facts in three Markdown files:

- hardware classes and the evidence used to distinguish them;
- Slurm partitions, limits, accounting rules, and safe defaults;
- storage roles, quotas, lifecycle rules, and I/O guidance.

Include collection dates, commands or probe versions, and links to authoritative
site pages. Separate measured facts from documentation claims and unresolved
questions.

Create and populate a reference set:

First write the three summaries under the profile's durable configuration
directory and point the profile at them:

```toml
[profiles.example]
hardware_reference = "~/.config/hpc-tools/profiles/example/hardware.md"
slurm_reference = "~/.config/hpc-tools/profiles/example/slurm.md"
storage_reference = "~/.config/hpc-tools/profiles/example/storage.md"
```

Then copy those profile-local references into a named set, inspect it, and
validate its structure:

```console
hpc --profile example references create example-2026
hpc references show example-2026
hpc references validate example-2026
```

Then attach it to the profile:

```console
hpc --profile example references attach example-2026
```

Creation and attachment write local configuration. Preview the target paths
with `hpc paths`, and use `--force` only for an intentional replacement. See
[Cluster references and sharing](reference-sets.md) for sharing and import/export.

## Completion checklist

Before calling the cluster onboarded, verify that:

- SSH and `hpc doctor` work;
- the relevant partitions and resource limits are known;
- accounts and QoS combinations are confirmed, or explicitly marked unknown;
- home, project, scratch, and temporary-storage roles are understood;
- required module families and version constraints are recorded;
- representative CPU and GPU node classes are documented;
- a minimal job passes scheduler validation;
- durable references include dates and authoritative sources;
- unresolved policy, hardware, and charging questions are visible.

Refresh the evidence after announced hardware, scheduler, accounting, or
storage-policy changes. Otherwise, review it periodically and before planning a
large or expensive campaign.

Continue with [Everyday cluster operations](everyday-operations.md) for routine
inspection, [Running Slurm jobs](slurm-jobs.md) for the submission lifecycle,
or [Probes and cluster discovery](probes.md) for detailed probe selection and
interpretation.
