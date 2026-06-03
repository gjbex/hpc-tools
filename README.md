# hpc-tools

`hpc-tools` provides a small `hpc` command for common SSH and Slurm interactions
with remote HPC systems. Hosts are configured as named profiles, so the same
commands can target `genius`, another login node, or a local SSH alias.

## Install

From the repository root:

```bash
python3 -m pip install --user -e .
```

Make sure the user script directory is on `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Configuration

By default, `hpc` reads:

```text
~/.config/hpc-tools/config.toml
```

Set `HPC_TOOLS_CONFIG` or pass `--config` to use another file.

Two example configuration files are provided:

- [examples/ssh-alias-config.toml](examples/ssh-alias-config.toml) uses a target
  from `~/.ssh/config`, such as `ssh genius`.
- [examples/user-host-config.toml](examples/user-host-config.toml) uses explicit
  `user` and `host` fields.

SSH alias example:

```toml
default_profile = "genius"

[profiles.genius]
ssh_target = "genius"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
projects_dir = "$VSC_DATA/Projects"
quota_command = "myquota"
queue_command = "slurm_queuestate"
sam_balance_command = "sam-balance"
sam_statement_command = "sam-statement"
hardware_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/hardware.md"
hardware_url = "https://docs.vscentrum.be/leuven/tier2_hardware.html"
slurm_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/slurm.md"
slurm_url = "https://docs.vscentrum.be/leuven/slurm_specifics.html"
storage_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/storage.md"
storage_url = "https://docs.vscentrum.be/leuven/tier2_hardware/storage.html"
default_cluster = "wice"
```

`ssh_target` is passed directly to `ssh`, so it can be a configured SSH alias
from `~/.ssh/config`. For example, if `ssh genius` already expands to the right
host, username, agent forwarding, and credentials, use `ssh_target = "genius"`.
`ssh_options` is passed before the target; `["-x"]` disables X11 forwarding for
non-interactive commands.

User/host example:

```toml
[profiles.some-cluster]
host = "login.somewhere"
user = "myuser"
ssh_options = ["-x"]
```

`projects_dir` is interpreted by the remote shell. Values such as
`$VSC_DATA/Projects` are intentionally not expanded locally.

`quota_command`, `queue_command`, `sam_balance_command`, and
`sam_statement_command` are optional. If a profile does not define one of them,
the corresponding `quota`, `queue`, `balance`, or `statement` subcommand is
hidden from help for that profile and rejected if invoked anyway.

`hardware_reference`, `hardware_url`, `slurm_reference`, `slurm_url`,
`storage_reference`, and `storage_url` are optional metadata fields. They let
users and Codex skills inspect site-specific hardware, partitions, filesystems,
and Slurm policy without hardcoding those details in the generic skills. Local
reference files should be concise Markdown summaries of the relevant web
documentation.

## Commands

```bash
hpc run 'hostname'
hpc quota                  # if quota_command is configured
hpc projects
hpc clone https://github.com/org/repo.git --branch main
hpc module-spider Rust
hpc queue                  # if queue_command is configured
hpc balance                # if sam_balance_command is configured
hpc statement --account <account> --start 2026-01-01 --end 2026-01-31
hpc hardware               # if hardware or Slurm reference metadata is configured
hpc hardware --source
hpc hardware --path
hpc jobs
hpc submit job.slurm
hpc submit --test-only job.slurm
hpc sacct 123456 --cluster wice
```

Use `--profile` to select a profile and `--dry-run` to print the SSH command
without executing it:

```bash
hpc --profile genius --dry-run run 'cd "$VSC_DATA/Projects/foo" && git status'
```

## Scope

The initial implementation deliberately avoids destructive operations. Cleanup,
job cancellation, and file deletion should remain explicit until the command
surface has enough validation and safeguards.

## Hardware Probing

For clusters where hardware documentation is missing or incomplete, use the
example Slurm probe script at
[examples/job-scripts/hardware-probe.slurm](examples/job-scripts/hardware-probe.slurm).
It records CPU/cache hierarchy, NUMA hints, memory, filesystems, block devices,
memory bandwidth/latency through Intel MLC when available, GPU inventory when
available, and relevant Slurm environment variables from inside a real
allocation.

Adapt site-required `#SBATCH` directives such as `--account`, `--clusters`, or
`--partition`. For meaningful Intel MLC results, probe an entire node: keep
`#SBATCH --exclusive`, and on sites that enforce CPU cgroups add a
partition-specific `#SBATCH --cpus-per-task=<full-node-core-count>`. Also adjust
`#SBATCH --time` if Intel MLC or other probes take longer on the target node.
Then submit with:

```bash
hpc submit hardware-probe.slurm --directory <remote-dir>
```

The script writes a `hardware-probe-<host>-<jobid>` directory in the submission
directory unless `HPC_PROBE_OUTPUT_DIR` is set.

## Codex Skills

The repository also includes reusable Codex skills under [skills](skills). They
generalize the original Genius-specific workflows so agents can work with any
configured `hpc-tools` profile:

- [skills/hpc-filesystem-environment](skills/hpc-filesystem-environment) for
  storage, quota, ownership, module, and conda environment inspection.
- [skills/hpc-deploy-build](skills/hpc-deploy-build) for cloning, building, and
  verifying software on a remote HPC profile.
- [skills/hpc-slurm-jobs](skills/hpc-slurm-jobs) for queue inspection, Slurm job
  scripts, submission, accounting, and output follow-up.

Install them into a Codex skills directory by copying or symlinking the skill
directories, for example:

```bash
mkdir -p ~/.codex/skills
ln -s /home/gjb/Projects/hpc-tools/skills/hpc-filesystem-environment ~/.codex/skills/hpc-filesystem-environment
ln -s /home/gjb/Projects/hpc-tools/skills/hpc-deploy-build ~/.codex/skills/hpc-deploy-build
ln -s /home/gjb/Projects/hpc-tools/skills/hpc-slurm-jobs ~/.codex/skills/hpc-slurm-jobs
```

Each skill assumes the `hpc` CLI is installed and the relevant profile is
configured. Optional commands such as `hpc quota` and `hpc queue` are used only
when the selected profile exposes them.
