# Configuring cluster profiles

A profile tells `hpc` which cluster context and site-specific helpers to
use. The selected executor determines whether commands reach that context over
SSH or run directly on the current host. A profile may also point to durable
notes about the cluster. It does **not** store SSH credentials, Slurm
authorization, or software environments.

Start with the smallest profile that works. Add site commands and reference
material only after you have verified them on the cluster.

## Locate the configuration

Run:

```console
hpc paths
```

Unless you pass `--config`, `hpc` searches for its configuration in this order:

1. the path in `HPC_TOOLS_CONFIG`;
2. `$XDG_CONFIG_HOME/hpc-tools/config.toml`;
3. `~/.config/hpc-tools/config.toml`.

An explicit command-line option has the highest priority:

```console
hpc --config ./cluster-config.toml --profile example doctor
```

This is useful for testing a candidate configuration without replacing your
normal one.

## Create a minimal profile

If the cluster already has an entry in `~/.ssh/config`, prefer its SSH alias:

```toml
default_profile = "example"

[profiles.example]
ssh_target = "example-login"

[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
```

The corresponding SSH configuration might contain the host name, user name,
identity file, jump host, and other connection details:

```sshconfig
Host example-login
    HostName login.example.edu
    User researcher
    IdentityFile ~/.ssh/id_ed25519
```

Keeping connection policy in SSH configuration avoids duplicating it in every
tool. Verify the alias independently before using `hpc`:

```console
ssh example-login
```

If you do not use an SSH alias, specify the host directly:

```toml
default_profile = "example"

[profiles.example]
host = "login.example.edu"
user = "researcher"

[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
```

Use either `ssh_target` or `host`; do not set both. Authentication remains the
responsibility of SSH. Do not put private keys, passwords, access tokens, or
one-time codes in this file.

## Choose the command executor

The default executor is `ssh`, which preserves the original hpc-tools behavior.
It requires `ssh_target` or `host` and sends each cluster command through SSH.

When `hpc` already runs on an approved cluster login node, use the local
executor explicitly:

```console
hpc --executor local --profile example doctor
```

The equivalent process-level setting is:

```console
export HPC_TOOLS_EXECUTOR=local
```

An explicit `--executor` takes precedence over the environment variable. The
local executor runs the command through `login_shell` on the current host and
does not invoke SSH. A targetless local-only profile is therefore valid:

```toml
default_profile = "login-node"

[profiles.login-node]
login_shell = ["bash", "-l", "-c"]
default_cluster = "compute"

[profiles.login-node.capabilities]
version = 1
max_level = "cluster-discovery"
```

Be precise about what this selection means. It changes command transport only;
it does not detect a login node, create a sandbox, or limit which CLI or MCP
operations are available. Do not treat `--executor local` as the security policy
for an unattended Slurm job.

## Select a profile

Every configuration contains one or more `[profiles.<name>]` tables. Select a
profile explicitly when there could be any doubt:

```console
hpc --profile example doctor
```

`hpc` selects a profile using the following rules:

1. `--profile NAME`, if supplied;
2. the top-level `default_profile` setting;
3. the only configured profile, if exactly one exists.

With multiple profiles and no default, `hpc` refuses to guess. That is
intentional: silently using the wrong cluster can submit work under the wrong
policy or account.

## Configure profile fields and capability policy

Every profile requires a `[profiles.<name>.capabilities]` table with
`version = 1` and one of these ordered `max_level` values:
`profile-context`, `cluster-discovery`, `job-inspection`, or `job-lifecycle`.
Missing, empty, unsupported-version, and otherwise invalid policy is a
configuration error. `scopes` and every remote-root list default to empty, so
omitting them grants nothing.

!!! warning

    The typed policy, strict configuration loading, shared operation registry,
    pure evaluator, and bounded filesystem foundation are implemented. Existing
    commands are not routed through that foundation yet. CLI command
    hiding/denial and MCP discovery filtering are delivered by later capability
    work packages; do not treat the current runtime as an enforcement boundary.

The recognized independent scopes are `accounting.read`, `config.read.raw`,
`delegation-ledger.read`, `job.validate`, `local-state.write`,
`remote-filesystem.list`, `remote-filesystem.read`, `remote-install.write`,
`remote-shell.execute`, `remote-workspace.delete`, `remote-workspace.write`,
and `submission-record.write`.

Remote roots are grouped under `list`, `read`, `write`, `delete`, and
`install`. They must be absolute paths, `~` paths, or paths beginning with a
single environment variable such as `$VSC_DATA`; traversal, glob, command
substitution, shell syntax, trailing separators, and the filesystem root `/`
are rejected. WP2 intersects root declarations by exact string. The WP4
filesystem foundation expands and resolves roots on the selected executor and
uses descriptor-relative traversal below them. Existing commands start using
that foundation in WP5 and WP6.

The available fields fall into four groups.

| Purpose | Fields | Notes |
| --- | --- | --- |
| Execution and connection | `ssh_target`, `host`, `user`, `ssh_options`, `login_shell` | `ssh_target` or `host` is required by the SSH executor but optional for local execution. Prefer an SSH alias for complex connection policy. |
| Workspace and site helpers | `projects_dir`, `quota_command`, `queue_command`, `sam_balance_command`, `sam_statement_command`, `sam_quote_command` | These are site-specific remote paths or commands. Configure only commands you have verified. |
| Cluster references | `hardware_reference`, `hardware_url`, `slurm_reference`, `slurm_url`, `storage_reference`, `storage_url`, `status_url`, `reference_set` | Local files hold durable notes; URLs point to authoritative site sources. A reference set can supply the three local reference files. |
| Defaults and identity | `default_cluster`, `email` | `default_cluster` narrows cluster-aware Slurm queries. `email` can supply a notification address to generated scripts. |
| Capability policy | `capabilities.version`, `capabilities.max_level`, `capabilities.scopes`, `capabilities.remote_roots` | Mandatory, strict per-profile policy. Scopes and roots are additive constraints independent of the maximum level. |

For example:

```toml
default_profile = "example"

[profiles.example]
ssh_target = "example-login"
projects_dir = "$VSC_DATA/projects"
quota_command = "quota -s"
queue_command = "squeue --me"
default_cluster = "example-cluster"
email = "researcher@example.edu"
reference_set = "example-2026"
status_url = "https://status.example.edu/"

[profiles.example.capabilities]
version = 1
max_level = "job-inspection"
scopes = [
    "accounting.read",
    "job.validate",
    "remote-filesystem.list",
    "remote-filesystem.read",
]

[profiles.example.capabilities.remote_roots]
list = ["$VSC_DATA/projects"]
read = ["$VSC_DATA/projects"]
```

Remote environment variables such as `$VSC_DATA` must reach the remote shell
unchanged. When passing such a path as a command-line argument, quote it for
your local shell:

```console
hpc --profile example storage inspect '$VSC_DATA/projects'
```

### Login shell

By default, cluster commands run through:

```toml
login_shell = ["bash", "-l", "-c"]
```

The final element must be `-c`, because `hpc` appends the cluster command. You
may also use a string where appropriate, but change this only when the site
requires a different login-shell invocation. A non-login shell can miss the
module system and other environment initialization supplied by the cluster.

### SSH options

`ssh_options` is a list of extra arguments passed to SSH:

```toml
ssh_options = ["-o", "ConnectTimeout=10"]
```

Prefer persistent options in `~/.ssh/config`, especially jump hosts and
identity selection. Profile-level options are useful when the setting belongs
specifically to this tool configuration. Do not disable host-key checking as a
convenience; it removes an important identity check on the remote system.

## Understand site-feature-driven commands

Some commands are available only when their supporting profile field exists.
For example, `quota` requires `quota_command`, while `balance`, `statement`,
and `quote` require their corresponding accounting helper. `hardware` requires
some cluster reference or source context—hardware, Slurm, storage, or status—
either directly or through a reference set.

Inspect the commands for the selected profile:

```console
hpc --profile example --help
```

A missing command can therefore mean that the profile deliberately does not
configure that site feature. It is not necessarily an installation failure.

The `projects` command is always visible, but needs `projects_dir` to produce a
result. The `clone` command can use `projects_dir` as its default destination,
or you can supply `--directory` explicitly.

## Configure multi-cluster sites

Some Slurm installations federate or expose several clusters through one login
host. `default_cluster` is used by cluster-aware accounting and limit queries,
including `sacct` and `slurm-limits`. Queue queries are different: `hpc jobs`
shows all visible clusters by default unless you pass `--cluster`.

Be explicit when interpreting or comparing results:

```console
hpc --profile example jobs --cluster example-cluster
hpc --profile example sacct 123456 --cluster example-cluster
```

Do not assume that partitions, accounts, QoS rules, or job identifiers have the
same meaning across clusters in a federation.

## Attach durable cluster references

References record the context users need repeatedly: hardware classes, Slurm
limits, and storage roles. Keep personal references under:

```text
~/.config/hpc-tools/profiles/<profile>/
```

Shared, reusable sets belong under:

```text
~/.config/hpc-tools/reference-sets/<name>/
```

A named reference set is usually easier to validate, export, and share than
three unrelated paths. See [Cluster references and sharing](reference-sets.md) for the
creation and attachment workflow.

References should summarize verified facts and link to their sources. They are
not a substitute for current scheduler output: partitions, QoS limits, and
maintenance status can change.

## Validate a profile

First preview the SSH command without connecting:

```console
hpc --config ./cluster-config.toml --profile example --dry-run doctor
```

Then run the actual diagnostic:

```console
hpc --config ./cluster-config.toml --profile example doctor
```

The first command validates configuration selection and command construction.
The second verifies remote identity and the presence of core Slurm tools. A
successful `doctor` does not prove that an account is authorized, a partition
is suitable, or a job will run; those checks belong to
[cluster onboarding](onboarding.md) and [Slurm job validation](slurm-jobs.md).

For machine-readable output, place `--json` before the subcommand:

```console
hpc --profile example --json doctor
```

## Maintain profiles safely

- Give profiles stable, recognizable names rather than names tied to a single
  project.
- Keep site commands small and read-only. A profile is not an appropriate
  place for cleanup, package installation, or submission side effects.
- Test changed commands directly on the cluster before recording them.
- Review references after scheduler-policy, storage, or hardware changes.
- Use separate profiles when login environments or policy boundaries differ
  materially, even if they share a host name.
- Treat `--dry-run` as an executor-command preview, not a universal offline
  mode. For example, commands that read a configured web status page may still
  make a local HTTP request.

Once the profile is sound, follow [Onboarding a new cluster](onboarding.md) to
turn a working SSH connection into a documented, submission-ready setup.
