# Getting started

This path installs the human-operated CLI, creates one minimal cluster profile,
and performs read-only checks. It does not install the Codex plugin, start the
MCP server, or submit a Slurm job.

## Prerequisites

You need:

- Python 3.10 or newer;
- `pipx` for an isolated CLI installation;
- working SSH access to a Slurm login node;
- the SSH target or the cluster hostname and username.

Verify direct SSH access before configuring hpc-tools. If an SSH alias already
handles the username, hostname, jump host, and credentials, use that alias as
the profile's `ssh_target`.

## Install the CLI

For normal use, install the released Python package with `pipx`:

```bash
pipx install hpc-tools
pipx ensurepath
hpc --help
```

Installing the Codex plugin is a separate operation and does not provide the
`hpc` executable.

## Locate the configuration

Run:

```bash
hpc paths
```

The default configuration file is
`$XDG_CONFIG_HOME/hpc-tools/config.toml`. When `XDG_CONFIG_HOME` is not set,
hpc-tools uses `~/.config/hpc-tools/config.toml`.

## Create a profile

For an existing SSH alias called `example`, start with:

```toml
default_profile = "example"

[profiles.example]
ssh_target = "example"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
```

Without an SSH alias, configure the user and host explicitly:

```toml
default_profile = "example"

[profiles.example]
user = "myuser"
host = "login.example.edu"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
```

`ssh_options = ["-x"]` disables X11 forwarding for the non-interactive
commands used by hpc-tools.

## Preview and verify access

First inspect the SSH command without running it:

```bash
hpc --profile example --dry-run doctor
```

Then perform the remote check:

```bash
hpc --profile example doctor
```

The report identifies the remote host and user and checks for core Slurm tools
such as `sbatch`, `sinfo`, `scontrol`, `sacct`, and `sacctmgr`. Some tools may
be unavailable or restricted by site policy; that does not necessarily mean
SSH access is broken.

## Inspect the site

Continue with bounded, read-only discovery:

```bash
hpc --profile example site-env
hpc --profile example slurm-limits
hpc --profile example storage inspect .
hpc --profile example jobs
```

These commands help establish the cluster's Slurm, storage, and software
environment before making resource or installation choices.

## Next steps

- Onboard a new cluster with the `hpc-cluster-onboarding` Codex skill if the
  Codex plugin is installed.
- Create durable cluster context before relying on undocumented site
  assumptions; see [Cluster reference sets](reference-sets.md).
- Before a real Slurm submission, identify the correct account, quote the full
  workload where supported, and use `hpc submit --validate-first`.
- After submission, use [Submission tracking](submissions.md) to retain the
  workflow history locally.
