# Delegated MCP credit-budget implementation plan

Status: WP1--WP2 implemented on 2026-10-16; WP3--WP8 are proposed and not yet
implemented.

This plan adds server-owned quoted-credit enforcement to the restricted
`slurm-job` MCP topology. It complements, rather than replaces, the existing
submission-count, active-job, per-job resource, and cumulative resource limits.

The target deployment is an unattended harness in a container. The harness can
write only its work directory and can reach Slurm only through the private MCP
relay. The host MCP process owns the profile, delegation manifest, HMAC secret,
ledger, staging state, Slurm credentials, and scheduler commands.

## Required outcome

A real delegated submission is accepted only when all applicable independent
limits pass:

- profile capability and scope;
- manifest lifetime, ownership, controller generation, and lifecycle state;
- account, cluster, partition, QoS, reservation, container, script, and path
  allowlists;
- per-job scheduler resource ceilings;
- cumulative logical submission count (`max_submissions`);
- concurrent active-job count (`max_active_jobs`);
- cumulative requested-resource budgets;
- optional maximum quoted cost for one logical submission; and
- optional cumulative quoted-credit budget.

The server refuses the request as soon as any limit is exhausted. Credit cost
does not imply or replace a job-count limit: an operator who wants both must set
both `budget.max_submissions` and `credit_budget.maximum_total`.

## Frozen contract decisions

WP1 freezes the following decisions for the later implementation packages.
Changing one requires an explicit plan and fixture update.

### Fixed-point credit amount

A credit amount is the tuple `(value, scale, unit)` and represents
`value * 10^-scale` units.

- `value` is a JSON integer in the inclusive range `0` through `2^63 - 1`.
- `scale` is a JSON integer in the inclusive range 0 through 9.
- `unit` matches `[a-z][a-z0-9._-]{0,31}`.
- Boolean values, JSON floats, exponent notation, negative values, and integer
  overflow are rejected.
- Policy comparison and storage use bounded integer minor units. Binary
  floating-point is never used.
- The quote unit and scale must exactly match the manifest. There is no implicit
  conversion or rounding.
- Every addition is checked before it is performed; overflow fails closed.

### Structured quote envelope

The profile retains `sam_quote_command` and gains:

```toml
sam_quote_format = "hpc-tools-credit-quote-v1"
```

For that format, successful stdout is at most 4096 bytes and contains exactly
one UTF-8 JSON object:

```json
{
  "format_version": 1,
  "maximum_cost": {
    "value": 2730,
    "scale": 0,
    "unit": "credits"
  }
}
```

Unknown or duplicate keys, trailing output, invalid UTF-8, unsupported versions,
and malformed values fail closed. Diagnostics belong on stderr and are not
parsed as authority. A site whose native quote tool prints a human report must
configure a trusted host-side wrapper; hpc-tools will not guess costs with
site-specific regular expressions.

The quote command receives the same closed, validated `sbatch` argument set as
the requested submission. Ordinary interactive quoting may retain opaque
output. A delegation containing `[credit_budget]` requires the structured
format and cannot fall back to opaque stdout.

### Delegation manifest

The credit implementation will bump the protected manifest to version 3 and
add:

```toml
[credit_budget]
unit = "credits"
scale = 0
maximum_total = 20000
maximum_per_job = 5000       # optional
quote_ttl_seconds = 300
```

`maximum_total` and `quote_ttl_seconds` are required when the table is present.
`maximum_total` and `maximum_per_job` are positive integers no greater than
`2^63 - 1`; `maximum_per_job`, when present, must not exceed `maximum_total`.
`quote_ttl_seconds` is an integer from 1 through 86400. Unknown keys are
rejected.

A manifest without `[credit_budget]` retains resource-only delegation for a
site without credit accounting. It does not silently gain credit enforcement.
The restricted accounting scenario defined by this plan requires the table.

### Job-count semantics

`budget.max_submissions` remains the maximum number of consumed logical
submission operations. It is independent of credits and resources.

- A normal `sbatch` request counts as one logical submission.
- A Slurm array also counts as one logical submission. Its full array shape is
  nevertheless included in cumulative resources and in the site quote.
- Exact idempotent replay never consumes a second count or a second credit
  reservation.
- A definite failure before scheduler acceptance releases the count, resources,
  and quoted credits.
- A successful, uncertain, terminal, or cancelled submission remains consumed
  for the lifetime of the delegation.
- `max_active_jobs` is separate: terminal jobs stop being active but continue
  to count against `max_submissions` and cumulative quoted credits.
- Count, active-job, resource, and credit checks occur in the same
  `BEGIN IMMEDIATE` reservation transaction. Passing one limit never overrides
  another; whichever applicable limit is reached first denies the request.

### Quote lifetime

`quote_ttl_seconds` limits how long quote evidence can authorize a new
reservation. It is not a job runtime, queue-wait limit, budget-reset interval,
or reservation lease.

After the quote helper succeeds and its envelope validates, the MCP server
records `issued_at` from its own UTC clock and computes:

```text
expires_at = issued_at + quote_ttl_seconds
```

Evidence is valid only while `issued_at <= now < expires_at`. Future, expired,
missing, malformed, or unsigned timestamps fail before a ledger or scheduler
effect. The agent cannot select or extend either timestamp.

An expired quote requires a fresh `hpc_quote_job` -> `hpc_validate_job` ->
`hpc_submit_job` chain. Validation evidence used for a credit-budget submission
must be issued no earlier than its bound quote. Once a valid reservation is
durably inserted, later quote expiry does not release or alter it. Server
restart invalidates outstanding evidence because the process-local HMAC secret
is not persisted.

### Evidence and exact binding

Signed quote evidence gains:

```json
{
  "quoted_cost": {
    "value": 2730,
    "scale": 0,
    "unit": "credits"
  },
  "timestamp": "2026-10-16T12:00:00+00:00",
  "expires_at": "2026-10-16T12:05:00+00:00"
}
```

The HMAC binds the typed cost, timestamps, normalized profile, account, exact
resource overrides, immutable payload digest, directory, executor,
idempotency key, container boundary, and controller generation. Any change
requires fresh quote and validation evidence. Submission consumes the typed
object returned by the parser; it does not reparse stdout or trust an unsigned
cost supplied by the client.

### Failure accounting

The server reserves job count, requested resources, and quoted credits durably
before invoking `sbatch`.

- Definite command-execution failure or definite scheduler rejection before
  acceptance releases the reservation.
- Accepted submissions, unparseable accepted responses, persistence ambiguity,
  and other uncertain outcomes retain the reservation.
- Completion and cancellation do not refund cumulative count or credit.
- Actual site-charge reconciliation is outside this plan. All exposed values
  are labelled quoted maxima, not live account balance or actual charge.
- The agent receives no refund, correction, migration, ledger-write, or
  operator-recovery operation.

### Security boundary

No new MCP tool, network listener, mount, scheduler credential, or protected
path is introduced. The existing private single-client Unix socket remains the
capability channel. Its directory stays read-only inside the harness container;
the connection itself remains bidirectional. Socket possession and Unix-UID
checking authenticate the container/user boundary, not an individual process
inside that container.

## Characterized baseline and current state

WP1 characterized the following state before credit implementation:

- delegation manifest version is 2 and rejects `credit_budget`;
- ledger schema version is 3 and stores no quote cost or quote identity;
- the profile had `sam_quote_command` but no structured-format selector;
- successful quote stdout is signed as opaque text;
- quote evidence has no typed cost or expiry;
- `max_submissions` already counts logical submissions, with arrays consuming
  one count and their elements multiplying cumulative resources;
- definite pre-acceptance failure releases an existing reservation; and
- restricted logical shapes contain `controller_generation`, but evidence
  normalization currently drops that top-level field, so the generation is not
  bound by the evidence HMAC.

WP2 adds the strict format selector and pure structured parser. A successful
real `hpc_quote_job` now returns `structured_quote` when the selector is set;
that convenience field is not yet signed evidence or submission authority.
Manifest, ledger, expiry, and controller-generation behavior remain at the WP1
baseline until their owning packages.

The synchronized work-package fixture is
`tests/fixtures/delegated_credit_budget_baseline.json`; its regression tests are
in `tests/test_delegated_credit_budget_baseline.py`. These are intentional
change detectors, not promises to preserve the missing behavior. Later work
packages must update the fixture and tests alongside the implementation.

## Dependency order

| Package | Deliverable | Depends on |
| --- | --- | --- |
| WP1 | Contract freeze and characterization baseline | None |
| WP2 | Strict structured quote parser and profile configuration | WP1 |
| WP3 | Manifest v3 and startup admission | WP1, WP2 |
| WP4 | Cost-bearing, expiring, generation-bound evidence | WP2, WP3 |
| WP5 | Ledger schema and atomic credit reservation | WP3, WP4 |
| WP6 | MCP, runtime, launcher, and operator-audit integration | WP4, WP5 |
| WP7 | Documentation, examples, image skill, and packaging | WP3--WP6 |
| WP8 | Local, installed, protocol, and live-site acceptance | WP1--WP7 |

## WP1: Contract freeze and characterization baseline

Status: implemented on 2026-10-16.

Work:

1. Freeze fixed-point, strict-envelope, manifest, job-count, TTL, evidence,
   failure-accounting, and transport-boundary semantics in this plan.
2. Record manifest, ledger, profile, and quote-evidence schema versions before
   production changes.
3. Characterize opaque quote output, absence of cost/expiry, strict rejection
   of premature `credit_budget`, logical array counting, failure refund, and the
   controller-generation evidence gap.
4. Capture the pre-change focused test baseline and add a synchronized fixture
   that later packages must update deliberately.

Exit criteria: every deferred behavior has an explicit owning package; the
current gaps are executable and documented; no production schema or runtime
behavior changes in WP1.

Implementation artifacts:

- this plan and contract record;
- `tests/fixtures/delegated_credit_budget_baseline.json`;
- `tests/test_delegated_credit_budget_baseline.py`.

Validation record:

- Before the WP1 additions, the focused contract, MCP submission, and
  delegation slices passed 33 tests.
- The new WP1 characterization module passes five tests.
- The complete supported suite passes 448 tests. Its two local-socket cases
  were rerun outside the restricted command sandbox after the sandbox correctly
  denied loopback TCP and Unix-socket creation; the unrestricted run passed.
- Locked dependency checking, plugin validation, skill validation, Python
  compilation, Ruff checks, and strict MkDocs construction pass.
- `tools/check_repo_hygiene.py` remains blocked by existing ignored development
  artifacts (`.ruff_cache`, `build`, `hpc_tools.egg-info`, and bytecode cache
  trees). WP1 did not delete unrelated local state.
- No live cluster, scheduler submission, or site accounting helper was used.

## WP2: Structured quote parser and profile contract

Status: implemented on 2026-10-16.

Add and strictly parse `sam_quote_format`. Implement the v1 envelope decoder
with duplicate-key detection, bounded input, exact keys, fixed-point validation,
unit normalization, and overflow checks. Keep opaque quotes available only when
credit policy is absent. Test malformed UTF-8, duplicate and unknown keys,
trailing bytes, wrong versions, Boolean/float/negative/oversized values, and
stderr-only diagnostics.

Exit criteria: the parser returns one immutable typed cost or fails closed; it
has no ledger or scheduler side effects.

Implementation artifacts:

- `hpc_tools/credit_quotes.py` defines the immutable fixed-point types, bounds,
  v1 selector, and strict 4096-byte parser;
- `hpc_tools/config.py` parses the optional selector, rejects unknown formats,
  and requires a quote command when it is set;
- `hpc_tools/mcp/submit.py` parses successful non-dry-run quote stdout and
  returns `structured_quote` separately from the still-opaque signed evidence;
- parser, configuration, MCP integration, and synchronized-baseline tests cover
  the fail-closed cases without contacting a cluster.

The `structured_quote` response is informational in WP2. `hpc_submit_job` does
not consume it, and clients must not treat it as budget authorization. WP4 will
place the typed cost inside signed, expiring, shape-bound evidence.

Validation record:

- The 69-test focused parser, configuration, MCP submission, synchronized
  baseline, MCP resource, and restricted-boundary slice passes.
- The complete supported suite passes 458 tests.
- Locked dependency checking and synchronization, plugin and skill validation,
  Python compilation, focused Ruff checks, and strict MkDocs construction pass.
- `tools/check_repo_hygiene.py` remains blocked by the pre-existing ignored
  caches, build output, and egg-info recorded under WP1; they were preserved.
- No live quote helper, cluster, or scheduler operation was used.

## WP3: Manifest v3 and startup admission

Parse `[credit_budget]` with the frozen bounds and reject unknown or
inconsistent fields. At restricted-server startup, require a compatible quote
command and format when credit policy is present. Capture the credit policy,
profile configuration digest, and quote-format identifier in protected
controller authority. Preserve resource-only manifests for sites without
credit accounting.

Exit criteria: incompatible setups fail before the harness or any scheduler
effect starts, without widening tools, mounts, or capabilities.

## WP4: Cost-bearing and expiring evidence

Extend quote evidence with typed cost, server timestamps, expiry, quote identity,
and validation-chain binding. Retain `controller_generation` in canonical shape
normalization. Use an injectable clock and require
`issued_at <= validation_at <= now < expires_at`. Reject tampering, restart-old
HMACs, dry-run evidence, changed shapes, wrong executor/unit/scale, and future or
expired evidence before ledger access.

Exit criteria: cost evidence is authoritative only for the exact current
payload, shape, executor, idempotency key, and controller generation.

## WP5: Ledger schema and atomic credit reservation

Bump the ledger schema without silently migrating protected ledgers. Store
fixed-point quote cost, evidence identity, expiry, and reservation state with
each submission operation. Check per-job cost, total credit, job count, active
jobs, and aggregate resources inside the existing `BEGIN IMMEDIATE` transaction.
Include cost and quote identity in idempotency hashing. Preserve fail-closed
uncertainty and release only definite pre-acceptance failures.

Exit criteria: concurrent callers cannot overspend the final count, resource,
or credit allowance; exact replay consumes nothing twice.

## WP6: MCP, runtime, launcher, and audit integration

Preserve the seven-tool `slurm-job` surface and the ordered quote -> validate ->
submit chain. Return structured denials distinguishing format, expiry, per-job
cost, total credits, submission count, active jobs, and resources without
exposing protected paths or commands. Extend `hpc://runtime` with consumed and
remaining quoted maxima. Extend operator audit/export with per-operation and
aggregate quote data. Keep actual balance and actual charge clearly out of
scope.

Exit criteria: the harness can make deterministic stopping decisions from
read-only public state, while only the host process can mutate authority.

## WP7: Documentation, examples, image skill, and packaging

Update configuration, restricted-agent, MCP, delegation-internals, examples,
schemas, and the image-only `hpc-delegated-slurm` skill. Document count-versus-
credit semantics, arrays, quote expiry, failure retention, and operator setup.
Validate that source distributions, wheels, plugin assets, and agent-image
assets include the synchronized material without combining the Python CLI and
Codex-plugin installation surfaces.

Exit criteria: an operator can configure the pair without reading source, and
the unattended skill cannot imply authority absent from MCP.

## WP8: Acceptance and handoff

Add fake-helper, concurrent-ledger, real stdio MCP, restricted bridge,
clean-install wheel/sdist, and separately reported live-site qualification.
Required cases include exact-boundary acceptance, one-minor-unit rejection,
count-first and credit-first denial, array accounting, expiry, restart,
idempotency, definite failure, uncertain acceptance, and protected-state
negative tests.

Run the repository validation sequence from `AGENTS.md`. Report live scheduler
and site-accounting evidence separately; local fakes cannot prove a site's
native quote semantics.

Exit criteria: WP1--WP8 have literal evidence, all budgets are bound end to end,
and the container boundary remains intact.
