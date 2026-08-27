# Design a Delegated Job

Read this reference only when creating or materially changing a delegated job.

## Select an Unambiguous Shape

Use `hpc://runtime` as the authority for allowed accounts, clusters,
partitions, QoS values, reservations, worker containers, roots, per-job limits,
and remaining aggregate budget. Use the hardware, Slurm, and storage resources
to choose among already-authorized options.

Do not choose arbitrarily when multiple accounts or worker containers have
materially different cost or trust implications. The task contract must select
one, or the delegation must leave only one viable choice. Finish as blocked
when that decision cannot be made from supplied context.

Request the smallest useful resource shape. Prefer one representative pilot
when the script, input mapping, container, or resource estimate has not already
been demonstrated and the task contract and budget permit a pilot. A pilot is
not useful when it consumes the only authorized submission without satisfying
the objective.

The restricted wrapper currently supports one node and one Slurm task, with
multiple CPUs assigned to that task. Do not request GPUs, GRES, multiple tasks,
or multiple nodes unless `hpc://runtime` and the server explicitly expose a
reviewed extension that supports them. Use an array for independent repeated
work.

## Prepare the Payload

Write the job script as a regular, non-symlink file below the delegated work
root. Keep it deterministic and fail on errors. Load or invoke only software
already present in the approved worker image or read-only input roots; this
agent cannot install missing cluster software.

The delegate sees the complete work root and input roots read-only. Its only
writable location is the per-job directory named by
`HPC_TOOLS_DELEGATE_OUTPUT`. Make the payload write all results, checkpoints,
and application logs below that directory. Avoid absolute output paths copied
from the parent work root.

Use explicit input paths and stable configuration. Only the payload script is
snapshotted by the server. If exact auxiliary inputs matter, place them in an
operator-managed input root or use immutable, content-addressed files.

## Bind Evidence to One Logical Job

Choose an idempotency key that is stable for the logical job and independent of
transport retries. Record the script path, worker container, resource shape,
and expected artifacts before quoting. Use identical values for quote,
validation, and submission.

If script content, directory, container, array range, account, cluster,
partition, walltime, CPU, memory, or any other resource input changes, start a
new quote and validation chain. A corrected workload is a new logical job and
requires a new idempotency key plus explicit corrective-resubmission authority.
