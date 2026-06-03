---
name: hpc-filesystem-environment
description: Inspect remote HPC filesystem, quota, storage, ownership, software environment, Lmod modules, and conda environments through hpc-tools. Use when the user asks about home/data/scratch/project storage, quota state, path ownership, module availability, or remote conda configuration on a configured HPC profile.
---

# HPC Filesystem Environment

## Remote Access

Use the installed `hpc` CLI. Prefer `--profile <name>` when the user names a
cluster/profile; otherwise use the configured default profile:

```bash
hpc --profile <profile> run '<command>'
```

Commands run through the profile's configured login shell. If SSH prints a
firewall or login-gate URL, wait for the user to complete it, then retry.

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
```

## Quotas and Storage

Inspect quota state when configured:

```bash
hpc --profile <profile> quota
```

Treat quota warnings seriously:

- Block quota can block clones, builds, and generated output.
- File-count quota can fail jobs even when block usage is below quota.
- Summarize both block usage and file-count usage when either is near or over
  quota.

For configured project storage:

```bash
hpc --profile <profile> projects
```

For jobs with parallel I/O or heavy temporary I/O, use the profile's storage
reference to identify the appropriate scratch filesystem. Do not assume home or
data filesystems are suitable; on many HPC systems they are NFS-mounted and not
intended for parallel I/O.

For ownership or path questions, inspect likely paths directly:

```bash
hpc --profile <profile> run 'ls -ld <path>'
hpc --profile <profile> run 'df -h <path> 2>/dev/null || true'
hpc --profile <profile> run 'du -sh <path> 2>/dev/null || true'
```

Do not delete files or environments unless the user explicitly asks. For cleanup
requests, first report the target path, approximate size, filesystem, and any
quota pressure it appears to address.

## Lmod Software Availability

Search software through Lmod rather than guessing module names:

```bash
hpc --profile <profile> module-spider <tool>
hpc --profile <profile> module-spider <full-module-name>
```

If a module exists but cannot be loaded, inspect the full module with
`module spider <full-module-name>` for prerequisite cluster modules or toolchain
context.

## Conda Environments

Use these commands to answer conda environment questions:

```bash
hpc --profile <profile> run 'which conda; conda --version'
hpc --profile <profile> run 'conda env list'
hpc --profile <profile> run 'conda info'
hpc --profile <profile> run 'conda config --show envs_dirs'
```

Summarize named environments separately from path-only environments when that
helps the user scan the result. Do not assume path-only environments are
mistakes; check `envs_dirs`, the path prefix, and the user's context before
recommending cleanup.
