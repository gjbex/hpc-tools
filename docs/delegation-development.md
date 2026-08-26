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
- an append-only authorization audit trail.

These controls protect the MCP-mediated path. They do not constrain other
processes running as the same Unix user. The agent container must therefore
lack Slurm commands, SSH credentials, and write access to the manifest and
ledger.

## Delegation manifest

The operator starts the host-side server with a TOML manifest selected through
`hpc-mcp --delegation PATH` or `HPC_TOOLS_MCP_DELEGATION`. The file must be
owned by the server user and must not be group- or world-writable. The server
also requires `HPC_TOOLS_PARENT_JOB_ID`; it must match `parent_job_id`.
The ledger path is selected by `--ledger`, `HPC_TOOLS_MCP_LEDGER`, or the
default `~/.config/hpc-tools/delegations.sqlite3`.

Example format version 1:

```toml
format_version = 1
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
nodes = 2
tasks = 64
cpus_per_task = 8
gpus = 2
wall_seconds = 14400
array_tasks = 100
array_concurrency = 20
memory_mib = 262144

[budget]
max_submissions = 20
max_active_jobs = 4
max_total_nodes = 30
max_total_gpus = 10
max_total_wall_seconds = 172800
```

Accounts and clusters are mandatory non-empty allowlists. Other allowlists may
be empty. An omitted optional policy field is not a wildcard: if a request
supplies that field, its value must occur in the corresponding allowlist.
Allowed roots must be absolute normalized paths. Environment-variable,
home-directory, relative, and parent-directory forms are rejected.

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

## Reservation and budget semantics

A real restricted submission requires an `idempotency_key`. In one
`BEGIN IMMEDIATE` transaction the ledger:

1. verifies that the registered manifest is unchanged, unexpired, and not
   revoked;
2. rejects reuse of a key for a different shape;
3. checks per-job policy and remaining aggregate budget;
4. creates a `reserved` operation.

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

`max_submissions` counts accepted reservations immediately so concurrent
requests cannot overrun the cap. A definite submission failure refunds it;
successful, uncertain, terminal, and cancelled jobs remain cumulative.
`max_active_jobs` counts `reserved`, `submitted`, and
`uncertain` operations. `max_total_RESOURCE` is cumulative over reserved,
submitted, uncertain, and terminal operations; failed reservations are
excluded. These MCP budgets are optional delegation ceilings, not Slurm account
balances.

## Ledger schema

The authorization ledger is separate from `submissions.sqlite3`. The latter
is agent-readable lifecycle history and must not be used as authorization
state. Ledger schema version 1 uses `PRAGMA user_version = 1` and these tables:

| Table | Purpose |
| --- | --- |
| `delegations` | Manifest digest, issuer, profile, parent allocation, expiry, and revocation state. |
| `submission_operations` | Idempotency key, request digest, reservation state, accounted resources, and resulting job identity. |
| `job_ownership` | Exact delegation/job/cluster ownership used by later lifecycle authorization. |
| `delegation_audit` | Append-only accepted and rejected mutation decisions. |

The database uses a rollback journal, `synchronous=FULL`, foreign keys, a
five-second busy timeout, and mode `0600`. As with the submission database,
this does not make arbitrary network filesystems safe for SQLite. Use
node-local or otherwise verified storage, and do not use one file as a
distributed multi-node database.

The Python API exposes `DelegationLedger.revoke` for an operator control
plane and `DelegationLedger.reconcile_job` for scheduler reconciliation.
Neither operation is exposed to the restricted agent MCP surface.
