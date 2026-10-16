# Quick start

This guide takes one cluster from a working SSH login to a small validated
Slurm job. It starts with read-only inspection and makes the transition to a
real, chargeable submission explicit.

If you only want to verify installation and access, stop after step 5,
**Inspect the cluster**.

## What you need

- Python 3.13 or newer;
- `pipx`;
- working SSH access to a Slurm login node;
- the correct Slurm account and partition for a small test job;
- permission to submit that job.

First verify SSH without hpc-tools:

```bash
ssh example
```

Here and below, replace `example` with your SSH alias. If you do not use an
alias, substitute the appropriate `user@login.example.edu` target.

## 1. Install the CLI

Install the released command in an isolated pipx environment:

```bash
pipx install hpc-tools
pipx ensurepath
hpc --help
```

If the final command is not found, start a new shell after `pipx ensurepath`.
See [Installation and maintenance](installation.md) for local checkouts,
upgrades, the Codex plugin, and MCP.

## 2. Locate hpc-tools state

Run the local command:

```bash
hpc paths
```

It reports the active configuration path, profile-reference and reference-set
locations, packaged templates, and uninstall information. It does not require a
configured profile or contact a cluster.

By default, the configuration is:

```text
~/.config/hpc-tools/config.toml
```

If `XDG_CONFIG_HOME` is set, hpc-tools uses
`$XDG_CONFIG_HOME/hpc-tools/config.toml` instead. An explicit `--config` option
or `HPC_TOOLS_CONFIG` environment variable can override both; the full
precedence is explained in [Profiles select site context](core-concepts.md#profiles-select-site-context).

## 3. Create a minimal profile

Create the configuration directory and edit `config.toml`. For an existing SSH
alias called `example`, use:

```toml
default_profile = "example"

[profiles.example]
ssh_target = "example"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]

[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
```

Without an SSH alias, specify the host and optionally the user:

```toml
default_profile = "example"

[profiles.example]
host = "login.example.edu"
user = "myuser"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]

[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
```

The `login_shell` must end in `-c` so hpc-tools can pass one quoted remote
command. The default is already `bash -l -c`; keeping it explicit makes the
first profile easier to inspect. `ssh_options = ["-x"]` disables X11
forwarding for these non-interactive commands.

The capability table is mandatory. This initial onboarding profile permits
bounded cluster discovery but not job inspection or job lifecycle actions.
Scopes and remote roots are empty until explicitly configured. Add authority
only after reviewing the site rules and choosing the specific operations and
paths you need.

## 4. Preview and verify access

Ask hpc-tools to print, but not execute, the SSH command:

```bash
hpc --profile example --dry-run doctor
```

Inspect the target and SSH options. Then run the check:

```bash
hpc --profile example doctor
```

The report shows the remote hostname, user, working directory, and availability
of core Slurm commands including `sbatch`, `sinfo`, `scontrol`, `sacct`, and
`sacctmgr`.

Some sites restrict `sacctmgr`; that alone is not an SSH failure. Later
discovery may need to combine live commands with site documentation.

## 5. Inspect the cluster

Start with bounded, read-only commands:

```bash
hpc --profile example site-env
hpc --profile example slurm-limits
```

Interpret them as a starting point, not a complete site description:

- `site-env` reports common storage variables, helper tools, and the module
  system visible in the login shell;
- `slurm-limits` combines controller, partition, QoS, association, and array
  information where the site permits access;

To inspect a storage path, first identify a path permitted by site policy and
add the matching C1 list scope and root. For example, if `/project/example-team`
is approved, update the profile policy:

```toml
[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
scopes = ["remote-filesystem.list"]

[profiles.example.capabilities.remote_roots]
list = ["/project/example-team"]
```

Then inspect only a path under that root:

```bash
hpc --profile example storage inspect /project/example-team
```

Inspecting jobs requires C2. After reviewing that additional authority, change
`max_level` to `"job-inspection"` and run:

```bash
hpc --profile example jobs
```

This shows the current user's visible jobs and defaults to all visible clusters
unless a cluster is selected. Keep the list scope and root only if you still
need storage inspection.

If the site is federated, repeat relevant commands with an explicit cluster:

```bash
hpc --profile example slurm-limits --cluster <cluster>
hpc --profile example jobs --cluster <cluster>
```

At this point, installation and read-only access are working. Do not proceed to
a real job until the account, partition, and local site rules are known.

## 6. Prepare a pilot job

Create a local file named `hello.slurm`:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=hpc-tools-hello
#SBATCH --time=00:02:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128M

set -euo pipefail

echo "host=$(hostname)"
echo "job_id=${SLURM_JOB_ID}"
echo "started=$(date --iso-8601=seconds)"
srun --ntasks=1 hostname
```

This job requests one task, one CPU, 128 MB, and two minutes. Those values are
small, but they are not guaranteed to be valid on every site. Adjust them to
the minimum accepted by the chosen partition.

Put the script in a remote working directory using your normal SSH, `scp`, Git,
or file-transfer workflow. For an SSH alias named `example`, one possible
sequence is:

```bash
ssh example 'mkdir -p "$HOME/hpc-tools-quick-start"'
scp hello.slurm example:hpc-tools-quick-start/
```

The directory and script are remote state. hpc-tools does not automatically
delete them after the example.

## 7. Quote the request

Before quoting or validating, review and grant C2 `job.validate`. A configured
quote operation also requires `accounting.read`; retain any other scopes and
roots needed for earlier steps. For example:

```toml
[profiles.example.capabilities]
version = 1
max_level = "job-inspection"
scopes = ["job.validate", "accounting.read"]
```

If the profile and site provide a quote command, estimate the complete request
with an explicit account:

```bash
hpc --profile example quote \
  sbatch -A <account> -p <partition> -N 1 -n 1 -c 1 \
  --mem=128M -t 00:02:00 hello.slurm
```

The `quote` command is site-specific and is hidden when the profile does not
configure a quote helper. A quote is evidence about the request at that time;
it is not permission to use the account and becomes stale if the resource
shape changes. Include an explicit cluster, QoS, or reservation when the site
requires one.

## 8. Validate without submitting

Ask Slurm to test the same request without enqueueing it:

```bash
hpc --profile example submit \
  --directory '$HOME/hpc-tools-quick-start' \
  --account <account> \
  --partition <partition> \
  --test-only \
  hello.slurm
```

This runs `sbatch --test-only`. It can catch many scheduler and policy errors,
but it cannot prove that the program will run successfully, that files exist on
a compute node, or that the request is efficient.

If validation fails, correct the script or resource request and repeat the
quote when the cost-relevant shape changed.

## 9. Submit deliberately

The next command can consume allocation credits. Before running it, review and
explicitly approve C3 lifecycle authority by changing `max_level` to
`"job-lifecycle"`; keep `job.validate` for the pre-submission validation and
any other scopes required by your chosen setup.

Preview the submission SSH command only after enabling C3. Although this is a
dry run, `submit` still requires lifecycle authority:

```bash
hpc --profile example --dry-run submit \
  --directory '$HOME/hpc-tools-quick-start' \
  --account <account> \
  --partition <partition> \
  --validate-first \
  hello.slurm
```

The single quotes prevent the local shell from expanding `$HOME`; the login
shell on the cluster expands it instead. Confirm that the preview contains the
intended host, directory, account, partition, and script.

This command validates the request and, if validation succeeds, immediately
performs the real submission:

```bash
hpc --profile example submit \
  --directory '$HOME/hpc-tools-quick-start' \
  --account <account> \
  --partition <partition> \
  --validate-first \
  hello.slurm
```

There is no interactive pause between validation and submission. Do not run
this command merely to see what it does; use `--dry-run` or `--test-only` for
that.

On success, Slurm prints a job ID. hpc-tools also appends the successful real
submission to its local event database when the `sbatch` output can be parsed.

## 10. Follow the job

Use the reported job ID:

```bash
hpc --profile example jobs
hpc --profile example job <jobid>
hpc --profile example sacct <jobid>
```

`submissions observe` also changes local records. Before using it, review and
add the `submission-record.write` scope to the profile. Then update the local
submission records and view the active workflow:

```bash
hpc --profile example submissions observe
hpc --profile example submissions list
```

`observe` records scheduler state; it does not download job output. Inspect or
transfer the remote output separately, then use the
[Submission tracking](submissions.md) workflow to record collection, analysis,
and closure.

## What success means

After this quick start, you have verified:

- an isolated CLI installation;
- a parsable profile and correct SSH target;
- non-interactive login-shell behavior;
- visibility of basic site and Slurm context;
- Slurm validation for one small job;
- real submission and local lifecycle tracking, if you chose to perform it.

You have not yet completed cluster onboarding. Before larger jobs, discover
storage roles, account and QoS policy, array limits, module stacks, and
representative compute-node hardware, then record stable facts as durable
references.
