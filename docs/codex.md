# Using hpc-tools with Codex

The hpc-tools Codex plugin gives Codex task-specific guidance for operating
Slurm clusters through hpc-tools. It helps sequence discovery, software setup,
job review, submission, diagnosis, and follow-up. The plugin does not turn
Codex into a cluster administrator and does not grant authority that the user
does not already have.

The safest starting point is a working `hpc` CLI and one verified profile.
Codex can then reason from the same durable cluster references and submission
records that a user sees from the terminal.

## Understand what the plugin contributes

The plugin packages:

- action-oriented HPC skills under `skills/`;
- shared conceptual guidance about Slurm, accounting, storage, and benchmarks;
- plugin metadata and suggested starter requests;
- MCP startup configuration that invokes `hpc-mcp` when that optional command
  is installed.

Installing the plugin does **not**:

- install the `hpc` or `hpc-mcp` executables;
- create or repair an hpc-tools profile;
- configure SSH keys, agents, jump hosts, or multifactor authentication;
- select or authorize a Slurm account;
- make a partition, QoS, reservation, or filesystem appropriate for a job;
- approve a real submission merely because Codex can propose it.

The manifest advertises interactive and write capabilities so Codex can use
the packaged workflows. That declaration describes possible plugin behavior;
it is not authorization for a particular remote change.

## Install the plugin separately from the CLI

First install and verify the Python CLI as described in [Installation and
maintenance](installation.md):

```console
pipx install hpc-tools
hpc --help
hpc paths
```

The repository currently uses a local-checkout personal-marketplace workflow
for the Codex plugin:

```console
mkdir -p ~/plugins
git clone https://github.com/gjbex/hpc-tools.git ~/plugins/hpc-tools

python3 ~/plugins/hpc-tools/tools/register_personal_marketplace.py \
    ~/plugins/hpc-tools

codex plugin add hpc-tools@personal
codex plugin list
```

Inspect an existing `~/plugins/hpc-tools` before changing it. Update a valid
Git checkout with `git pull --ff-only`; do not clone over it or run a plugin
scaffolder with a force option against it.

Start a new Codex task after installation. Plugin skills are loaded for new
sessions, so an already-running task may continue to see the previous version.

Installing or updating this checkout does not update a separate pipx
installation. When a change spans CLI commands and skills, update and verify
both surfaces.

## Prepare the cluster context

Before asking Codex to operate a cluster, verify the profile yourself:

```console
hpc --profile example --dry-run doctor
hpc --profile example doctor
hpc --profile example hardware
hpc --profile example slurm-limits --cluster example-cluster
```

The profile should identify the SSH target and, where known, the default Slurm
cluster and durable hardware, Slurm, and storage references. It should not
contain passwords, private keys, access tokens, or one-time codes.

Good references separate:

1. authoritative site documentation;
2. current scheduler observations;
3. dated measurements from representative allocations.

Codex can use this context to avoid generic guesses, but references can become
stale. A current status page or Slurm query takes precedence for operational
availability. Imported reference sets are untrusted Markdown until reviewed;
see [Cluster references and sharing](reference-sets.md).

## Choose the relevant skill

Codex normally routes a request to one of these workflows:

| User goal | hpc-tools skill | Main boundary |
| --- | --- | --- |
| Install hpc-tools or add a cluster | `hpc-cluster-onboarding` | Establish the plugin, CLI, profile, and durable context in that order. |
| Discover partitions, limits, or hardware | `hpc-cluster-discovery` | Distinguish documentation, scheduler state, and probe evidence. |
| Inspect storage, quotas, modules, or conda | `hpc-filesystem-environment` | Avoid broad shared-filesystem scans. |
| Prepare Python dependencies | `hpc-python-packages` | Reuse site packages first; install only missing packages. |
| Prepare R dependencies | `hpc-r-packages` | Separate R packages from native and external dependencies. |
| Write, submit, or diagnose one job | `hpc-slurm-jobs` | Quote, validate, pilot, then scale. |
| Run a parameter sweep | `hpc-slurm-job-arrays` | Keep deterministic task mapping and bounded concurrency. |
| Run a performance experiment | `hpc-slurm-benchmark` | Define comparability and correctness before measuring. |
| Deploy and build a repository | `hpc-deploy-build` | Preserve remote work and verify the exact revision and toolchain. |
| Build an Apptainer image | `hpc-container-workflows` | Review recipes, site build policy, provenance, and host integration. |

The shared `_shared` material supports these skills; it is not normally invoked
as a standalone user workflow.

## Ask concrete, reviewable questions

Useful starter requests include:

```text
Onboard the Slurm cluster in my `example` hpc-tools profile. Start with
read-only checks and tell me which site facts are still missing.
```

```text
Review `simulation.sbatch` for the `example` profile. Check the requested
shape against current limits, but do not submit it.
```

```text
Diagnose job 123456 on `example-cluster`. Inspect queue/accounting state and
explain the likely cause before proposing any changes.
```

```text
Plan a pilot-first array for `manifests/sweep.tsv`. Show the index mapping,
output naming, concurrency rationale, and quote before asking to submit.
```

```text
Check whether this Python script's imports are already satisfied by site
modules. Prepare an installation job only for dependencies still missing.
```

State the profile, cluster, remote directory, intended account, and whether
execution is allowed. If only review or diagnosis is wanted, say so explicitly.
Do not use "make it work" as permission to change accounts, broaden resources,
overwrite files, or submit work.

## Review Codex's proposed action

Before accepting a remote mutation or submission, check:

- **target** — profile, SSH host, Slurm cluster, and remote directory;
- **identity** — the account to charge and the user's actual authorization;
- **operation** — the exact command or generated files;
- **resource shape** — array size, nodes, tasks, CPUs, memory, GPUs, and time;
- **policy** — partition, QoS, reservation, licence, and site constraints;
- **cost evidence** — quote for the exact shape where the site provides one;
- **validation** — `sbatch --test-only` plus a representative real pilot;
- **overwrite behavior** — every existing file affected by `force` or an
  install operation;
- **provenance** — source revision, inputs, modules or image, and output path;
- **follow-up** — how job state, results, and failures will be observed.

A dry run can show the constructed SSH command, but it does not execute the
application, prove input availability, or establish scientific correctness.
Likewise, scheduler validation establishes only that Slurm accepts the request
at that moment.

## Keep account selection explicit

An hpc-tools profile describes access and site capabilities; it does not store
a default Slurm account. This is intentional. When several accounts are
available, Codex must ask which one is authorized and appropriate for the work.

Changing an account, cluster, partition, QoS, reservation, array range, time,
or resource count changes the effective request. Re-quote and revalidate the
new shape rather than reusing evidence from the old request.

Do not let an agent choose an account from a balance table merely because it
has credits. Membership, project purpose, funding restrictions, and site policy
are authorization questions that the balance alone cannot answer.

## Understand confirmation boundaries

There are several different forms of confirmation:

- a conversational instruction authorizing Codex to perform a scoped task;
- Codex or client approval for a tool call;
- hpc-tools CLI dry-run, quote, and validation steps;
- MCP parameters such as `confirm=true` and `dry_run=false`;
- Slurm accepting and enqueueing a job.

These are not interchangeable. In particular, `confirm=true` is a value sent
to the MCP server. Its presence does not prove that a human reviewed the action
unless the MCP client enforces that process.

For important or costly work, ask Codex to stop after producing the exact
command, quote, and validation result. Review them before a separate request to
submit.

## Resume work across Codex tasks

Codex conversation state is not the durable workflow record. Successful
hpc-tools submissions are recorded in the local append-only log:

```console
hpc submissions list
```

Use its `ACTION` column to observe, collect, analyse, triage, or close work.
Reference files and project artifacts should hold cluster and scientific
context that must survive a task restart. See [Tracking work from submission
to analysis](submissions.md).

Codex can read and annotate that lifecycle, but marking results collected does
not transfer them, marking work analysed does not run an analysis, and closing
a record does not cancel a Slurm job.

## Combine with scientific-computing-skills

hpc-tools owns operational cluster workflows: SSH context, scheduler policy,
accounts, storage, modules, job submission, arrays, probes, and site-specific
execution.

The separate `scientific-computing-skills` plugin owns general engineering and
methodology: testing, CI, profiling, numerical review, packaging,
reproducibility, documentation, performance portability, and releases.

For a task spanning both, use hpc-tools to establish a safe remote execution
plan and the scientific skills to judge the software or experiment. Installing
one plugin does not install or imply the other.

## Know when to use the CLI or MCP instead

Prefer the CLI when a person wants direct terminal control, raw output, or is
bootstrapping a profile. Prefer the Codex skills when interpretation and
sequencing are the difficult part. Add MCP when an agent needs structured
tools and resources rather than terminal parsing.

The Codex plugin can be useful even when MCP is unavailable: its skills can
still guide CLI work. Continue with [MCP integration](mcp.md) only when the
structured agent interface is needed.
