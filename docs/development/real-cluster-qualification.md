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
- failures and delays are visible to the operator with a tested recovery path.

If any criterion cannot be established, record the result as unqualified rather
than treating local automated-test success as site acceptance.
