# Capability policy

Every hpc-tools profile declares the operations it may expose. The same policy
controls CLI help, CLI execution, MCP discovery, and MCP invocation. It is an
application safety boundary: SSH credentials, Unix permissions, Slurm policy,
confirmation, evidence, and restricted-agent delegation checks still apply.

Policy is ordinary user-editable configuration. This lets each HPC center and
each user choose an appropriate surface without pretending that hpc-tools can
prevent the user from using SSH or another client directly.

## Understand the four levels

Levels are cumulative, but independent scopes and filesystem roots can still
deny an operation at any level.

| Level | Name | Authority |
| --- | --- | --- |
| C0 | `profile-context` | Read installed profiles, references, paths, and plugin metadata without contacting the cluster. |
| C1 | `cluster-discovery` | Perform bounded non-job cluster discovery and permitted remote file operations. |
| C2 | `job-inspection` | Inspect jobs and accounting, and optionally quote or validate prospective jobs. |
| C3 | `job-lifecycle` | Submit, cancel, and perform authorized controller lifecycle actions. |

Filesystem authority is a separate axis. A C1 staging profile can write a job
script without submitting it; a C3 lifecycle profile can submit jobs without
having general access to user file contents.

`hpc run` is not C3. It is arbitrary remote shell execution and requires the
separate operator scope `remote-shell.execute`. It is never exposed by an MCP
capability preset.

## Configure a mandatory policy

Every profile needs a non-empty capability table:

```toml
[profiles.example]
ssh_target = "example-login"

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
list = ["/project/example-team"]
read = ["/project/example-team/logs"]
write = []
delete = []
install = []
```

Missing or empty policy, an unsupported version, unknown keys, unknown or
duplicate scopes, and invalid roots are configuration errors. Omitted scopes
and root lists grant nothing.

The independent scopes are:

| Scope | Additional authority |
| --- | --- |
| `config.read.raw` | Return the selected profile's raw resolved configuration through MCP. |
| `delegation-ledger.read` | Read protected restricted-agent audit state. |
| `local-state.write` | Create or update local references, generated assets, or exports. |
| `submission-record.write` | Add or change local submission-history events outside intrinsic submission logging. |
| `remote-filesystem.list` | List entries and inspect metadata below permitted list roots. |
| `remote-filesystem.read` | Read or download regular files below permitted read roots. |
| `remote-workspace.write` | Upload, copy, clone, create, or replace workspace content below write roots. |
| `remote-workspace.delete` | Remove one regular file or empty directory below delete roots. |
| `remote-install.write` | Install packaged probe or container assets below install roots. |
| `accounting.read` | Read account balances, statements, and credit information. |
| `job.validate` | Quote and perform test-only validation of prospective jobs. |
| `remote-shell.execute` | Use the operator-only arbitrary `hpc run` escape hatch. |

Remote roots are grouped as `list`, `read`, `write`, `delete`, and `install`.
They accept absolute paths, `~` paths, or a path beginning with one remote
environment variable such as `$PROJECT`. They reject the filesystem root,
traversal, globs, command substitution, and shell syntax. Each action needs its
matching scope and root; write permission does not imply read or deletion.

The helper resolves roots on the selected executor, rejects symlinks and
special files for bounded content operations, and applies fixed size and entry
limits. These grants constrain hpc-tools operations. They do not sandbox code
inside a submitted job or arbitrary external programs.

## Inspect CLI authority

Inspect the execution policy and the commands visible for one profile:

```console
hpc --profile example capabilities
hpc --profile example --help
```

Denied leaves and empty command groups are hidden by default. To audit the
complete command grammar and see safe denial reasons:

```console
hpc --profile example --show-disallowed --help
```

`--capability LEVEL` applies a lower display ceiling. It is useful when
reviewing how a narrower role would look, but neither it nor
`--show-disallowed` changes execution authority. Direct invocation is checked
again before effects and a policy denial exits with status 2. Site-feature
requirements, such as a configured quote command, are applied in addition to
capability policy.

## Bind MCP to one profile

Each `hpc-mcp` process snapshots one selected profile and registers only the
tools and fixed resources allowed by the intersection of:

- the profile's level, scopes, roots, and configured site features;
- the requested MCP preset; and
- any restricted-agent delegation ceiling.

For example:

```console
hpc-mcp --profile example --preset job-inspect
```

Run separate server processes when clients need different profiles. Bound tool
schemas have no profile, configuration, or submission-database override. The
`full` preset means every operation allowed by the bound profile, not an
unrestricted surface. MCP has no show-disallowed mode, and guessed names or
URIs cannot invoke operations that were not registered.

Restart the server after changing configuration or policy. A running process
intentionally continues to use its startup snapshot so discovery and execution
cannot disagree.

The `slurm-job` preset is a restricted deployment mode rather than another
cumulative level. It exposes a small lifecycle surface and intersects current
profile policy with captured controller authority and host-side delegation.

## Start from role templates

[`examples/capability-profiles.toml`](https://github.com/gjbex/hpc-tools/blob/main/examples/capability-profiles.toml)
contains four fictional templates across two centers:

| Template | Intended role | Explicit additions |
| --- | --- | --- |
| `atlas-context` | C0 installed references | No scopes or remote roots. |
| `atlas-staging` | C1 inspection and file staging | List/read/write scopes with different roots. |
| `borealis-monitor` | C2 monitoring and preflight | Accounting, validation, and log-read scope. |
| `borealis-lifecycle` | C3 reviewed lifecycle | Accounting, validation, staging, and submission-record scope; no general read/delete/install grant. |

Copy one profile rather than treating the file as a deployable center
configuration. Replace all fictional aliases, paths, commands, URLs, and
reference names with values approved by the real site.

## Keep references separate from policy

An administrator can publish a reference-set archive with hardware, Slurm,
storage, probe, and documentation context. A user can download, inspect,
import, and attach that archive instead of rediscovering stable facts.

That archive is knowledge, not authority. Importing or attaching it does not
create a profile capability block, change SSH configuration, grant filesystem
roots, install credentials, or authorize a job. The user or site still defines
policy separately in `config.toml`.

See [Cluster references and sharing](reference-sets.md) for the publishing
workflow and [Configuring cluster profiles](configuration.md) for the complete
schema.

## Extend the policy safely

Python CLI plugins use the `hpc_tools.plugins` entry-point group and must
declare versioned `OperationDescriptor` metadata for every leaf command. The
descriptor identifies the minimum level, required scopes, effects, profile
binding, site features, and path requirements. Missing, incompatible, or
mismatched metadata rejects the plugin command instead of exposing an
unclassified operation.

This Python extension API is distinct from the Codex plugin, which distributes
workflow skills and MCP startup metadata. Installing the Codex plugin neither
installs a Python CLI extension nor grants cluster authority. See
[CLI plugin system](plugins.md) for the contract.
