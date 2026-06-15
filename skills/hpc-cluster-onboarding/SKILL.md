---
name: hpc-cluster-onboarding
description: Guide a first-time hpc-tools setup for an arbitrary Slurm-based HPC system. Use when the user wants to onboard a new cluster/profile, collect site facts, discover Slurm partitions and limits, identify storage and quota commands, run hardware probes, or create reusable hardware, Slurm, and storage reference notes for hpc-tools skills.
---

# HPC Cluster Onboarding

## Local Installation

Before creating or using a remote profile, verify that `hpc-tools` is installed
and that the `hpc` command is on `PATH`:

```bash
command -v hpc
hpc --help
```

If the command is missing, install the released CLI with `pipx`:

```bash
pipx install hpc-tools
pipx ensurepath
```

If the user is working from the `hpc-tools` repository root before release,
use a local release-style install instead:

```bash
pipx install .
```

Do not proceed to remote profile checks until the local `hpc --help` command
works.

Use `python3 -m pip install --user -e .` only when the user is developing
`hpc-tools` itself.

## Remote Access

Use the installed `hpc` CLI for remote commands after a profile exists:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Conceptual References

During onboarding, use the shared conceptual references to decide what facts
belong in durable profile notes:

- [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md) for
  partitions, QoS, submit limits, array limits, job-script conventions, and
  probe-job requirements;
- [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) for filesystem
  roles, quota interpretation, parallel I/O, local scratch, and search hygiene;
- [`../_shared/hpc-accounting-safety.md`](../_shared/hpc-accounting-safety.md)
  for charge-account selection and quote-before-submit rules.

## Goal

Build enough local reference context for the other hpc-tools skills to make
site-aware decisions without hardcoding site facts into generic skills. Assume
Slurm is the scheduler, but do not assume site-specific partitions, accounts,
storage paths, module names, or quota commands.

Produce or update three concise profile reference notes under the hpc-tools
config directory when possible. `hpc paths` shows the active location; normally
it is `$XDG_CONFIG_HOME/hpc-tools/profiles/<profile>/` when `XDG_CONFIG_HOME`
is set, otherwise `~/.config/hpc-tools/profiles/<profile>/`:

- hardware reference: node classes, CPUs, GPUs, memory, local scratch,
  interconnect, and partition mapping;
- Slurm reference: cluster names, partitions, walltime and array limits,
  account/QoS policy, and job-script conventions;
- storage reference: home/project/scratch filesystems, quota commands,
  parallel-I/O guidance, and local scratch behavior.

If the site publishes an operational status page, add it to the profile as
`status_url`. This gives later skills a current source to check when login,
storage, OnDemand, Slurm, or job-start behavior looks like a site incident.

The recommended durable layout is:

```text
<hpc-tools-config-dir>/
├── config.toml
└── profiles/
    └── <profile>/
        ├── hardware.md
        ├── slurm.md
        ├── storage.md
        ├── partition-report.md
        ├── probe-hardware-report.md
        └── probe-results/
```

Treat repository files under `examples/` as templates and examples. Do not store
user-generated cluster references only inside the `hpc-tools` checkout, because
the user should be able to delete the checkout after installation.

When the resulting hardware, Slurm, and storage references are stable enough to
share with other users of the same system, package them as a shared reference
set with `hpc references create <name>` and `hpc references export <name>`.
Other users can then `hpc references import <archive>` and
`hpc references attach <name>` instead of regenerating the same reference notes.

## Guided Process

Work in phases and stop after each phase if required access, local installation,
or user context is missing.

### 0. Verify Local Installation

Run the local installation checks above. If `hpc-tools` is not installed, help
the user install it with `pipx` before collecting remote cluster facts.

### 1. Establish a Minimal Profile

Ask for or infer:

- profile name;
- SSH target, either a configured SSH alias or explicit user/host;
- login shell, normally `["bash", "-l", "-c"]`;
- default Slurm cluster name, if the site uses Slurm federation or multiple
  clusters.
- optional notification email for Slurm jobs that may wait a long time in the
  queue.

Create or update the user's hpc-tools config outside this skill only when the
user asks. Otherwise, provide the TOML snippet they should review.

When adding reference paths to the profile, point them at durable files under
the profile reference directory shown by `hpc paths`:

```toml
hardware_reference = "~/.config/hpc-tools/profiles/<profile>/hardware.md"
slurm_reference = "~/.config/hpc-tools/profiles/<profile>/slurm.md"
storage_reference = "~/.config/hpc-tools/profiles/<profile>/storage.md"
status_url = "https://status.example.org/"
email = "user@example.org"
```

Verify:

```bash
hpc --profile <profile> --dry-run doctor
hpc --profile <profile> doctor
```

### 2. Discover Slurm Shape

Collect partition and controller-level information:

```bash
hpc --profile <profile> slurm-limits
hpc --profile <profile> slurm-limits --cluster <cluster> --partition <partition>
```

If multiple Slurm clusters are visible, rerun with `-M <cluster>` for each
cluster the user cares about.

For a selected partition, use the `hpc-cluster-discovery` skill to drill into
walltime, node counts, QoS, submit limits, array limits, and node properties.

### 3. Discover Accounts and QoS

Find whether jobs require accounts and which limits are attached to QoS or user
associations:

```bash
hpc --profile <profile> slurm-limits --cluster <cluster>
hpc --profile <profile> slurm-limits --cluster <cluster> --partition <partition> --qos <qos>
```

If `sacctmgr` access is restricted, fall back to site documentation, example job
scripts, and `sbatch --test-only` errors. Do not guess account names.

### 4. Discover Storage and Quotas

Use the filesystem/environment skill for detailed storage inspection. At a
minimum, collect:

```bash
hpc --profile <profile> storage inspect .
hpc --profile <profile> site-env
```

Identify home, project/data, shared scratch, and node-local scratch separately.
Use [`../_shared/hpc-storage-io.md`](../_shared/hpc-storage-io.md) before
recommending parallel I/O on home or data filesystems.

### 5. Discover Software Environment

Check whether the site uses Lmod or another module system:

```bash
hpc --profile <profile> site-env
hpc --profile <profile> run 'module avail 2>&1 | sed -n "1,120p"'
```

For specific tools, use `hpc module-spider <tool>` when Lmod is available.

### 6. Probe Compute Hardware

Install the packaged hardware probe script on the remote system when
documentation is missing, stale, or too coarse:

```bash
hpc --profile <profile> install-probe --kind hardware --directory <remote-dir>
hpc --profile <profile> install-hardware-probe --directory <remote-dir>
```

Pass common required directives directly when known:

```bash
hpc --profile <profile> install-probe --kind hardware --directory <remote-dir> \
    --account <account> --cluster <cluster> --partition <partition> --time 00:30:00
```

If the profile defines `email` and the user wants notification for long-queued
probe jobs, add `--mail-notifications`. This adds `#SBATCH --mail-type=END,FAIL`
only; do not add start notifications. If the user wants a different address, use
`--mail-user <address>`.

For custom edits, generate a local copy with
`hpc write-probe --kind hardware hardware-probe.slurm`, edit it, and transfer it
to the remote working directory with the user's normal file-transfer method.

Submit one probe per representative node class or partition, not one per node,
following [`../_shared/hpc-slurm-concepts.md`](../_shared/hpc-slurm-concepts.md).
Prefer short, low-impact probes first; increase walltime only when Intel MLC or
site tools need more time.

For GPU node classes, also run the packaged CUDA device-property probe when
CUDA cache sizes, shared-memory limits, register limits, compute capability, or
launch dimensions matter. Use `hpc paths` to locate
`cuda-device-properties.slurm` and the packaged CUDA source after installation.
Install the remote bundle with
`hpc --profile <profile> install-probe --kind cuda-device-properties --directory <remote-dir>`.
Quote the same cluster, partition, account, reservation, walltime, and GPU
request before submission, use a pilot-first workflow when probing multiple GPU
classes, and keep the resulting `cuda-device-properties-<host>-<jobid>`
directories as raw artifacts outside the durable `.config` reference directory.

After jobs finish, summarize probe output into the hardware reference. Keep
probe-derived facts separate from documentation-derived facts. Consolidate both
full hardware-probe and CUDA device-property findings into the profile hardware
report under `~/.config/hpc-tools/profiles/<profile>/`. After the report is
updated, use `hpc submissions mark-collected`, `hpc submissions mark-analysed`,
and `hpc submissions close` for the matching runs; do not update the local JSONL
submission log by hand unless the CLI is unavailable or broken. If an earlier
probe attempt failed and a later corrected run succeeded, close the failed run
with a superseded reason so onboarding state reflects only unresolved work.

## Handoff

Use the specialized skills after onboarding has enough context:

- `hpc-cluster-discovery`: partition limits, QoS/account limits, array limits,
  and probe interpretation;
- `hpc-filesystem-environment`: quotas, storage choices, modules, and conda;
- `hpc-slurm-jobs`: job scripts, validation, submission, queue follow-up;
- `hpc-deploy-build`: remote clone, build, and verification workflows.

## Completion Criteria

The onboarding is useful when a future agent can answer these without guessing:

- How do I connect to the login node?
- Which Slurm clusters and partitions exist?
- Which account/QoS directives are required or optional?
- What are the normal and long walltime limits?
- What is the maximum job array size?
- What per-user submit limits are visible?
- Which storage locations are for home, project data, shared scratch, and
  node-local scratch?
- Which representative node classes exist, and what CPU/GPU/memory/local disk
  properties do they have?
