# Capability model and implementation record

## Purpose

This design gives `hpc` and `hpc-mcp` one vocabulary for progressively granting
authority. WP1--WP10 implement the inventory, typed policy, shared operation
registry, bounded filesystem foundation, core and plugin authorization, CLI
visibility, profile-bound MCP discovery, bounded file operations, and
restricted-agent intersection. WP11 publishes the corresponding user guidance,
templates, and packaging checks. WP12 completes local, fake-endpoint,
installed-distribution, and optional-MCP protocol acceptance. WP1--WP12 are
complete as of 2026-10-15; live-cluster testing remains separately authorized.
It is intended to let a person, site
administrator, or restricted-agent deployment expose only the part of
hpc-tools that they are comfortable authorizing.

The model is deliberately based on **what an operation can affect**, not on
whether it happens to be presented by the CLI, MCP, or a plugin.  The command
and tool names below describe the current built-in surface; external plugins
must declare their own capability metadata before they can be enabled.

Capability policy belongs to each profile in the ordinary, user-editable
hpc-tools configuration.  It expresses the HPC center's rules and the user's
chosen limits for that system.  Immutability is not a requirement: the user
can also access the system directly using their existing credentials.

Slurm accounts, scheduler limits, SSH authorization, filesystem permissions,
confirmation, and the restricted-agent delegation ledger continue to apply.
Protected delegation manifests and ledgers retain their existing deployment
requirements independently of the editable profile policy.

## The ordered capabilities

Capability grants are cumulative.  Granting a higher level grants the
observation and preflight functionality beneath it, subject to the separate
scopes described below.  Filesystem permissions are independent of the job
level: a user may prepare a remote workspace without permission to submit jobs.

```text
C3  job-lifecycle        submit, cancel, and controller actions
|
C2  job-inspection       inspect jobs, obtain quotes, and validate requests
|
C1  cluster-discovery    inspect a cluster without job information
|
C0  profile-context      read installed hpc-tools context only
```

### C0: `profile-context`

This is entirely local, durable context: resolved profile summaries, packaged
paths, installed reference sets, rendered hardware/Slurm/storage references,
and installed CLI plugins.  It must not contact the cluster, a status URL, or
a scheduler.

Current examples are CLI `paths`, `plugins list`, `plugins info`, `hardware`,
and `references list`, `show`, and `validate`; MCP `hpc_profiles_list`,
`hpc_paths`, `hpc_profile_show`, `hpc_hardware_context`,
`hpc_hardware_sources`, `hpc_references_list`, `hpc_references_show`, and
`hpc_plugins_list`; and the profile/reference MCP resources.

Administrators can publish reference-set archives containing hardware, Slurm,
and storage notes, documentation/status URLs, and an optional hardware probe
report.  Users download the archive, run `hpc references import`, and attach it
to their own profile with `hpc references attach`.  Importing and attaching
require C0 plus `local-state.write`; reading the installed material needs only
C0.  This avoids repeating discovery for each user.  Archive download and
updates are currently manual.

Raw configuration needs an explicit per-profile grant.  `hpc://config`
may expose host names, usernames, paths, email addresses, site commands, and
project context.  It needs the `config.read.raw` scope as well as C0.
The raw-config resource returns only the selected profile's resolved
configuration and the selected default-profile name. It does not return the
entire active TOML file, so one profile's grant cannot disclose another
profile's configuration.

### C1: `cluster-discovery`

C1 permits bounded, non-job remote reads.  It includes login and tool checks,
site environment, modules, filesystem and repository inspection, project
directory listing, storage/quota information, hardware/Slurm limits, and
site or account information that does not disclose jobs.  Listing directories
and reading user files are included only when the corresponding filesystem
scopes and path restrictions permit them, as specified below.

Current CLI examples are `doctor`, `site-env`, `projects`, `repo status`,
`storage inspect`, `quota`, `module-spider`, `slurm-limits`, `balance`, and
`statement`.  Their MCP counterparts include `hpc_slurm_limits`,
`hpc_module_spider`, `hpc_storage_inspect`, and `hpc_site_env`.

`status` is a focused C1 read of the configured public site-status page.
Quota, account balance, and submission history are separate operations with
their own scopes and levels.

### C2: `job-inspection`

C2 permits observation of queued, running, cancelled, and completed jobs.  It
does not create, alter, or cancel a job.  This includes queue occupancy,
per-job state, Slurm accounting, and read-only local submission history.  It
also permits quotation and preflight validation of a prospective job without
placing it in the scheduler.

Current CLI examples are `jobs`, `job`, `queue`, `sacct`, and
`submissions list`.  The corresponding MCP operations are `hpc_jobs`,
`hpc_job`, `hpc_job_accounting`, and `hpc_submissions_list`, including the
`hpc://submissions/active` and `hpc://submissions/all` resources.  A
read-only delegated-agent audit also belongs here, but requires the separate
`delegation-ledger.read` scope because its ledger is protected state.

`submissions observe` contacts accounting but appends a local event, so it is
C2 plus `submission-record.write`, not a pure observation operation.

Preflight covers CLI `quote` and `submit --test-only`, and MCP
`hpc_quote_job` and `hpc_validate_job`.  A successful validation result is
evidence for C3 submission, not permission to submit.  Quotation and validation
also require the per-profile `job.validate` grant, so a center can permit
monitoring without preflight.  `submit --validate-first` belongs to C3 because it
validates and then submits.

### C3: `job-lifecycle`

C3 permits effects on scheduler state: non-test `submit`, `cancel`, MCP
`hpc_submit_job`, MCP `hpc_cancel_job`, and any agent controller, requeue, or
cleanup action that submits or cancels jobs.  It does not weaken existing
controls.  In particular, MCP submission remains the evidence chain
`hpc_quote_job` -> `hpc_validate_job` -> `hpc_submit_job`; full mode still
needs confirmation, and delegated mode still needs host-side delegation,
ownership, budget, and idempotency checks.

## Remote directories and user files

Filesystem access is a separate axis of authority.  Permission to inspect or
manage jobs must not automatically expose every file accessible to the SSH
identity, and permission to copy a script must not imply permission to run it.

| Filesystem action | Minimum level and scope | Status in the current framework |
| --- | --- | --- |
| List directory entries and inspect file metadata | C1 + `remote-filesystem.list` | `projects`, `storage inspect`, `files list`, and `hpc_files_list` use the bounded filesystem helper |
| Read file content, including source, job scripts, input files, and logs | C1 + `remote-filesystem.read` | `files read`, `files download`, `hpc_files_read`, and `hpc_files_download` are bounded; arbitrary CLI `run` remains an operator escape hatch |
| Copy/upload a job script or input file, create a directory, or replace a workspace file | C1 + `remote-workspace.write` | `files upload/copy/mkdir` and matching MCP tools are bounded and do not execute uploaded content |
| Clone a repository into an allowed workspace | C1 + `remote-workspace.write` | CLI `clone` and `hpc_repo_clone` validate the destination, reject local sources, and disable hooks and recursive submodules |
| Install packaged probe or container assets | C1 + `remote-install.write` | CLI and MCP installers publish bounded files atomically through the helper |
| Delete workspace files or directories | C1 + `remote-workspace.delete` | `files remove` and `hpc_files_remove` remove one regular file or empty directory; ordinary write permission does not grant deletion |

Reading an output file uses filesystem read authority regardless of whether
its producing job is still running.  Querying Slurm about that job requires C2.
Installing a probe script uses filesystem write authority; submitting that
probe requires C3.  A container build or another executable must also be
classified by its execution effects; copying its build bundle does not
authorize running it.

Each filesystem grant must bind a profile and explicit remote roots, such as
one project directory or one job's output directory.  Listing, content reads,
writes, and deletion may have different roots.  Grants do not implicitly cover
the entire home directory or all shared storage.  Paths must be checked against
those roots, including symlink resolution and destination checks; remote
filesystem permissions remain authoritative.

Bounded tools should accept structured paths and actions rather than arbitrary
shell commands.  Reads need output-size limits; transfers need explicit source
and destination, and writes need a defined overwrite policy.  Recursive
operations must be explicit.  Copying a script creates a file and does not
execute it.  A remote-to-remote copy requires read permission for its source
and write permission for its destination; downloading to a local file also
requires `local-state.write`.  These constraints apply through both SSH and
local executors.

Useful combinations include C1 with read access to a source tree for a code
review, C1 with write access to a staging directory for script preparation, C2
with read access to job logs for monitoring, and C3 with narrowly scoped write
access for submission workflows.  Job-lifecycle authority can also be granted
without general file-content access.

## Effects and sensitive-data scopes

The ordered level says how far into cluster/job activity an operation reaches.
It cannot safely express every independent risk.  An effective grant therefore
has both a maximum capability and explicitly named scopes:

| Scope | Required for | Current examples |
| --- | --- | --- |
| `config.read.raw` | Returning raw local configuration | MCP `hpc://config` |
| `delegation-ledger.read` | Reading protected agent ledger data | `hpc agent audit` |
| `local-state.write` | Creating or replacing local files/reference state | reference-set create/import/attach/detach; local probe/container output; `hpc agent export` |
| `submission-record.write` | Appending/changing local submission records | `submissions observe`, mark-collected, mark-analysed, close; matching MCP tools |
| `remote-filesystem.list` | Listing permitted directories and reading file metadata | `projects`, `storage inspect`, `files list`, `hpc_files_list` |
| `remote-filesystem.read` | Reading permitted remote file content | `files read/download`, `hpc_files_read/download`, copy sources |
| `remote-workspace.write` | Creating or modifying permitted remote workspace data | `clone`, upload/copy/mkdir, matching MCP tools |
| `remote-workspace.delete` | Removing permitted remote workspace data | `files remove`, `hpc_files_remove` |
| `remote-install.write` | Installing generated assets remotely | `install-probe`, `install-hardware-probe`, `install-container`; matching MCP tools |
| `accounting.read` | Viewing account/credit information when granted by the profile | `balance`, `statement`, quotation tools |
| `job.validate` | Quoting and validating prospective jobs when granted by the profile | `quote`, `submit --test-only`, MCP quotation and validation |

These are the scope names accepted by policy format version 1. A scope is additive:
for example, C2 with `job.validate` can validate a prospective job description
but cannot install a probe without the install scope; C3 alone does not permit
raw-config, protected-ledger, or general user-file reads.  Local probe/container generation
requires C0 plus `local-state.write` when writing files.

`hpc run` is intentionally outside this hierarchy.  It is arbitrary remote
shell execution and cannot be made equivalent to a bounded read, preparation,
or lifecycle operation merely by labelling it C3.  It should remain an
explicit operator-only facility (or receive a separate, high-risk
`remote-shell.execute` scope) and must never appear in an MCP capability
preset.

## Interface shape

Use canonical identifiers everywhere:

```text
profile-context | cluster-discovery | job-inspection | job-lifecycle
```

Each profile supplies its maximum capability, granted scopes, and remote
filesystem roots.  Account information, raw configuration, and preflight
permission are explicit grants in that profile, allowing different centers to
make different choices.  An absent scope is denied; warnings are not a
substitute for a required grant.  A CLI invocation may select a lower level,
never raise the configured ceiling.  The user may edit the configuration to
change the policy.

The capability table is mandatory for every profile. Missing, empty, invalid,
or unknown-version policy is a configuration error; there is no implicit
unrestricted or compatibility default. All shipped profiles, examples, and
documentation fragments must use the same accepted schema as the parser.

For example, a site could give a monitoring or CI validation profile C2 and a
human-operated submission profile C3, with different filesystem scopes and
roots for each.  The effective authority is the intersection of the selected
profile policy, requested lower capability, any server/delegation ceiling,
and existing Slurm/SSH authorization.  Restrictions combine by intersection;
a more permissive preset cannot override a profile restriction.

Configuration shape implemented by WP2:

```toml
[profiles.example.capabilities]
version = 1
max_level = "job-inspection"
scopes = ["remote-filesystem.list", "remote-filesystem.read", "job.validate"]

[profiles.example.capabilities.remote_roots]
list = ["/project/my-group"]
read = ["/project/my-group"]
write = []
delete = []
install = []
```

This profile permits C2 observation and preflight plus file reads within one
project, but omits account-credit information, workspace writes, and job
submission.  Another profile may grant a different level and set of scopes.
An operation requiring several scopes needs all of them: for example, a
credit quotation needs `job.validate` and `accounting.read`.

### CLI visibility

Hide disallowed commands from help by default. Offer
`--show-disallowed` mode that includes them, marks them unavailable, and
explains the missing level or scope.  Showing a command never enables it.
Both modes use the same execution checks and reject a direct invocation of a
disallowed operation before its effects occur.  Commands with mixed modes
must be checked by arguments: a C2 profile may expose `submit --test-only`
while denying an actual submission.

### MCP discovery

Bind each server instance to one selected profile (explicitly supplied or
resolved from the configured default) so discovery reflects that profile's
policy.  Separate instances can expose different profiles.  Tools may not
switch to an unauthorized profile or alternate configuration through call
arguments.

Register only allowed tools, resources, and resource templates.  There is no
MCP equivalent of `--show-disallowed`; denied operations must not be
discoverable or callable.  Recheck authorization at execution as well as
registration.  Initially, load policy at server startup and require a restart
after configuration changes so discovery and execution use the same policy
snapshot.

For MCP, add named presets that expose only operations allowed by that
effective grant:

| Preset | Exposes | Intended use |
| --- | --- | --- |
| `context` | C0, no raw config by default | Safe local cluster context for an assistant |
| `discovery` | C0--C1 | Bounded site discovery without job visibility |
| `job-inspect` | C0--C2, subject to granted scopes | Job monitoring, accounting, quotation, and validation |
| `job-lifecycle` | C0--C3, subject to granted scopes | Reviewed human or delegated lifecycle workflow |

Every preset is subject to the same filesystem grants.  A `discovery` server
can permit file staging without job access, while a `job-lifecycle` server can
omit general file reads and writes.

The `full` preset requests every operation allowed by the selected profile; it
is a convenience selector, not a compatibility mode or a policy bypass. Every
profile must contain a valid capability block, and every MCP preset binds one
profile. The current `slurm-job` preset is a *deployment mode*, not merely a capability:
it binds one profile and adds host-side delegation and ledger enforcement.  It
should continue to be layered on top of the C2--C3 operations it currently
offers rather than be replaced by a plain `job-lifecycle` preset.

## Implementation history and remaining acceptance

The detailed, dependency-ordered work packages and acceptance criteria are in
the [capability implementation plan](implementation-plan.md).

Because the project has not yet been rolled out, the implementation may replace
current commands and schemas rather than carry compatibility branches. Any
such change must update code, operation metadata, CLI/MCP schemas,
documentation, examples, and tests in the same work package.

The delivered implementation follows these stages:

1. Introduce one internal operation registry. Each CLI command, MCP tool,
   resource, and plugin operation declares its minimum capability, required
   scopes, effects (`local-read`, `remote-read`, `local-write`,
   `remote-write`, `scheduler-write`), profile binding requirement, and any
   path restrictions and confirmation/evidence/delegation rules.  Classify
   argument-dependent effects, especially `submit --test-only` versus actual
   submission.  Derive CLI visibility, MCP tool registration, and MCP resource
   registration from that registry; do not
   maintain parallel hand-written lists.
2. Classify the existing built-ins and split compound operations such as
   `status` before turning the registry into a policy gate. Command names,
   arguments, and result shapes may change where that produces a clearer or
   safer model; update implementation, schemas, documentation, examples, and
   tests together.
3. Add per-profile capability, scope, and filesystem-root configuration in the
   existing user-editable config file.  Keep existing host-side delegation
   controls for restricted agents; ordinary profile policy needs no immutable
   administrator-owned configuration.
4. Add CLI capability narrowing, default hidden commands, and the optional
   `--show-disallowed` help mode.  Bind MCP instances to profiles and register
   only allowed tools/resources. Test `full` as the complete policy-filtered
   profile surface and `slurm-job` as the narrower delegated deployment mode;
   neither may bypass profile restrictions.
5. Require third-party CLI plugins to register metadata.  An undeclared plugin
   must not be exposed through a capability-limited CLI or MCP server.
6. Add bounded CLI/MCP directory listing, file reads/transfers, and workspace
   writes with profile/root binding and overwrite rules.  Apply the same
   filesystem scopes to existing inspection, clone, and install commands.

## Acceptance criteria

These criteria passed through the WP12 local and installed-distribution
acceptance described in the
[WP12 acceptance record](work-packages/wp12-acceptance.md). They do not claim a
live cluster install or Slurm submission.

- A single registry provides the authoritative classification for all built-in
  CLI commands, MCP tools, and MCP resources.
- Tests prove monotonicity: a lower preset cannot expose an operation requiring
  a higher capability or an absent scope.
- Tests prove that C0 performs no remote execution, C1 invokes no job-query or
  job-preflight commands, and C2 does not submit or cancel jobs.  Local/remote
  file writes and submission-record updates require their explicit scopes at
  every level.
- Tests cover the evidence-gated C3 MCP submission chain, delegated ownership,
  confirmation, and scope denial separately from capability denial.
- Filesystem tests cover profile and root confinement, symlink escapes,
  bounded reads, overwrite rules, and independent list/read/write/delete
  grants.  C3 without file-read scope cannot retrieve user files, and C1 with
  workspace-write scope cannot launch a copied script.
- `hpc run` and undeclared plugins are absent from every capability-limited MCP
  registry.
- CLI help, documentation, and denial responses state the missing capability
  or scope without leaking raw configuration or protected ledger details.
  MCP discovery lists only permitted operations.
- CLI tests cover default hiding, optional display of unavailable commands,
  and identical execution denial in both modes.
- Two profiles with different grants yield different CLI/MCP surfaces.  MCP
  discovery omits denied tools and resources, and call arguments cannot switch
  the server to a more permissive profile or configuration.
- Tests cover per-profile account, raw-config, and preflight grants, including
  that raw configuration cannot disclose unrelated profiles.
- Missing, empty, or invalid capability blocks are rejected. All shipped
  examples and documented configuration fragments contain valid policy, and
  `full` and `slurm-job` always respect it.

## Resolved policy decisions

- Policy is per profile: centers can choose their capability ceiling,
  sensitive-data/preflight grants, and filesystem access independently.
- The CLI supports both visibility modes and hides unavailable commands by
  default; visibility never changes permission to execute.
- MCP exposes only allowed tools and resources for its selected profile.
- Policy lives in the ordinary editable configuration.  Immutability is not
  required; existing restricted-agent delegation protection remains in place.

These settle the previously listed policy decisions. Policy format version 1,
including its configuration keys, level names, scopes, and root categories, is
implemented and documented. The project has not yet promised backward
compatibility for that schema.
