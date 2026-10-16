# Delegation policy and ledger internals

This page is for maintainers and operators developing the restricted
non-interactive MCP server. It is not part of the normal user workflow.

## Responsibility boundary

Slurm remains authoritative for Unix identity, account associations,
partitions, QoS, reservations, scheduler resource limits, placement, and
cluster-wide accounting. A delegation can only narrow what Slurm permits. It
cannot create a subpartition, grant access to an account, or make a request
valid that Slurm would reject.

The MCP delegation ledger adds controls that Slurm does not provide for one
unattended agent invocation:

- ownership of the exact job IDs submitted through that delegation;
- idempotency for submission retries;
- delegation expiry and operator revocation;
- per-job ceilings and optional delegation-scoped aggregate budgets;
- bounded parent-controller requeue and startup reconciliation;
- terminal cleanup scoped to exact delegation ownership;
- an append-only authorization audit trail.

These controls protect the MCP-mediated path. They do not constrain other
processes running as the same Unix user. The agent container must therefore
lack Slurm commands, SSH credentials, and write access to the manifest and
ledger.

## Delegation manifest

The operator starts the host-side server with a TOML manifest selected through
`hpc-mcp --delegation PATH` or `HPC_TOOLS_MCP_DELEGATION`, and can bind the
profile configuration explicitly with `--config PATH`. The manifest must be
owned by the server user and must not be group- or world-writable. The server
also requires `HPC_TOOLS_PARENT_JOB_ID`; it must match `parent_job_id`.
The ledger path is selected by `--ledger`, `HPC_TOOLS_MCP_LEDGER`, or the
default `~/.config/hpc-tools/delegations.sqlite3`.

Example format version 2:

```toml
format_version = 2
id = "agent-20260826-001"
issuer = "operator@example.org"
profile = "genius"
parent_job_id = "60350000"
issued_at = "2026-08-26T09:00:00Z"
expires_at = "2026-08-26T17:00:00Z"

[allowed]
accounts = ["project123"]
clusters = ["wice"]
partitions = ["batch"]
qos = ["normal"]
reservations = []
containers = ["/srv/agent-images/worker.sif"]
script_sha256 = []
roots = ["/scratch/project123/delegations/agent-20260826-001"]

[per_job_limits]
nodes = 1
tasks = 1
cpus_per_task = 8
wall_seconds = 14400
array_tasks = 100
array_concurrency = 20
memory_mib = 262144

[budget]
max_submissions = 20
max_active_jobs = 4
max_total_nodes = 20
max_total_wall_seconds = 172800

[filesystem]
state_root = "/scratch/project123/delegations/agent-20260826-001-private"
work_root = "/scratch/project123/delegations/agent-20260826-001/work"
output_root = "/scratch/project123/delegations/agent-20260826-001/output"
input_roots = ["/project/project123/common-inputs"]
apptainer_path = "/usr/bin/apptainer"
max_file_blocks = 2097152
max_open_files = 1024

[lifecycle]
on_cancel = "cancel"
on_timeout = "requeue-or-cancel"
on_failure = "cancel"
on_normal_exit_with_active_jobs = "cancel"
max_requeues = 3
warning_seconds = 600
```

Accounts and clusters are mandatory non-empty allowlists. A delegation that
submits restricted container jobs also needs at least one approved container.
Unknown manifest, allowlist, per-job-limit, budget, filesystem, and lifecycle keys are
rejected. This is intentional: a misspelled ceiling must not silently become
an unenforced operator policy.
Optional scheduler-field allowlists may be empty; if a request supplies that
field, its value must occur in the corresponding allowlist. An empty
`script_sha256` list permits any regular, non-symlink payload below `work_root`;
a non-empty list restricts payload snapshots to those exact digests.
Allowed roots must be absolute normalized paths. Environment-variable,
home-directory, relative, and parent-directory forms are rejected.

The optional `[filesystem]` table becomes mandatory when the delegation creates
new jobs through the restricted container boundary. Its state, work, output,
and input paths must be absolute, non-overlapping, and free of symlinks. The
state root and `apptainer_path` are host-private and omitted from the public MCP
runtime summary. See [Run an unattended agent in Apptainer](restricted-agent.md)
for bind modes, generated wrappers, and output semantics.
`allowed.roots` must authorize the selected `work_root`; it does not authorize
state or output paths for agent selection.

Resource values in the manifest are positive integers. Slurm submission values
covered by a delegation must use the restricted parser: numeric counts, one
numeric array index or range, and wall time in `[days-]HH:MM:SS` form. This
deliberately rejects valid but ambiguous Slurm syntax until it can be accounted
for exactly.

The manifest's `issuer` is audit metadata, not a cryptographic signature.
Authority comes from the operator selecting a protected host-side file when
starting the server. If manifests must cross an untrusted distribution
boundary, signature verification must be added before treating `issuer` as an
authenticated identity.

The lifecycle table is optional and defaults to the values in the example.
Only the issuer can select `leave-running`, independently for cancellation,
failure, or normal exit with active jobs. A wall-time warning normally requests
a bounded same-job-ID requeue; if it fails or the limit is exhausted, cleanup
cancels active jobs. `warning_seconds` must match the advance signal in the
deployed Slurm template. It is descriptive policy input rather than permission
for the agent to signal or requeue anything.

## Reservation and budget semantics

A real restricted submission requires an `idempotency_key`. In one
`BEGIN IMMEDIATE` transaction the ledger:

1. verifies that the registered manifest is unchanged, unexpired, and not
   revoked;
2. requires the controller to be running with startup reconciliation complete;
3. rejects reuse of a key for a different shape;
4. checks per-job policy and remaining aggregate budget;
5. creates a `reserved` operation.

The scheduler is called only after that transaction commits. A successful
submission changes the operation to `submitted` and records its Slurm job ID
and cluster as delegation ownership before the ordinary submission-history
event is written. Repeating a completed key returns the recorded job rather
than calling `sbatch` again.

A definite `sbatch` failure changes the reservation to `failed` and releases
its active and resource reservation. If Slurm appears to accept the request but
the job ID cannot be parsed, the operation becomes `uncertain`; its budget
remains consumed until an operator reconciles it. Terminal reconciliation
changes `submitted` to `terminal`, releasing active-job capacity while
retaining cumulative submission and resource consumption.

If Slurm returns a job ID but the normal ownership/audit transaction fails, the
server attempts a smaller recovery transaction. It records the job ID and
ownership as `uncertain` without requiring another audit insert. This is a
deliberate fail-closed trade-off: the accepted job remains visible to lifecycle
authorization and consumes budget, while the missing audit event is reported
as a persistence error. Cancellation uses the same pattern: an accepted
`scancel` whose result/audit transaction fails becomes `uncertain`, so replay
cannot invoke `scancel` again blindly.

`max_submissions` counts accepted reservations immediately so concurrent
requests cannot overrun the cap. A definite submission failure refunds it;
successful, uncertain, terminal, and cancelled jobs remain cumulative.
`max_active_jobs` counts `reserved`, `submitted`, and
`uncertain` operations. `max_total_RESOURCE` is cumulative over reserved,
submitted, uncertain, and terminal operations; failed reservations are
excluded. Array resource requests are multiplied by the number of array
elements, so an array cannot consume a one-job node budget while launching many
equivalent elements. These MCP budgets are optional delegation ceilings, not
Slurm account balances.

## Ledger schema

The authorization ledger is separate from `submissions.sqlite3`. The latter
is agent-readable lifecycle history and must not be used as authorization
state. Ledger schema version 3 uses `PRAGMA user_version = 3` and these tables:

| Table | Purpose |
| --- | --- |
| `delegations` | Manifest digest, issuer, profile, parent allocation, expiry, and revocation state. |
| `submission_operations` | Idempotency key, request digest, reservation state, accounted resources, and resulting job identity. |
| `job_ownership` | Exact delegation/base-job/cluster ownership used by lifecycle authorization; a job/cluster pair is globally unique in one ledger. |
| `lifecycle_operations` | Idempotent cancellation reservations and scheduler results. |
| `delegation_audit` | Append-only accepted and rejected mutation decisions. |
| `controller_attempts` | Same-parent-job generations, restart counts, drain/reconciliation state, and terminal reasons. |
| `controller_cleanup` | The separately accounted dependent cleanup job and its last result. |

The database uses a rollback journal, `synchronous=FULL`, foreign keys, a
five-second busy timeout, and mode `0600`. As with the submission database,
this does not make arbitrary network filesystems safe for SQLite. Use
node-local or otherwise verified storage, and do not use one file as a
distributed multi-node database.

There is no schema migration because this authorization format has not entered
production and existing delegation data was explicitly out of scope. A
non-version-3 ledger is rejected rather than modified implicitly.

The first accepted controller start adds one `controller_authority` audit row.
It contains the complete C3 profile-policy snapshot, its digest, and the path
and digest of the configuration that supplied it. Subsequent starts reuse that
row: a changed profile cannot replace or widen the captured ceiling. The MCP
server intersects the current profile with this capture for new work, while
host-only requeue and cleanup continue under the capture so already accepted
ownership obligations remain enforceable after profile narrowing.

The Python API exposes `DelegationLedger.revoke` for an operator control
plane and `DelegationLedger.reconcile_job` for scheduler reconciliation.
Neither operation is exposed to the restricted agent MCP surface.

## Parent lifecycle enforcement

`hpc-agent-launch` registers a small host-side cleanup job with an
`afterany:<parent-job-id>` dependency before starting the agent. The cleanup
job and its `hpc-agent-reap` process are not mounted into the container and do
not consume the delegation's compute-job budget. On `SIGUSR1`, the launcher
atomically enters `draining`, stops the agent, waits within the warning window
for any earlier reserved scheduler submission to settle, and requests
`scontrol requeue` for the exact manifest-bound parent job. Slurm's restart
counter selects a new controller generation under the same parent ID.

The restarted MCP server exposes the new generation but blocks submissions
until `hpc_jobs` has reconciled every active ledger-owned job. Prepared quote
and validation evidence includes the controller generation, so evidence from a
previous attempt is stale. When the parent finally terminates, the cleanup job
uses `squeue` and `sacct` to classify the terminal event and applies only the
issuer's policy to exact `job_ownership` rows. It never selects jobs by Unix
user, Slurm account, partition, name, or wildcard.

This dependent-job implementation is user-deployable but may wait in the
queue; it cannot guarantee immediate cleanup. A persistent broker remains the
stronger future option for sites requiring a tighter cleanup latency bound.

## Operator audit and recovery

Treat any `ledger_status` other than `submitted`, `succeeded`, or `failed` as
an operator event. Responses include `ledger_error` for the failed normal
transaction and `ledger_recovery_error` if even the conservative recovery
transaction could not be written.

For an `uncertain` submission, use the returned job ID and cluster to query
Slurm directly from the host namespace. The job is already ledger-owned and its
budget remains reserved. Calling delegated job accounting is safe; a terminal
Slurm state reconciles either `submitted` or `uncertain` to `terminal`. If the
job never existed, the operator must make an explicit control-plane decision
before releasing or correcting the reservation; the restricted agent has no
such operation.

For an `uncertain` cancellation, inspect `squeue`/`sacct` from the host and then
call `DelegationLedger.record_lifecycle_result` through an operator-controlled
recovery procedure. That method can finalize an `uncertain` operation once the
scheduler outcome is known. Do not give this recovery capability to the agent.

If `controller_cleanup.status` is `failed`, inspect the registered cleanup
job's output and error files, then compare every row returned by
`DelegationLedger.owned_jobs_for_cleanup` with `squeue`/`sacct`. A recorded
`failed` cancellation is retried only after the reaper observes that the job is
still active, using a new audited operation key, and stops after three attempts.
An `uncertain` cancellation is not replayed. Resolve its scheduler outcome
through the operator API before requeuing the exact registered cleanup job or
starting a replacement control-plane procedure. Never repair cleanup by
cancelling a user, account, partition, or name pattern.

If `ledger_status` is `unrecorded`, retain the response containing the Slurm job
ID or cancellation target, stop further mutations for that delegation, and
repair or restore the ledger before reconciling against Slurm. The original
reservation normally still blocks replay. A crash after Slurm accepts a request
but before any local durable write is the unavoidable two-system transaction
gap: SQLite and Slurm do not provide a shared atomic commit. Sites requiring
automatic recovery across that gap need a durable broker that periodically
reconciles reserved operations with scheduler records and submission metadata.

The authorization audit is append-only through the server API, but SQLite does
not provide tamper-evident logging. Copy or stream audit records to protected,
independently retained storage if forensic non-repudiation is required.

For normal diagnosis, use the supported read-only joined view rather than
querying tables directly:

```console
hpc agent audit --ledger /protected/delegations.sqlite3 \
    --delegation-id delegate-1
hpc agent export --ledger /protected/delegations.sqlite3 \
    --delegation-id delegate-1 --output /protected/delegate-1-audit.json
```

The report combines the authorization ledger with the local submission event
database and the protected controller/output artifact paths. It does not make
the SQLite audit tamper-evident and it does not query live Slurm state; compare
the resulting job IDs with `squeue` or `sacct` during incident response.

## Restricted lifecycle authorization

In a configured `slurm-job` server, `hpc_jobs` obtains active base job IDs
from `job_ownership` and passes only those IDs to `squeue`; it never lists the
Unix user's complete queue. `hpc_job`, `hpc_job_accounting`, and
`hpc_cancel_job` normalize one Slurm identifier to its numeric submitted base
job and require ownership on the selected cluster before contacting Slurm.
This permits one owned array task, heterogeneous component, or job step without
granting access to another base job.

Cancellation requires a lifecycle idempotency key. A successful replay returns
the stored scheduler result and does not call `scancel` again. Full interactive
mode retains the confirmation gate, whereas delegated mode derives authority
from the host-selected manifest and ledger. Neither mode exposes cancellation
by user, account, partition, name, state, or an arbitrary list.

`hpc_job_accounting` uses parsable `sacct` output. A terminal state updates
the submission operation to `terminal` and releases active-job capacity.
Scheduler and authorization-ledger updates occur before best-effort writes to
the ordinary submission-history database, so a history failure is reported but
does not erase the authoritative result.

## Security verification scope

The automated suite checks the exact restricted MCP registry, malformed and
expired manifests, parent-allocation binding, every scheduler/payload allowlist
dimension, concurrent idempotency and budget enforcement, lifecycle ownership,
audit-failure recovery, and an Apptainer-like clean-environment harness with no
Slurm, SSH, or Munge commands on the agent `PATH`.

That harness validates generated arguments and environment flow; it does not
emulate Linux mount namespaces, the host kernel, site Apptainer configuration,
Munge, or Slurm. Operators must still build the reviewed SIF, run
`apptainer test`, exercise the real Unix-socket relay, inspect effective mounts,
and submit/cancel a tiny delegate job on every target cluster.
