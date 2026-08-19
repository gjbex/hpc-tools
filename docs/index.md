# hpc-tools

`hpc-tools` provides a profile-based `hpc` command for common SSH and Slurm
workflows on remote high-performance computing systems. It also provides Codex
skills and an optional structured MCP interface for agent-assisted cluster
work.

The tools are intended for users who already have SSH access to a Slurm-based
cluster and want repeatable ways to inspect the site, prepare software, submit
jobs, and retain enough local context to resume work safely.

## Start here

- Follow [Getting started](getting-started.md) to install the CLI, configure a
  profile, and perform the first read-only checks.
- Read [CLI, Codex, and MCP](interfaces.md) before installing more than one
  interface. They are related but separate distribution and authorization
  surfaces.
- Use [Submission tracking](submissions.md) when following a Slurm job from
  submission through collection and analysis.
- Use [Cluster reference sets](reference-sets.md) to share durable cluster-wide
  hardware, Slurm, and storage context without sharing user credentials or
  accounting state.

## What hpc-tools covers

The current command and workflow surface includes:

- named SSH profiles and bounded remote inspection;
- Slurm limits, job validation, submission, monitoring, and accounting;
- cluster hardware, storage, module, and quota discovery;
- packaged CPU and GPU probe workflows;
- Python, R, and C/C++ dependency helpers;
- job arrays, benchmarks, containers, and remote build workflows;
- append-only local submission tracking;
- durable profile references and shareable reference sets.

## Safety boundary

Slurm submissions can consume allocation credits and remote actions can modify
cluster state. Prefer dry runs, quote the complete workload when the site
supports quoting, validate jobs before submission, and start with a small
pilot.

The higher-level workflows apply these safeguards where possible. The generic
`hpc run` command executes the command supplied by the user and therefore
cannot provide the same protection against an unsafe remote operation.

## Project status

`hpc-tools` is under active development. The optional `hpc-mcp` interface is
experimental. Command availability can also depend on capabilities configured
for the selected profile and on services exposed by the target cluster.
