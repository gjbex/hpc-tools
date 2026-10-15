# MCP integration

The experimental `hpc-mcp` server exposes selected hpc-tools operations through
the Model Context Protocol (MCP). It is intended for agents that benefit from
structured profile data, reference content, bounded remote inspection, and
guarded writes instead of parsing human-oriented terminal output.

MCP is an additional interface over the same local configuration and command
executors. It does not replace the CLI, create authorization, or make an agent
a trusted cluster operator.

Read [Capability policy](capabilities.md) first when choosing the server's
profile and preset. MCP discovery is deliberately narrower than CLI auditing:
denied operations are absent, not listed with denial annotations.

## Decide whether MCP is useful

Use MCP when an agent needs to:

- enumerate and inspect hpc-tools profiles as structured data;
- consume durable hardware, Slurm, and storage references;
- inspect jobs, limits, modules, storage, or site environment through bounded
  tools;
- preview and perform narrowly defined local writes or remote installs;
- follow the guarded quote, validation, and submission protocol.

Prefer the CLI when a human is actively operating the workflow, raw shell
output is the desired artifact, or the profile is still being bootstrapped.
MCP deliberately does not expose an arbitrary equivalent of `hpc run`.

## Install the server runtime

The `hpc-mcp` entry point is part of the Python package, while its FastMCP
runtime is an optional dependency. For a released pipx installation:

```console
pipx install 'hpc-tools[mcp]'
command -v hpc-mcp
pipx list
```

For development in the repository's locked uv environment:

```console
uv sync --locked --extra mcp
uv run --locked --no-sync hpc-mcp --help
```

The server uses the same Python-package version as the CLI installation. A
Codex plugin checkout and a separate pipx package can therefore drift apart;
update both when tool schemas or workflows change.

`hpc-mcp` is a protocol server, not an interactive command shell. Normally the
MCP client starts it and communicates over standard input/output. Running it in
a terminal may simply wait for a client.

## Configure a client

The hpc-tools Codex plugin points to the repository's `.mcp.json`:

```json
{
  "mcpServers": {
    "hpc-tools": {
      "command": "hpc-mcp",
      "args": []
    }
  }
}
```

The `hpc-mcp` executable must be on the `PATH` inherited by the client, not
only on the path of an unrelated interactive shell. Start a new Codex task
after installing or updating the plugin or server.

Other MCP clients can use the same local command if they support a standard
stdio server. Their configuration, approval UI, filesystem sandbox, and tool
permissions are client-specific. Test discovery and a read-only call before
enabling writes.

The server resolves configuration in the normal hpc-tools order, including
`HPC_TOOLS_CONFIG` and `XDG_CONFIG_HOME`. Environment variables must be present
in the server process. It resolves one profile and snapshots that profile,
policy, configuration path, and submission database at startup. Tool schemas do
not expose overrides for those trusted selections. Restart the server after
editing configuration; a running server intentionally keeps both discovery and
execution on its original snapshot. Use `hpc_paths` to verify which state tree
it sees.

One process never multiplexes authority across profiles. Configure separate
stdio servers when a client needs two centers or two roles:

```json
{
  "mcpServers": {
    "atlas-context": {
      "command": "hpc-mcp",
      "args": ["--profile", "atlas-context", "--preset", "context"]
    },
    "borealis-monitor": {
      "command": "hpc-mcp",
      "args": ["--profile", "borealis-monitor", "--preset", "job-inspect"]
    }
  }
}
```

Restart the affected process after editing its profile, scopes, roots, site
features, or attached reference set. Starting another process is also required
to select a different profile; tools cannot switch profiles in call arguments.

## Select a capability preset

The default `full` preset requests every operation the bound profile permits;
it is not an unrestricted or compatibility mode. The lower presets impose an
additional cumulative ceiling:

| Preset | Maximum operation level |
| --- | --- |
| `context` | local installed context (C0) |
| `discovery` | non-job cluster discovery (C1) |
| `job-inspect` | job observation, quotation, and validation (C2) |
| `job-lifecycle` | submission and cancellation (C3) |

For example:

```console
hpc-mcp --profile example --preset discovery
```

The registered tools and resources are the intersection of the preset,
profile level and scopes, configured site helpers, and deployment mode. Missing
tools are unavailable rather than merely documented as denied. Independent
filesystem scopes still apply at every preset level. `slurm-job` is the
separate delegated deployment mode described below.

## Select where cluster commands run

The server uses the SSH executor by default, matching the existing laptop
workflow. Its profiles require `ssh_target` or `host`:

```console
hpc-mcp
```

If the MCP server itself runs on an approved cluster login node, select direct
execution explicitly:

```console
hpc-mcp --executor local
```

`HPC_TOOLS_EXECUTOR=local` is equivalent when the client configuration cannot
add arguments. For example:

```json
{
  "mcpServers": {
    "hpc-tools": {
      "command": "hpc-mcp",
      "args": ["--executor", "local"]
    }
  }
}
```

For an unattended agent in a Slurm allocation, run the server outside the
agent container, select the restricted surface, and bind a protected delegation
manifest, ledger, parent allocation, and profile:

```console
HPC_TOOLS_PARENT_JOB_ID=60350000 \
hpc-mcp --executor local --preset slurm-job --profile example \
    --config ~/.config/hpc-tools/config.toml \
    --delegation /srv/hpc-tools/delegations/agent-001.toml \
    --ledger /srv/hpc-tools/state/delegations.sqlite3
```

`HPC_TOOLS_MCP_PRESET`, `HPC_TOOLS_MCP_PROFILE`,
`HPC_TOOLS_MCP_DELEGATION`, and `HPC_TOOLS_MCP_LEDGER` provide equivalent
configuration. The parent job ID is deliberately host-provided rather than an
MCP argument. The restricted preset registers only:

```text
hpc_jobs
hpc_job
hpc_job_accounting
hpc_cancel_job
hpc_quote_job
hpc_validate_job
hpc_submit_job
```

It publishes fixed, selected-profile resources:

```text
hpc://runtime
hpc://cluster/hardware
hpc://cluster/slurm
hpc://cluster/storage
```

No bound tools expose `profile`, `config`, or `database` parameters. The
restricted tools additionally hide confirmation and selected submission-path
overrides. Profile
enumeration, raw configuration, arbitrary path inspection, live site discovery,
installation, probe generation, reference mutation, and unrelated local-state
mutation are absent from the server registry.

The local executor runs cluster commands through the selected profile's
`login_shell` on the current host. It does not detect the host, enter an
allocation, or add process and filesystem isolation. Apptainer and explicit
bind mounts must provide that boundary.

Do not place the preceding raw `hpc-mcp` command in the agent container. Use
`hpc-agent-launch` to create the private host server and socket bridge, and
configure the in-container client to start `hpc-mcp-relay`. See
[Run an unattended agent in Apptainer](restricted-agent.md).

`slurm-job` fails closed unless the host supplies a valid delegation manifest
and matching parent job ID; the preset cannot be started as an unscoped
user-wide lifecycle server. It then enforces account/cluster/resource allowlists,
submission and cancellation idempotency, aggregate budgets, and exact job
ownership from its private ledger. The manifest and ledger must remain outside
the agent's writable container mounts. See
[Delegation policy and ledger internals](delegation-development.md).

## Read structured tools

The read-oriented tools are:

| Tool | Result |
| --- | --- |
| `hpc_profiles_list` | The bound profile's safe summary only. |
| `hpc_paths` | Active config, reference, packaged-template, skill, and uninstall paths. |
| `hpc_profile_show` | One resolved profile as structured data. |
| `hpc_hardware_context` | Rendered hardware, Slurm, storage, and status context. |
| `hpc_hardware_sources` | Reference paths, URLs, status URL, and attached set metadata. |
| `hpc_references_list` | The bound profile's effective attached reference set, if any. |
| `hpc_references_show` | Manifest data for that attached reference set only. |
| `hpc_plugins_list` | Installed Python CLI extensions. |
| `hpc_submissions_list` | Active or complete reconstructed records for the selected profile. |
| `hpc_status` | The configured public site-status page; quota, balance, and submissions are separate operations. |
| `hpc_jobs` | Ordinary mode: current user queue. Delegated mode: only ledger-owned active jobs. |
| `hpc_job` | Queue state for one job ID; delegated mode requires ownership. |
| `hpc_job_accounting` | Slurm accounting for one job; delegated mode requires ownership and reconciles terminal state. |
| `hpc_slurm_limits` | Raw and best-effort parsed controller, partition, QoS, and association data. |
| `hpc_module_spider` | Raw and best-effort parsed Lmod search result. |
| `hpc_storage_inspect` | Bounded filesystem information for one remote path. |
| `hpc_files_list` | Non-recursive bounded entries and metadata under a list root. |
| `hpc_files_read` | Bounded UTF-8 or base64 content for one regular file under a read root. |
| `hpc_site_env` | Site variables, module system, and common HPC helper availability. |

Tools that access the cluster execute SSH-backed reads by default. Pass
`dry_run=true` to preview the selected executor command without running it. A
read-only tool can still consume network, login-node, status-page, or scheduler
capacity, so read-only does not mean cost-free or offline.

Remote result objects include `executor` and `execution_command`. The existing
`ssh_command` field remains populated for SSH execution for compatibility and
is `null` for local execution.

Parsed fields are best effort. Preserve `stdout`, `stderr`, return code, and
parse warnings when making a decision. A partial parser result must not hide a
failed remote command or unfamiliar site output.

## Use MCP resources for durable context

Subject to profile policy and site availability, the server publishes fixed
selected-profile resources:

```text
hpc://paths
hpc://profile
hpc://config
hpc://reference-set
hpc://cluster/hardware
hpc://cluster/slurm
hpc://cluster/storage
hpc://submissions/active
hpc://submissions/all
hpc://runtime
```

`hpc://reference-set` is present only when the profile attaches an effective
set. The server publishes no resource templates that accept a different
profile or arbitrary reference-set name. Profile references resolve from the
startup snapshot and installed reference material, not from repository
examples. Missing configured files produce an error rather than an invented
reference.

`hpc://config` requires the selected profile's `config.read.raw` grant and
returns parseable TOML containing only that profile's resolved configuration
and the needed `default_profile` setting, not the complete multi-profile file.
It can still reveal hosts, usernames, email addresses,
paths, site commands, and project context. Do not expose it to an untrusted
client or model.

`hpc://runtime` reports the selected preset, executor, profile, cluster, and
effective capability level/scopes. Ordinary mode does not add protected
deployment data; delegated mode retains its existing public delegation and
ledger summary.

Resources are read-only protocol endpoints. Submission resources are filtered
to the selected profile and reject unlabelled records; reading one does not
observe Slurm again. Reading a reference does not refresh it from a site URL.

## Preview local writes

The following tools can change local state:

- `hpc_references_create`
- `hpc_references_import`
- `hpc_references_attach`
- `hpc_submissions_mark_collected`
- `hpc_submissions_mark_analysed`
- `hpc_submissions_close`
- `hpc_write_probe`
- `hpc_write_container`
- `hpc_files_download`
- `hpc_files_upload`
- `hpc_files_copy`
- `hpc_files_mkdir`
- `hpc_files_remove`
- `hpc_repo_clone`

Without `confirm=true`, they return a preview and do not write. Review the
destination, selected profile, archive, generated content, overwrite flag, and
submission-database event before confirming.

`force=true` can replace existing generated files or reference sets. The
confirmation flag does not back up overwritten state. Prefer versioned outputs
and inspect exact targets first.

File mutations additionally require `dry_run=false`; their default call is a
preview even when `confirm=true`. Downloads name an explicit local target.
Uploads and copies are bounded single-file operations and publish the remote
destination atomically. Removal accepts only a regular file or empty directory
and never follows symlinks or removes a configured root. `hpc_repo_clone`
accepts network sources only and disables hooks and recursive submodules.

Lifecycle tools append events only. They do not copy artifacts, execute an
analysis, validate a path, cancel a job, or reopen a closed record.

## Preview remote mutations

Remote mutation tools are:

- `hpc_cancel_job`
- `hpc_install_probe`
- `hpc_install_container`

They default to `dry_run=true`. Execution requires both:

```text
confirm=true
dry_run=false
```

This two-part gate prevents a confirmed preview from automatically becoming a
remote write. Review the generated execution command, destination, identifiers,
filenames, and `force` behavior. The install tools install scripts or bundles;
they do not submit a probe or container build job.

### Cancel one job

`hpc_cancel_job` accepts one validated numeric Slurm job ID, individual array
task, heterogeneous component, or job step. It deliberately does not expose
the broad user, partition, name, state, or multi-job filters supported by raw
`scancel`. The selected cluster is explicit or comes from the profile's
`default_cluster`.

In full interactive mode execution requires both `confirm=true` and
`dry_run=false`. In delegated mode the host-side policy and ownership ledger
replace interactive confirmation; `dry_run=false` and a fresh
`idempotency_key` are required. A repeated successful key returns the stored
result without calling `scancel` again. Jobs outside the delegation are
rejected before Slurm is contacted.

When `scancel` returns success, the tool records the ledger mutation before it
appends a `cancel_requested` event to each matching active local submission
record. It does not set the record state to
`CANCELLED`: use `hpc_job`, Slurm accounting, or a later submission observation
to confirm scheduler state. A request for an untracked job can succeed without
appending a local event; `recorded_run_ids` makes that distinction visible. If
the scheduler request succeeds but the local event database cannot be updated,
`database_error` reports the history failure without hiding the scheduler result.
If the authoritative lifecycle/audit transaction fails after `scancel`, the
tool attempts a non-audited `uncertain` recovery record. Inspect
`ledger_status`, `ledger_error`, and `ledger_recovery_error`; an uncertain key
cannot call `scancel` again until an operator reconciles it.

A successful cancellation request is not proof of terminal scheduler state.
Call `hpc_job_accounting`; terminal accounting reconciles active ledger
capacity. Array tasks, heterogeneous components, and job steps inherit
ownership from the submitted base job, but broad cancellation filters remain
unavailable.

## Follow the submission evidence chain

MCP exposes real Slurm submission only through:

```text
hpc_quote_job → hpc_validate_job → hpc_submit_job
```

The protocol is stricter than the ordinary CLI:

1. `hpc_quote_job` requires an explicit account and a profile with a configured
   `sam_quote_command`.
2. `hpc_validate_job` executes `sbatch --test-only` for the proposed request.
3. `hpc_submit_job` requires successful quote and validation evidence for the
   same resource shape.
4. Ordinary mode requires `confirm=true` and `dry_run=false`. Delegated mode
   instead requires `dry_run=false`, a fresh `idempotency_key`, matching
   policy, and available budget.
5. Delegated mode records ownership in the private ledger before appending the
   normal local submission event. Failure of the latter is reported through
   `database_error` without hiding scheduler or ledger success.

If `sbatch` returns a job ID but normal ledger/audit persistence fails, the
server conservatively records ownership and consumed budget as `uncertain`.
The response retains `job_id` and `cluster` and reports `ledger_error`. If that
recovery also fails, `ledger_status=unrecorded` and `ledger_recovery_error`
require immediate host-operator reconciliation; retrying the same key remains
blocked by its original reservation when that reservation is still readable.

The resource shape covers:

- profile and account;
- job-script path and remote working directory;
- cluster, partition, QoS, reservation, and dependency;
- array expression;
- nodes, tasks, CPUs, memory, GPUs, and time;
- output, error, job name, environment export, and GPU binding overrides.

If any value changes, quote and validate the new shape. Do not edit evidence
objects or copy them between profiles.

A site without `sam_quote_command` cannot use the MCP submission chain as
currently implemented. Use the human-operated CLI workflow and the site's
authoritative accounting process instead of bypassing the missing quote.

## Understand what evidence does not prove

Evidence objects include a shape hash, timestamp, remote result, and an HMAC
token generated with a secret held by the running server process. The server
rejects failed, dry-run, tampered, shape-mismatched, or executor-mismatched
evidence.

Important limitations remain:

- the timestamp is recorded but currently has no maximum-age check;
- "stale" enforcement means the shape no longer matches, not that a fixed
  number of minutes elapsed;
- the process-local signing secret changes when the server restarts, so old
  evidence will no longer verify in a new process;
- the shape records the job-script path, not a hash of its contents;
- quote and `sbatch --test-only` results can become outdated as scheduler state
  or site policy changes;
- neither result proves that inputs exist, the application runs correctly, or
  outputs are scientifically valid.

Do not modify the script between validation and submission. For costly work,
keep the interval short, inspect the exact script and request, and re-run the
chain after any material change.

## Treat confirmation as a protocol gate

`confirm=true` tells the server that the client is requesting execution. It is
not cryptographic proof of informed human consent. A client could set it
without presenting an approval dialog.

The MCP client and its operator must enforce:

- which users and models may reach the server;
- whether tool calls require human approval;
- which local files and SSH credentials the server inherits;
- which profiles, accounts, clusters, and remote directories are in scope;
- logging, retention, and incident response;
- limits on unattended or repeated actions.

Do not expose this stdio server through a network bridge without adding an
appropriate authentication, authorization, isolation, and audit boundary.

## Use an example agent workflow

A safe review-and-submit conversation should proceed as follows:

1. Call `hpc_profile_show`, `hpc_hardware_context`, and `hpc_slurm_limits` for
   the named profile and cluster.
2. Ask the user which authorized account applies; never infer it from balance
   alone.
3. Review the job script, remote directory, inputs, output paths, and full
   resource shape.
4. Call `hpc_quote_job` and present the returned command and result.
5. Call `hpc_validate_job` with identical parameters and present the result.
6. Call `hpc_submit_job` first as a preview with its safe defaults.
7. After a separate approval, call it with `confirm=true` and
   `dry_run=false`, still using the identical shape and evidence.
8. Verify the parsed job ID and local submission record; do not retry blindly
   if parsing or transport fails.
9. Follow queue, accounting, output, collection, and analysis through the
   normal submission lifecycle.

## Troubleshoot startup and discovery

If the client cannot start the server:

```console
command -v hpc-mcp
pipx list
command -v hpc
hpc paths
```

Check that the optional MCP dependency was installed into the same environment
that supplies `hpc-mcp`, and that the client inherits that executable's path.
Then inspect the client's MCP logs for `ModuleNotFoundError`, configuration
errors, or a missing executable.

If the server starts but tools are absent, verify the client loaded the
hpc-tools MCP entry, selected the intended profile and preset, and that the
profile grants the required level, scopes, roots, and site helper. Restart the
server after configuration edits, and check for version drift between the
plugin checkout and Python package. If the bound profile is unexpected,
compare `HPC_TOOLS_MCP_PROFILE`, `HPC_TOOLS_CONFIG`, `XDG_CONFIG_HOME`, and
`hpc_paths` in the server environment.

Continue with [Troubleshooting](troubleshooting.md) for a layer-by-layer
diagnostic checklist.
