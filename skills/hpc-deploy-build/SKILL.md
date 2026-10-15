---
name: hpc-deploy-build
description: Deploy, build, and verify software on a configured remote HPC system through hpc-tools. Use when the user asks to clone or update repositories on an HPC login node, inspect or use remote project directories, choose build tools or Lmod modules, run remote builds/tests/examples, or diagnose build/runtime issues outside Slurm job management.
---

# HPC Deploy Build

## Remote Access

Inspect the selected profile before using remote commands:

```bash
hpc --profile <profile> capabilities
hpc --profile <profile> --help
```

For policy denials, profile selection, optional helpers, login-gate handling,
`--dry-run`, and remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

Use [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) before
choosing clone/build locations or diagnosing quota and filesystem pressure. Use
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
module-version and reproducibility guidance that also applies to job scripts.

## Discover Profile Capabilities

Before relying on profile-specific helpers, check what is configured:

```bash
hpc --profile <profile> --help
hpc --profile <profile> --dry-run run 'hostname'
```

Only use these helpers when they appear in help or the profile defines the
corresponding field:

- `hpc projects` requires `projects_dir`.
- `hpc quota` requires `quota_command`.
- `hpc queue` requires `queue_command`.
- `hpc hardware` exposes optional local hardware and Slurm policy references.

When build placement matters, such as GPU model, CPU generation, memory class,
local disk, or partition choice, inspect hardware context first:

```bash
hpc --profile <profile> hardware
```

## Deploy Repositories

When cloning to the remote HPC system, run an actual `git clone` on the remote
host instead of copying a working tree, unless the user asks for a transfer.

Use the local repository only to discover URL and branch:

```bash
git -C /path/to/local/repo remote -v
git -C /path/to/local/repo status --short --branch
```

Check destination and storage first when possible:

```bash
hpc --profile <profile> projects
hpc --profile <profile> quota
hpc --profile <profile> storage inspect <remote-project-dir>
```

If the profile has `projects_dir`, clone with:

```bash
hpc --profile <profile> clone <url> --branch <branch>
```

If no project directory is configured, ask for or infer a remote destination and
pass it explicitly:

```bash
hpc --profile <profile> clone <url> --branch <branch> --directory <remote-parent-dir>
```

Verify the clone:

```bash
hpc --profile <profile> repo status --directory <remote-repo-dir>
```

## Build Environment

Check tool availability before building:

```bash
hpc --profile <profile> module-spider <tool>
hpc --profile <profile> run 'which <tool>; <tool> --version'
```

For compiled projects, check the module system before relying on tools from the
system image. Follow the reproducibility guidance in
[`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md): prefer
site modules for compilers, CMake, MPI, and related build tools, and pin
explicit module versions instead of loading generic names.

If the site uses Lmod, load the pinned modules in the same command that builds:

```bash
hpc --profile <profile> run 'module load <module/version> && cd <remote-repo-dir> && <build-command>'
```

## Build and Verify

Prefer the narrowest build/test command for the requested example or component.
Inspect local project files first when needed, then run the equivalent command
remotely.

For Cargo projects, inspect `Cargo.toml`, choose a Rust module that supports the
required edition, then build and run remotely:

```bash
hpc --profile <profile> module-spider Rust
hpc --profile <profile> run 'module load <rust-module> && cd <remote-repo-dir> && cargo build'
hpc --profile <profile> run 'module load <rust-module> && cd <remote-repo-dir> && cargo run -- <args>'
```

When summarizing build results, distinguish compilation time from runtime. For
compiled languages, the first build may be dominated by dependency or object
compilation; later runs can be much faster if build artifacts persist.
