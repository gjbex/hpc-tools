# Welcome to hpc-tools

`hpc-tools` helps researchers and software developers perform recurring SSH and
Slurm work through named cluster profiles. Its human-operated `hpc` command
provides a consistent interface for inspecting a site, preparing remote
software, validating and submitting jobs, following results, and retaining
enough local context to resume the work later.

The project also distributes a Codex plugin and an optional MCP server. They
reuse the same profiles and durable context, but they are separate interfaces
with separate installation and safety boundaries.

## Who this documentation is for

This guide assumes that you:

- have, or are applying for, an account on a Slurm-based HPC system;
- can use a shell and understand basic files and directories;
- know the SSH target, or have an SSH alias, for a cluster login node;
- want operational guidance rather than a replacement for the cluster's own
  documentation and support service.

You do not need to know every Slurm option before starting. However, hpc-tools
cannot decide which account you are allowed to charge, invent site policy, or
make an unsuitable resource request scientifically meaningful. The tool makes
important choices more visible; it does not remove the user's responsibility
for them.

## The problem hpc-tools addresses

HPC commands are often simple in isolation but difficult to use reliably as a
workflow. A user must remember which login host, cluster, account, partition,
module stack, filesystem, and job limits apply. The relevant facts are commonly
split between site documentation, shell configuration, previous job scripts,
and personal notes.

`hpc-tools` addresses that fragmentation in three ways:

1. **Profiles** give recurring commands a named SSH and site context.
2. **Task-oriented commands and skills** turn common operations into visible,
   repeatable sequences.
3. **Durable local records** retain consolidated cluster references and Slurm
   submission history outside an ephemeral terminal or agent conversation.

The project is deliberately not a general remote administration framework. Its
focus is user-level scientific work on Slurm systems.

## Choose how to use it

| If you want to... | Start with... |
| --- | --- |
| operate the cluster directly from a terminal | the `hpc` CLI |
| have Codex guide an HPC workflow | the Codex plugin plus the CLI |
| expose structured HPC context and guarded actions to an agent | the optional `hpc-mcp` server |
| extend the CLI with another language or workflow | the Python plugin API |

Most users should install the CLI first. It is the human interface, provides
the packaged templates, and is the simplest way to verify a profile. Read
[Choose an interface](interfaces.md) before adding the Codex plugin or MCP
server.

## What the project covers

### Cluster context and inspection

- named SSH profiles;
- login identity and Slurm-tool checks;
- site environment, storage, quota, module, and repository inspection;
- Slurm partitions, limits, associations, and QoS discovery;
- durable hardware, Slurm, and storage references;
- packaged CPU, memory, NUMA, filesystem, and GPU probes.

### Slurm job workflows

- site-specific cost or credit quotes where the site provides them;
- `sbatch --test-only` validation;
- job submission with explicit resource overrides;
- queue, job, and accounting inspection;
- append-only local submission tracking;
- task guidance for job arrays, failure triage, and result collection.

### Software and performance workflows

- remote repository setup and inspection;
- Python and R dependency discovery and compute-node installation plans;
- C and C++ dependency hints;
- Apptainer container-build templates;
- local benchmark summarization and comparison;
- Codex skills for deployment, builds, arrays, benchmarks, and containers.

## What it does not do

`hpc-tools` does not:

- create a cluster account, SSH key, or network route;
- store passwords or replace the user's SSH configuration;
- replace site documentation, acceptable-use rules, or support staff;
- select a Slurm account when the user has not authorized one;
- guarantee that a valid job request is efficient or scientifically correct;
- copy arbitrary result trees back to the local machine;
- automatically delete remote data or bulk-cancel jobs by scheduler filter;
- make the generic `hpc run` command safe when given an unsafe command.

Some commands do modify state: they can clone a repository, install a probe or
container bundle, write local files, submit a job, or cancel one explicitly
identified job. The absence of built-in deletion and bulk-cancellation commands
should not be mistaken for a claim that the entire tool is read-only.

## A recommended learning path

1. Complete the [Quick start](getting-started.md) using one cluster profile.
2. Read [Installation and maintenance](installation.md) before adding optional
   components or changing installation method.
3. Read [Core concepts and safety](core-concepts.md) before submitting a costly
   job, a broad array, or an agent-proposed action.
4. [Onboard the cluster](onboarding.md) fully: discover limits, storage,
   modules, and representative hardware, then record those facts as references.
5. Learn the [Slurm job lifecycle](slurm-jobs.md) and how to
   [track work through analysis](submissions.md).
6. Continue with [software environments](software-environments.md),
   [remote builds](remote-builds.md), and
   [cluster probes](probes.md) when those tasks arise.
7. Use [job arrays](job-arrays.md) for independent sweeps,
   [benchmarking on Slurm](benchmarking.md) for controlled performance work,
   and [container workflows](containers.md) for larger portable environments.
8. Package stable cluster-global context with [cluster references and
   sharing](reference-sets.md).
9. Add [Codex](codex.md) for guided workflows or [MCP](mcp.md) when an agent
   needs structured tools and resources.
10. Use the [end-to-end recipes](recipes.md) as compact checklists and the
    [troubleshooting guide](troubleshooting.md) to isolate failures by layer.
11. Keep the [reference](reference.md) nearby for exact commands and formats,
    and read [limitations, support, and project information](project-information.md)
    before automating, upgrading, contributing, or redistributing the project.

## Project status

The CLI and Codex skills are under active development. The `hpc-mcp` interface
is experimental. Command availability also depends on the selected profile and
the services exposed by its cluster. A command documented for one site may be
hidden for a profile that does not configure the required site-specific helper.
The project currently publishes neither a formal compatibility policy nor a
license declaration; see [Limitations, support, and project
information](project-information.md) before relying on either.
