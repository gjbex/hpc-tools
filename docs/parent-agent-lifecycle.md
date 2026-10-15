# Parent-agent and delegated-job lifecycle policy

Status: implemented in hpc-tools; the
[real-cluster qualification](development/real-cluster-qualification.md) is
still required on each target site.

This document defines what should happen to jobs submitted by an unattended
parent agent when its own Slurm allocation ends. It also describes the changes
required to implement that policy without weakening delegation ownership,
budget, or container boundaries.

## Terminology

A **parent agent job** is the Slurm allocation that runs `hpc-agent-launch`,
the host-side restricted MCP server, and the agent container.

A **delegated job** is a separate Slurm job submitted through that restricted
MCP server and recorded as owned by the active delegation. It is not a Slurm
*dependency job* unless its submission explicitly contains `--dependency`.

A **controller attempt** is one execution of the parent batch script. Requeuing
the parent starts a new attempt with the same Slurm job ID but a fresh agent
process and temporary Codex home.

## Policy decisions

The default policy is:

- explicit cancellation of the parent cascade-cancels its active delegated
  jobs;
- a predictable parent wall-time limit first attempts to requeue the parent;
- delegated jobs continue during a valid, bounded parent requeue;
- failure to establish a valid continuation cascade-cancels active delegated
  jobs;
- `leave-running` is available only when explicitly authorized by the
  delegation issuer.

This distinction avoids throwing away valid compute merely because the
controller reached a predictable wall-time, while retaining cancellation as
the fail-safe outcome when supervision cannot be restored.

`leave-running` does not transfer ownership and must not mean "forget these
jobs". The manifest must identify an operator or successor procedure that can
observe, reconcile, and cancel surviving jobs.

## Manifest policy

Manifest format version 2 accepts this optional policy table and uses these
values as its defaults:

```toml
[lifecycle]
on_cancel = "cancel"
on_timeout = "requeue-or-cancel"
on_failure = "cancel"
on_normal_exit_with_active_jobs = "cancel"
max_requeues = 3
warning_seconds = 600
```

The issuer may explicitly choose `leave-running` for an applicable terminal
event. The agent cannot select or relax these values through MCP.

`max_requeues` and `warning_seconds` have finite, validated upper bounds. A
manifest cannot create an immortal controller or allow repeated controller
attempts to extend delegation expiry.

## Event policy

| Parent event | Default action | Delegated-job treatment |
| --- | --- | --- |
| Explicit `CANCELLED` | Finalize the controller and invoke cleanup | Cancel every ledger-owned active job |
| Advance wall-time warning | Enter `draining` and request parent requeue | Preserve jobs while continuation is being established |
| Requeue accepted | Start a new controller attempt under the same parent job ID | Preserve ownership and reserved budget; reconcile before new submissions |
| Requeue rejected or retry limit reached | Finalize the controller and invoke cleanup | Cancel every ledger-owned active job |
| Final `TIMEOUT` without a valid continuation | Invoke cleanup | Cancel every ledger-owned active job |
| `FAILED` or `NODE_FAIL` | Invoke cleanup | Cancel every ledger-owned active job |
| `PREEMPTED` and demonstrably requeued | Wait for the next controller attempt | Preserve jobs during the bounded continuation |
| Normal exit with no active delegated jobs | Finalize normally | No cleanup required |
| Normal exit with active delegated jobs | Treat as unsafe unless explicitly authorized | Cancel by default; preserve only under `leave-running` |
| Explicit `leave-running` | Finalize and transfer responsibility to the documented operator procedure | Preserve jobs and ownership; continue reconciliation outside the dead parent |

Slurm reports `TIMEOUT`, `CANCELLED`, `FAILED`, `NODE_FAIL`, and `PREEMPTED` as
distinct states. The cleanup component must use scheduler state rather than
guessing the cause from a missing process.

## Lifecycle state machine

```text
                    advance warning
running ---------------------------------> draining
   |                                          |
   | explicit cancellation/failure           | requeue accepted
   v                                          v
final -----------------------------------> continuation-pending
   |                                          |
   |                                          | same Slurm job ID restarts
   |                                          v
   |                                      reconciling
   |                                          |
   |                                          v
   |                                        running
   |
   +-- cleanup policy --> cancelling --> final
```

`draining` blocks new submissions. `continuation-pending` is valid only for a
bounded, ledger-recorded requeue attempt. A missing or expired continuation
falls through to cleanup.

## Why requeue the parent

Slurm restarts a requeued batch script from the beginning with the same job ID.
That fits the current manifest binding to `parent_job_id` and avoids inventing
implicit ownership transfer to a different allocation. See the Slurm
[`sbatch --requeue`](https://slurm.schedmd.com/sbatch.html) documentation.

Requeue is nevertheless site policy, not an hpc-tools guarantee. A target site
may disable or restrict it, and the requeued controller may wait in the queue.
The delegated jobs can continue during that gap because they already run in
approved restricted containers, possess no parent MCP credential, and have
already reserved delegation budget. No new delegated submission is possible
while the controller is absent.

Where user-initiated requeue is unavailable, continuation requires a successor
agent job and a broker-authorized ownership handoff. That is a separate, more
complex policy because the parent Slurm job ID changes. It must never infer
authority from the Unix user or account alone.

## Advance warning and graceful drain

The parent job template should request a warning before its wall-time limit,
for example:

```bash
#SBATCH --requeue
#SBATCH --signal=B:USR1@600
```

Slurm may deliver the requested warning up to 60 seconds earlier than the
specified offset. At the hard limit it normally sends `SIGTERM`, waits the
site-configured `KillWait`, and then sends `SIGKILL`. The advance warning is
therefore the useful cleanup window; `KillWait` alone is too short and is not a
portable checkpoint interval. See the Slurm [`--signal` and `--time`](https://slurm.schedmd.com/sbatch.html)
documentation and [`KillWait`](https://slurm.schedmd.com/slurm.conf.html).

On the warning, the host launcher should:

1. atomically change the controller state from `running` to `draining`;
2. reject new submissions while allowing read-only status and accounting;
3. stop the agent and let any submission reserved before the drain settle while
   the MCP bridge remains alive;
4. stop the MCP bridge cleanly;
5. record a bounded `requeue-requested` audit event; the new controller
   generation is created only when Slurm restarts the batch script;
6. run `scontrol requeue` for the exact validated parent job ID from the host
   namespace;
7. record whether Slurm accepted the request; and
8. fall back to terminal cleanup if requeue fails.

The Python signal handler only sets a flag for the launcher's `Popen`-based
control loop. SQLite transactions and blocking subprocess work happen after
normal control returns from the handler.

Because `B:` targets the batch shell, the generated shell script must either
run the launcher in the background and forward the signal safely, or use a
site-tested alternative that signals the Python launcher directly. Shells can
delay trap handling while waiting for a foreground child, so the generated
pattern needs an integration test rather than documentation-only confidence.

## Restart and reconstruction

Requeue starts the batch script again, but the current Codex wrapper creates a
new temporary Codex home. Conversation state is therefore not a durable
checkpoint.

The new attempt must reconstruct its state from:

- the original reviewed task;
- the delegation manifest and controller generation;
- ledger-owned job IDs and stable submission idempotency keys;
- job output and status files beneath the authorized roots; and
- an optional small, non-secret progress journal in the work directory.

On startup, the server must enter `reconciling`, query every active owned job,
and update terminal states before allowing another submission. This must be a
server-enforced gate rather than a skill instruction alone. Quote and
validation evidence from a previous controller generation should be rejected;
the restarted agent can obtain fresh evidence after reconciliation.

## Durable cleanup

Parent-side signal handling is only a fast path. It cannot enforce cleanup
after `SIGKILL`, node failure, launcher failure, or loss of the execution node.
Enforcement therefore uses a component outside the parent allocation. The
implemented user-deployable choice is a small Slurm cleanup job submitted with
an `afterany:<parent-job-id>` dependency before the agent starts. Slurm makes
such a job eligible after the predecessor terminates, but queue delay means it
cannot promise immediate cancellation. Its behavior across parent requeue must
be verified on each target site. A persistent host-side supervisor or broker
remains the stronger option for deployments requiring bounded cleanup latency.

The cleanup component must:

- read the protected manifest and ledger outside the agent container;
- query the parent job's authoritative Slurm state;
- distinguish a valid requeue from final termination;
- reserve idempotent cleanup operations in the ledger;
- cancel only exact active job IDs owned by the affected delegation;
- reconcile jobs that became terminal naturally during cleanup;
- retain conservative `uncertain` state when scheduler acceptance and ledger
  persistence cannot be made atomic;
- retry bounded scheduler failures without duplicating cancellation; and
- append accepted and rejected cleanup decisions to the audit history.

It must never cancel by Unix user, account, partition, job name, or broad state
filter. The cleanup job is control-plane infrastructure and should be recorded
separately from the delegation's compute-job budget.

## Ledger implementation

Manifest format version 2 and ledger schema version 3 provide:

- lifecycle policy in `DelegationManifest` and its public runtime summary;
- a `controller_attempts` table containing generation, parent job ID, state,
  restart count, timestamps, and terminal reason;
- the cleanup component's job or service identity and last observation;
- audit operations for drain, requeue request/result, restart, reconciliation,
  fallback cleanup, and explicit preservation; and
- transaction methods that combine state checks with submission blocking.

The pre-production decision was to preserve no existing authorization data.
Old manifest and ledger versions are rejected clearly; there is no implicit
migration.

## Evidence and MCP behavior

The restricted MCP tool list does not need a requeue tool. Parent continuation
is host lifecycle control and must not be delegated to the agent.

The restricted surface now has these behaviors:

- `hpc://runtime` reports the effective lifecycle policy, controller state,
  generation, restart count, and reconciliation requirement;
- `hpc_submit_job` rejects requests while draining, continuation is pending, or
  startup reconciliation is incomplete;
- quote and validation evidence is bound to the delegation and controller
  generation where applicable;
- lifecycle reads remain available during draining when the MCP server is
  still reachable; and
- terminal reconciliation and cleanup update the same ownership and budget
  invariants as explicit agent cancellation.

The image-only `hpc-delegated-slurm` skill no longer says that active jobs are
always left running when its observation period ends. It keeps observing valid
work while possible, reconstructs after a host-controlled continuation, and
reports the host policy's decision without overriding it.

## Failure and race handling

| Race or failure | Required outcome |
| --- | --- |
| Warning arrives during submission | The ledger transaction establishes one order: a reservation committed before draining is allowed to settle while the bridge stays alive; a later reservation is rejected |
| Delegated job finishes while cleanup is reserving cancellation | Reconcile it as terminal; do not turn natural completion into an error |
| Requeue accepted but result persistence fails | Record or recover an `uncertain` continuation and let the external component query Slurm before acting |
| Requeue command fails definitively | Mark the attempt failed and initiate default cleanup |
| Parent disappears without warning | External component applies the terminal-state policy |
| Requeued parent waits in the queue | Preserve jobs and prohibit new submissions; the dependent cleanup job cannot enforce a wall-clock continuation deadline while its dependency is still live |
| Restarted parent races with cleanup | A ledger lease or generation check permits only one of continuation or terminal cleanup |
| Cleanup is replayed | Return the recorded result; do not issue duplicate `scancel` calls blindly |
| Unrelated job shares the Unix account | Reject it before any scheduler mutation because it lacks delegation ownership |
| Delegation expires during continuation | A restarted server rejects the expired manifest; dependent cleanup runs after the parent becomes final, while strict cleanup at the expiry instant requires a persistent broker |

## Security invariants

Implementation is acceptable only if all of these remain true:

- the agent container has no Slurm commands, SSH credentials, manifest, ledger,
  or cleanup credential;
- only the host launcher or external cleanup component can requeue the parent;
- all delegated-job mutations require exact ledger ownership;
- controller continuation cannot extend manifest authority, budget, or expiry;
- a new Slurm job ID cannot adopt surviving jobs without an explicit,
  issuer-authorized handoff protocol;
- requeue and cleanup operations are idempotent and audited; and
- loss of the parent process cannot silently convert the default from `cancel`
  to `leave-running`.

## Implementation map

Implemented code and documentation changes include:

| Area | Implemented changes |
| --- | --- |
| `hpc_tools/delegation.py` | Parse lifecycle policy; add controller state, transactions, audit events, and schema/version handling |
| `hpc_tools/restricted_launch.py` | Add signal-aware process control, drain, requeue, restart, and finalization paths |
| Restricted MCP resources and submission code | Expose lifecycle state and enforce drain/reconciliation/generation gates |
| New host cleanup module and console entry point | Observe final parent state and perform exact ownership-scoped cleanup |
| Agent Slurm template | Add requeue and advance-signal directives plus safe signal forwarding |
| `hpc-delegated-slurm` skill and task template | Teach restart reconstruction and defer terminal policy to the host |
| Delegation and boundary tests | Cover state transitions, failures, concurrency, ownership isolation, and restarts |
| Operator and deployment documentation | Explain site requirements, recovery, observability, and `leave-running` responsibility |

## Verification plan

Automated tests must cover:

- strict manifest validation and safe defaults;
- every parent terminal state and policy value;
- successful requeue and restart under the same job ID;
- bounded requeue attempts and fallback cancellation;
- submission rejection during drain and before restart reconciliation;
- stale evidence across controller generations;
- abrupt parent loss without signal handling;
- cleanup races with submission, natural completion, and explicit cancellation;
- idempotent requeue and cleanup recovery after ledger failures;
- arrays, heterogeneous identifiers, and uncertain submissions;
- isolation from unrelated delegations and unrelated jobs under the same Unix
  account; and
- explicit authorization and operator ownership for `leave-running`.

Unit tests cannot establish site behavior. Each supported target cluster also
needs a pilot that verifies:

1. advance-signal delivery to the launcher;
2. permission to requeue the user's parent job;
3. same-job-ID restart and dependency behavior;
4. reconstruction and reconciliation after a queued restart;
5. cleanup after explicit cancellation, final timeout, and node/process loss;
6. Apptainer and credential boundaries during every controller attempt; and
7. ledger correctness on the selected filesystem.

## Acceptance criteria

- Explicit parent cancellation eventually cancels every active job owned by
  the delegation, subject to an explicitly surfaced scheduler outage or
  recovery condition.
- A wall-time warning can requeue the parent without cancelling valid delegated
  compute, and the restarted controller reconciles before mutating scheduler
  state.
- A failed or exhausted continuation falls back to cancellation unless
  `leave-running` was explicitly authorized. An expired continuation cannot
  submit more work and is cleaned after the parent becomes final.
- No termination, requeue, reconciliation, or cleanup path can inspect or
  mutate a job not owned by the affected delegation.
- Ownership, budget, expiry, idempotency, audit, and container-boundary
  invariants hold across restart and cleanup races.
- Site-specific behavior is demonstrated using the
  [real-cluster qualification checklist](development/real-cluster-qualification.md),
  not inferred from unit tests.

## Remaining deployment choices

- Optional application checkpoint signalling is not implemented. It needs a
  separate allowlisted signal contract; sending a generic signal to arbitrary
  workloads would be unsafe.
- The generated template uses a 600-second warning and the manifest defaults to
  three requeues. Operators changing the warning must update both places and
  qualify the result on the target cluster.
- `leave-running` retains ledger ownership but has no automatic successor-agent
  handoff. The issuer needs an external operator procedure for adopted jobs.
- Sites requiring bounded cleanup latency should replace the dependent cleanup
  job with a persistent broker while retaining the same ledger ownership rules.
- The dependent cleanup job cannot wake at manifest expiry while a requeued
  parent remains pending indefinitely. Enforcing that wall-clock deadline also
  requires a persistent broker or a separately reviewed scheduler deadline.
