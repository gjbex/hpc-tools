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

If the command is missing and the user is working from the `hpc-tools`
repository root, install it with:

```bash
python3 -m pip install --user .
```

If installation succeeds but `hpc` is still not found, ask the user to add the
user script directory to `PATH`, commonly:

```bash
export PATH="$HOME/.local/bin:$PATH"
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

## Goal

Build enough local reference context for the other hpc-tools skills to make
site-aware decisions without hardcoding site facts into generic skills. Assume
Slurm is the scheduler, but do not assume site-specific partitions, accounts,
storage paths, module names, or quota commands.

Produce or update three concise profile reference notes under
`~/.config/hpc-tools/profiles/<profile>/` when possible:

- hardware reference: node classes, CPUs, GPUs, memory, local scratch,
  interconnect, and partition mapping;
- Slurm reference: cluster names, partitions, walltime and array limits,
  account/QoS policy, and job-script conventions;
- storage reference: home/project/scratch filesystems, quota commands,
  parallel-I/O guidance, and local scratch behavior.

The recommended durable layout is:

```text
~/.config/hpc-tools/
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

## Guided Process

Work in phases and stop after each phase if required access, local installation,
or user context is missing.

### 0. Verify Local Installation

Run the local installation checks above. If `hpc-tools` is not installed, help
the user install it from the repository root with a non-editable install before
collecting remote cluster facts.

### 1. Establish a Minimal Profile

Ask for or infer:

- profile name;
- SSH target, either a configured SSH alias or explicit user/host;
- login shell, normally `["bash", "-l", "-c"]`;
- default Slurm cluster name, if the site uses Slurm federation or multiple
  clusters.

Create or update the user's hpc-tools config outside this skill only when the
user asks. Otherwise, provide the TOML snippet they should review.

When adding reference paths to the profile, point them at durable files under
`~/.config/hpc-tools/profiles/<profile>/`:

```toml
hardware_reference = "~/.config/hpc-tools/profiles/<profile>/hardware.md"
slurm_reference = "~/.config/hpc-tools/profiles/<profile>/slurm.md"
storage_reference = "~/.config/hpc-tools/profiles/<profile>/storage.md"
```

Verify:

```bash
hpc --profile <profile> --dry-run run 'hostname'
hpc --profile <profile> run 'hostname; whoami; pwd'
hpc --profile <profile> run 'command -v sbatch; command -v sinfo; command -v scontrol; command -v sacctmgr || true'
```

### 2. Discover Slurm Shape

Collect partition and controller-level information:

```bash
hpc --profile <profile> run 'sinfo -a -o "%P|%a|%l|%D|%c|%m|%G|%f"'
hpc --profile <profile> run 'scontrol show partition'
hpc --profile <profile> run 'scontrol show config | grep -Ei "ClusterName|MaxArraySize|MaxJobCount|MaxSubmitJobs|MaxTasksPerNode|SchedulerParameters"'
```

If multiple Slurm clusters are visible, rerun with `-M <cluster>` for each
cluster the user cares about.

For a selected partition, use the `hpc-cluster-discovery` skill to drill into
walltime, node counts, QoS, submit limits, array limits, and node properties.

### 3. Discover Accounts and QoS

Find whether jobs require accounts and which limits are attached to QoS or user
associations:

```bash
hpc --profile <profile> run 'sacctmgr -n -P show assoc where user=$USER format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES 2>/dev/null || true'
hpc --profile <profile> run 'sacctmgr -n -P show qos format=Name,MaxJobsPU,MaxSubmitJobsPU,MaxTRESPU,GrpJobs,GrpSubmitJobs,GrpTRES,MaxWall 2>/dev/null || true'
```

If `sacctmgr` access is restricted, fall back to site documentation, example job
scripts, and `sbatch --test-only` errors. Do not guess account names.

### 4. Discover Storage and Quotas

Use the filesystem/environment skill for detailed storage inspection. At a
minimum, collect:

```bash
hpc --profile <profile> run 'pwd; df -hT .; mount | sed -n "1,80p"'
hpc --profile <profile> run 'env | grep -Ei "HOME|DATA|SCRATCH|WORK|PROJECT|TMP|SLURM" | sort'
hpc --profile <profile> run 'command -v quota; command -v lfs; command -v beegfs-ctl; command -v mmlsquota; command -v module || true'
```

Identify home, project/data, shared scratch, and node-local scratch separately.
Do not recommend parallel I/O on home directories unless site documentation
explicitly says it is appropriate.

### 5. Discover Software Environment

Check whether the site uses Lmod or another module system:

```bash
hpc --profile <profile> run 'module --version 2>&1 || true'
hpc --profile <profile> run 'module avail 2>&1 | sed -n "1,120p"'
```

For specific tools, use `hpc module-spider <tool>` when Lmod is available.

### 6. Probe Compute Hardware

Install the packaged hardware probe script on the remote system when
documentation is missing, stale, or too coarse:

```bash
hpc --profile <profile> install-hardware-probe --directory <remote-dir>
```

Pass common required directives directly when known:

```bash
hpc --profile <profile> install-hardware-probe --directory <remote-dir> \
    --account <account> --cluster <cluster> --partition <partition> --time 00:30:00
```

For custom edits, generate a local copy with
`hpc write-hardware-probe hardware-probe.slurm`, edit it, and transfer it to the
remote working directory with the user's normal file-transfer method.

Submit one probe per representative node class or partition, not one per node.
Prefer short, low-impact probes first; increase walltime only when Intel MLC or
site tools need more time.

After jobs finish, summarize probe output into the hardware reference. Keep
probe-derived facts separate from documentation-derived facts.

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
