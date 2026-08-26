# Restricted non-interactive MCP mode

## Goal

Support an unattended agent running inside an Apptainer container in a Slurm
allocation. The container has no Slurm commands or SSH access. It receives:

- read-only MCP access to previously gathered cluster information, including
  hardware characteristics, scheduler policies, storage characteristics, and
  relevant site guidance;
- a narrow MCP job-lifecycle API;
- direct filesystem access only to explicitly bound input, work, and output
  directories.

Delegated jobs should also run in restricted Apptainer containers. Their
stdout, stderr, logs, checkpoints, and other outputs should be written beneath
per-job directories visible to the parent agent through its bound delegation
workspace. Ordinary output access therefore does not need an MCP log-reading
tool.

## Already implemented

- [x] Local and SSH command executors shared by the CLI and MCP server.
- [x] Stored hardware context through `hpc_hardware_context` and
  `hpc://profiles/{profile}/hardware`.
- [x] Stored Slurm and storage context through profile resources.
- [x] Live Slurm-limit inspection through `hpc_slurm_limits`.
- [x] Job quotation through `hpc_quote_job`.
- [x] Job validation through `hpc_validate_job` using `sbatch --test-only`.
- [x] Job submission through the quote, validation, and submission evidence chain.
- [x] Live queue listing through `hpc_jobs`.
- [x] Live inspection of one queued job through `hpc_job`.
- [x] Cancellation of one validated job ID through `hpc_cancel_job`.
- [x] Local submission history through `hpc_submissions_list` and submission resources.
- [x] SQLite submission event storage with transactional writes and a versioned schema.
- [x] Slurm accounting through the CLI command `hpc sacct`.

The existing confirmation and dry-run gates are safety mechanisms for an
interactive client. They are not authorization for unattended execution.

## Required work

### 1. Define the restricted server surface

- [x] Add a `slurm-job` MCP capability preset.
- [x] Register only the tools and resources permitted by that preset; do not
  register the full server and rely on client-side tool filtering.
- [x] Expose the selected profile's stored hardware, Slurm-policy, and storage
  information without exposing arbitrary profile enumeration or the raw
  `hpc://config` resource.
- [x] Add a runtime/delegation resource reporting the effective policy,
  delegation identifier, expiry, permitted partitions/accounts, allowed
  filesystem roots, and remaining submission/resource budget.
- [x] Keep installation, reference mutation, probe generation, arbitrary site
  inspection, and unrelated local-state mutation out of this preset.

### 2. Add delegation policy, ownership, and agent accounting

Keep the responsibility split explicit:

- Slurm remains authoritative for Linux identity, account associations,
  partitions, QoS, reservations, resource limits, scheduling, and cluster-wide
  usage/accounting. The MCP server must not emulate Slurm accounts or
  partitions, maintain a second account balance, or claim that its checks make
  a scheduler-invalid request valid.
- The delegation policy may only narrow what Slurm permits. Its account,
  cluster, partition, QoS, reservation, container, path, and resource fields
  are allowlists or tighter ceilings selected by the delegation issuer, not
  replacement scheduler policy.
- The MCP ledger supplies controls Slurm does not provide for one unattended
  agent delegation: ownership of delegated job IDs, idempotent mutation,
  expiry, an optional agent-scoped compute budget, and an audit trail.
- Scheduler-native limits should be queried from Slurm and relied on where
  available. Ledger budgets are appropriate only for delegation-specific caps
  that an ordinary user cannot create or delegate through site-managed Slurm
  associations or QoS.
- These controls protect the MCP-mediated agent path, not the Unix user from
  themselves. The server and ledger must run outside the agent container, and
  the container must have neither Slurm commands nor credentials that bypass
  MCP.

Required work:

- [x] Define a versioned, issuer-authorized delegation manifest.
- [x] Bind the delegation to the parent Slurm job/allocation and selected
  cluster profile. The host-selected stdio server process and its private pipe
  are the client boundary; no delegation credential is exposed as an MCP
  argument.
- [x] Define narrowing allowlists for accounts, clusters, partitions, QoS
  values, reservations, approved container images, script identities or
  hashes, and filesystem roots.
- [x] Define optional per-job ceilings for nodes, tasks, CPUs, memory, GPUs,
  wall time, and array size/concurrency. Slurm remains the final authority and
  may impose stricter limits.
- [x] Define only the aggregate agent budget that Slurm cannot already enforce
  for this delegation, such as accepted submission count and concurrently
  active or cumulatively requested resources. Specify reservation, release,
  cancellation, and terminal-job accounting semantics before implementation.
- [x] Add an expiry time, explicit policy version, issuer identity, and
  revocation mechanism.
- [x] Add idempotency keys so retries cannot create duplicate jobs or consume
  the delegation budget twice.
- [x] Extend or complement the submission database with server-owned delegation
  and job-ownership records; do not treat the agent-readable submission history
  as the authorization ledger.
- [x] Update ownership and budget state atomically across concurrent MCP
  requests, including an explicit recovery state for a scheduler-accepted
  submission whose ledger update is interrupted.
- [x] Record an append-only audit event for every accepted and rejected
  mutation, while keeping mutable reservation/counter state separately
  queryable.
- [x] Add an ownership-checked terminal-state reconciliation primitive that
  releases active capacity without importing unrelated jobs. Fetching queue and
  accounting state through MCP remains lifecycle work in section 3.

### 3. Complete and restrict the job lifecycle API

- [ ] Add an MCP accounting operation corresponding to `hpc sacct` so
  completed jobs remain observable after leaving the live queue.
- [ ] Filter job listing to jobs created under the active delegation.
- [ ] Require delegation ownership for inspection, accounting, and cancellation.
- [x] Enforce the delegation policy before quotation, validation, and
  submission, and recheck it atomically immediately before submission.
- [ ] Replace interactive `confirm=true` as the authority for unattended
  submission and cancellation. Authorization must come from the delegation;
  dry-run/preview may remain useful diagnostics.
- [ ] Reconcile successful submissions and cancellations with the delegation
  ledger even when updating the local audit log fails.
- [ ] Handle Slurm arrays and heterogeneous job identifiers consistently.
- [ ] Do not add broad cancellation filters by user, partition, state, or job name.
- [ ] Defer requeue support until duplicate-work, idempotency, and resource
  accounting semantics are defined.

### 4. Enforce the Apptainer boundary

- [ ] Ensure the parent agent image contains neither Slurm client commands nor
  SSH tooling or credentials.
- [ ] Bind only explicitly authorized input, work, and output directories;
  review and disable unintended default/system binds where possible.
- [ ] Create a separate directory for each delegated job before submission.
- [ ] Generate validated host-side Slurm stdout/stderr paths beneath that job
  directory rather than accepting arbitrary paths from the agent.
- [ ] Bind common inputs read-only and give each delegated job only its own
  writable output/checkpoint directory unless sharing is explicitly required.
- [ ] Run delegated computations in an approved Apptainer image under the same
  filesystem restrictions.
- [ ] Do not pass the parent's MCP credential to delegated computations.
  Issue a narrower derived delegation only if recursive job management is an
  explicit requirement.
- [ ] Minimize inherited environment variables and prevent credentials or
  secrets from being written to logs.
- [ ] Account for symlink escape, storage exhaustion, excessive file counts,
  partial outputs, and concurrent writers.

### 5. Test and document the security properties

- [ ] Add registry tests proving forbidden tools and resources are absent from
  the `slurm-job` preset.
- [ ] Test expired, malformed, and wrong-parent delegations.
- [ ] Test unauthorized account, partition, QoS, path, container, script, and
  resource requests.
- [ ] Test duplicate and concurrent submissions against the same idempotency
  key and exhausted budgets.
- [ ] Test that jobs outside the delegation cannot be listed, inspected,
  accounted, or cancelled.
- [ ] Test failure recovery when Slurm accepts a mutation but ledger or audit
  persistence fails.
- [ ] Add an integration test using an Apptainer-like restricted environment
  with no Slurm executables available to the agent.
- [ ] Document deployment topology, trust boundaries, manifest format,
  operator workflow, audit/recovery procedures, and known limitations.

## Intended minimal MCP interface

Exact names can be settled during implementation, but the unattended surface
should cover only:

- stored hardware, Slurm-policy, storage, and runtime/delegation context;
- delegated-job quotation and validation where required by site policy;
- delegated-job submission;
- delegated-job listing and inspection;
- delegated-job accounting;
- delegated-job cancellation;
- read-only submission/audit history scoped to the delegation.

Files and job outputs remain ordinary files inside explicitly bound
directories. MCP is the scheduler authority boundary; Apptainer and filesystem
permissions are the process and data-access boundaries.
