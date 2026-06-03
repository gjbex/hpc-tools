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

Example:

```toml
default_profile = "genius"

[profiles.genius]
ssh_target = "genius"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
projects_dir = "$VSC_DATA/Projects"
quota_command = "myquota"
queue_command = "slurm_queuestate"
default_cluster = "wice"
```

`ssh_target` is passed directly to `ssh`, so it can be a configured SSH alias
from `~/.ssh/config`. For example, if `ssh genius` already expands to the right
host, username, agent forwarding, and credentials, use `ssh_target = "genius"`.
`ssh_options` is passed before the target; `["-x"]` disables X11 forwarding for
non-interactive commands.

Profiles can also use explicit host fields:

```toml
[profiles.some-cluster]
host = "login.somewhere"
user = "myuser"
```

`projects_dir` is interpreted by the remote shell. Values such as
`$VSC_DATA/Projects` are intentionally not expanded locally.

## Commands

```bash
hpc run 'hostname'
hpc quota
hpc projects
hpc clone https://github.com/org/repo.git --branch main
hpc module-spider Rust
hpc queue
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
