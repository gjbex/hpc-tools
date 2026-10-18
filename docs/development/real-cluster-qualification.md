# Real-cluster qualification

Status: required before production use on each target Slurm site.

The parent-agent lifecycle and restricted-agent boundary are implemented and
covered by local automated tests. This checklist records the remaining
site-specific qualification that unit tests and fake scheduler processes cannot
establish.

Use it together with the [parent-agent lifecycle policy](../parent-agent-lifecycle.md)
and [restricted-agent deployment guide](../restricted-agent.md). A successful
run qualifies only the tested combination of cluster, partition, Slurm policy,
Apptainer configuration, hpc-tools version, and agent image.

## Record the qualification context

- [ ] Record the date, operator, cluster, profile, partition, account, QoS, and
  reservation, where applicable.
- [ ] Record the hpc-tools revision or release, Slurm version, Apptainer version,
  agent-image digest, manifest digest, and relevant site-policy references.
- [ ] Record the parent, cleanup, and delegated Slurm job IDs and the delegation
  identifier used by the pilot.
- [ ] Store raw logs, the protected ledger, generated scripts, and audit export
  in an operator-controlled location outside this repository. Sanitize secrets,
  usernames, account identifiers, and private paths before publishing a report.

## Establish safe pilot conditions

- [ ] Obtain site approval for nested `sbatch`, `scontrol requeue`, advance
  signals, dependent cleanup jobs, and Apptainer execution from compute nodes.
- [ ] Use a low-cost test account and partition with short jobs and no production
  data. Confirm a manual cancellation path before starting.
- [ ] Use dedicated, non-overlapping, non-symlinked state, work, output, and
  input roots with the documented modes and a filesystem suitable for SQLite
  locking.
- [ ] Use a C3 (`job-lifecycle`) profile and a disposable delegation manifest
  with small node, task, wall-time, submission, and requeue limits.
- [ ] Keep the batch template's `--signal=B:USR1@<seconds>` value equal to the
  manifest's `warning_seconds`, and retain `--requeue` and
  `--open-mode=append`.
- [ ] Prepare one short delegated workload that remains active across a parent
  requeue, one workload that exits naturally, and one unrelated control job
  owned by the operator but not by the delegation.

## Qualify the image and containment boundary

- [ ] Build the real agent SIF from the reviewed recipe and record its digest.
- [ ] Run the image's Apptainer test section on the target cluster.
- [ ] Confirm the site accepts `--containall`, `--cleanenv`, `--no-home`, and
  `--no-mount home,cwd,hostfs,bind-paths`; do not silently remove a rejected
  containment flag.
- [ ] Confirm the parent container can reach only the private MCP socket and the
  declared mounts with their intended read/write modes.
- [ ] Confirm the container cannot access SSH-agent sockets, the protected
  manifest or ledger, scheduler credentials, undeclared host paths, or general
  filesystem MCP tools.
- [ ] Confirm a delegated container receives the immutable payload and declared
  inputs read-only, can write only its per-job output directory, and cannot
  access the parent MCP socket or another delegated job's output directory.

## Qualify startup and baseline execution

- [ ] Submit the reviewed parent template and confirm the launcher records a new
  controller generation and protected provenance artifacts.
- [ ] Confirm exactly one cleanup job is registered with
  `afterany:<parent-job-id>` and its exact job ID is stored in the ledger.
- [ ] Confirm the restricted MCP server exposes only the expected `slurm-job`
  tools and resources for the intersection of profile and manifest authority.
- [ ] Submit the pilot delegated workload through the quote, validation, and
  confirmed-submission evidence chain.
- [ ] Confirm the ledger records the delegated job as owned, its output is
  confined to the per-job directory, and the unrelated control job is absent
  from delegation ownership.

## Qualify native quoted-credit accounting

This section is separate from local acceptance. The repository's fake quote
helper proves protocol parsing and budget enforcement, but cannot prove that a
site's native accounting service quotes the intended job shape or uses the
configured unit and scale.

- [ ] Record the native quote service, wrapper revision, response schema, and
  site documentation that define the quoted maximum. Confirm the trusted host
  wrapper writes exactly one `hpc-tools-credit-quote-v1` JSON object to stdout
  and sends diagnostics only to stderr.
- [ ] Confirm the wrapper quotes the same normalized account, cluster,
  partition, reservation, QoS, array, node, task, CPU, memory, GPU, wall-time,
  dependency, export, and container-bearing shape that reaches `sbatch`.
- [ ] Confirm the manifest's fixed-point `unit` and `scale` exactly match the
  site quote and that no currency conversion, rounding, or floating-point
  interpretation occurs in the wrapper.
- [ ] Use a disposable delegation whose `maximum_per_job` equals one observed
  native quote. Confirm the exact-boundary job succeeds and a separately quoted
  job one minor unit above that ceiling is denied before `sbatch` submission.
- [ ] In separate disposable runs, make `budget.max_submissions` bind first and
  `credit_budget.maximum_total` bind first. Confirm whichever limit is reached
  first denies the next submission and that a zero-cost quote still consumes
  one logical submission.
- [ ] Quote an array and compare the helper's received shape, the ledger's
  logical count of one, and the full array-multiplied resource totals.
- [ ] Let one native quote expire. Confirm the server requires a completely new
  quote -> validate -> submit chain and that restart does not revive prior
  quote or validation evidence.
- [ ] Exercise a definite pre-acceptance scheduler rejection and an acceptance
  whose persistence result is uncertain. Confirm only the definite failure
  releases its reservation and the uncertain acceptance retains count and
  quoted credit for operator reconciliation.
- [ ] Reconcile quote records with the site's eventual accounting statement.
  Record discrepancies explicitly: actual charge is evidence for site review,
  not an input that refunds or expands the delegated budget.

## Qualify advance signalling and same-ID requeue

- [ ] Observe Slurm deliver the configured `USR1` warning before the parent
  wall-time limit.
- [ ] Confirm the launcher enters draining state, rejects new submissions,
  stops the current agent and MCP bridge, and requests requeue of the exact
  parent job ID.
- [ ] Confirm the parent returns with the same Slurm job ID and a new controller
  generation, while append-mode logs retain the preceding attempt.
- [ ] Confirm the active delegated workload continues rather than being
  cancelled solely because the parent requeued.
- [ ] Confirm the restarted controller requires reconciliation of every active
  owned job before accepting new submissions.
- [ ] Confirm quote or validation evidence created by the previous generation is
  rejected as stale.
- [ ] Confirm the cleanup job remains dependency-blocked while the requeued
  parent is nonterminal and becomes eligible only when the parent is final.

## Qualify final cleanup and ownership confinement

- [ ] Let one delegated job finish naturally and confirm cleanup reconciles it
  without attempting cancellation.
- [ ] Cancel a parent with an active delegated workload and confirm the cleanup
  job eventually runs and cancels that exact owned job.
- [ ] Confirm the unrelated control job is neither inspected as owned nor
  cancelled.
- [ ] Exercise failed or exhausted continuation and confirm the default
  `requeue-or-cancel` policy falls back to cleanup of active owned jobs.
- [ ] Confirm cancellation reservations and cleanup status are idempotent when
  the cleanup operation is retried.
- [ ] Confirm cleanup failure is visible in the cleanup job's logs and the
  ledger, and exercise the documented operator recovery procedure.

## Review evidence and decide

- [ ] Export the joined audit view with `hpc agent export` and reconcile it with
  `squeue`, `sacct`, parent logs, cleanup logs, controller provenance, and
  delegated output status.
- [ ] Verify that ownership, budget, expiry, idempotency, reconciliation, and
  containment invariants held throughout the pilot.
- [ ] Record any scheduler outage, delayed cleanup, filesystem-locking problem,
  site mount, unsupported Apptainer flag, or policy exception encountered.
- [ ] Record whether dependency-based cleanup latency is acceptable. If the site
  requires a strict deadline, require a persistent broker or separately
  reviewed scheduler deadline before production use.
- [ ] Have a second operator review the evidence and mark the tested site/version
  combination `qualified`, `qualified with restrictions`, or `not qualified`.
- [ ] Repeat the pilot after material changes to Slurm policy, Apptainer policy,
  hpc-tools lifecycle code, the agent image, or the deployment manifest.

## Pass criteria

Qualification passes only when all applicable checks above have evidence and:

- the advance signal and same-ID parent requeue work as configured;
- controller restart reconciles owned jobs before new scheduler mutation;
- dependent cleanup becomes eligible at the site's observed final-parent event;
- final cleanup affects all and only active delegation-owned jobs;
- the tested Apptainer and MCP boundaries expose no protected control-plane
  state or undeclared writable path; and
- the native quote adapter preserves the complete submitted shape, fixed-point
  dimensions, expiry, and both count-first and credit-first refusal behavior;
  and
- failures and delays are visible to the operator with a tested recovery path.

If any criterion cannot be established, record the result as unqualified rather
than treating local automated-test success as site acceptance.
