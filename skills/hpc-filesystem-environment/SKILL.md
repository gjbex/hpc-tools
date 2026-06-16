---
name: hpc-filesystem-environment
description: Inspect remote HPC filesystem, quota, storage, ownership, software environment, Lmod modules, and conda environments through hpc-tools. Use when the user asks about home/data/scratch/project storage, quota state, path ownership, module availability, or remote conda configuration on a configured HPC profile.
---

# HPC Filesystem Environment

## Remote Access

Use the installed `hpc` CLI for remote commands:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

Use [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for storage
roles, quota interpretation, local scratch, shared-filesystem search hygiene,
cleanup safety, and artifact handling. Use
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) when
storage decisions depend on partitions, node classes, or job-script behavior.

## Profile Capabilities

Check the selected profile before using optional helpers:

```bash
hpc --profile <profile> --help
```

Use `hpc quota` only when the profile defines `quota_command`. Use `hpc
projects` only when the profile defines `projects_dir`.

If the profile exposes site context, inspect it before making storage or I/O
recommendations:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
```

When storage paths disappear, quotas or project storage behave oddly, or remote
commands fail before reaching the expected filesystem, check any configured
`status_url` in the source output before assuming a local path or permission
problem.

## Quotas and Storage

Inspect quota state when configured:

```bash
hpc --profile <profile> quota
```

Treat quota warnings seriously, following the block and file-count guidance in
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md).

For configured project storage:

```bash
hpc --profile <profile> projects
```

For a quick status pass that combines the site status page, quota, balance, and
current submissions, use `hpc status` to collect the full report before you
split the problem into a storage-only or scheduler-only investigation. Let the
assistant summarize the attention-worthy items when you want a triage view.

For jobs with parallel I/O, heavy temporary I/O, or frequent small-file access,
use the profile's storage reference and
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) to choose between
home, project/data, shared scratch, and node-local scratch.

For ownership or path questions, inspect likely paths directly:

```bash
hpc --profile <profile> storage inspect <path>
```

Do not run blind `find` searches from top-level HPC filesystem roots such as
`VSC_DATA`, `VSC_SCRATCH`, project, data, scratch, or archive directories.
Follow the bounded-search guidance in
[`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md).

Do not delete files or environments unless the user explicitly asks. For cleanup
requests, first report the target path, approximate size, filesystem, and any
quota pressure it appears to address.

## Lmod Software Availability

Search software through Lmod rather than guessing module names:

```bash
hpc --profile <profile> module-spider <tool>
hpc --profile <profile> module-spider <full-module-name>
```

When the user needs compilers, CMake, MPI, or other build tools, recommend
site modules rather than system image tools unless live checks show the system
versions are adequate. Prefer explicit module versions in reproducible job
scripts and build commands.

If a module exists but cannot be loaded, inspect the full module with
`module spider <full-module-name>` for prerequisite cluster modules or toolchain
context.

## Conda Environments

Use these commands to answer conda environment questions:

```bash
hpc --profile <profile> site-env
hpc --profile <profile> run 'which conda; conda --version'
hpc --profile <profile> run 'conda env list'
hpc --profile <profile> run 'conda info'
hpc --profile <profile> run 'conda config --show envs_dirs'
```

Summarize named environments separately from path-only environments when that
helps the user scan the result. Do not assume path-only environments are
mistakes; check `envs_dirs`, the path prefix, and the user's context before
recommending cleanup.
