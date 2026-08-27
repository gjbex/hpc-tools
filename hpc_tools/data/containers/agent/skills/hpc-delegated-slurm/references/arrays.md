# Delegated Job Arrays

Read this reference only when the objective requires independent repeated work
that should be represented as a Slurm array.

## Define the Mapping

Use an explicit immutable manifest when task metadata matters. Map each array
index deterministically to one input and one unique application-output path
below `HPC_TOOLS_DELEGATE_OUTPUT`. Reject duplicate output targets and ambiguous
zero- versus one-based indexing before quotation.

Keep array elements independent. Do not use an array when tasks require shared
writable state, ordered execution, or concurrent writes to the same files.

## Bound Scale and Pressure

Check the Slurm reference for `MaxArraySize`, submit limits, and site-specific
array semantics. Check runtime per-job and aggregate budget before selecting the
range. Add a concurrency cap when simultaneous tasks would pressure shared
storage, a license service, or another shared dependency.

For short tasks, group several manifest rows into one array element so scheduler
and container startup do not dominate. Preserve deterministic row mapping and
propagate any row failure to the element exit status.

When the task contract and budget permit, quote, validate, submit, and verify a
representative one-element or small-slice pilot before the remaining range. The
pilot and remaining array are different logical jobs with different
idempotency keys and separate evidence chains. Do not submit the remainder
unless the pilot's expected artifacts and mapping are verified.
