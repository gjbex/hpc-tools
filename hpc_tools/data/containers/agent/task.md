Use $hpc-delegated-slurm for this unattended run.

This contract must contain no unresolved placeholder before submission. If an
authorized choice remains ambiguous, report `blocked`; do not guess.

Objective:
<State one bounded objective and the durable output location.>

Success criteria:
- artifact: <exact file or directory>
  validation: <application-level command or observable acceptance condition>
- artifact: <exact file or directory, if needed>
  validation: <application-level command or observable acceptance condition>

Authorized inputs and selections:
- input roots/files: <reviewed paths or an unambiguous selection rule>
- account: <one allowed account or an unambiguous selection rule>
- cluster/partition: <one allowed combination or an unambiguous selection rule>
- worker container: <one approved image path or an unambiguous selection rule>
- job script: <approved digest/path rule, or bounded inline-script authority>

Corrective resubmission policy:
forbidden

Maximum corrective submissions:
0

If corrective resubmission is authorized instead, replace both values above
with a positive finite limit and state the exact diagnosed conditions and
changes that are allowed. Every correction is a new logical submission and
requires a fresh quote, validation, and idempotency key.

Stopping condition:
- Stop submitting as soon as every success criterion passes.
- Stop and report `blocked` on missing authority, ambiguous selection,
  exhausted budget, expired delegation, or a failure outside the corrective
  policy.
- Finish before delegation expiry. While valid delegated jobs remain active,
  continue bounded observation instead of voluntarily ending the parent.
- The host lifecycle policy controls requeue, final cancellation, or an
  explicitly authorized leave-running outcome; report that outcome and every
  affected Slurm job ID.
