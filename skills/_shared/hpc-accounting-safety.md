# HPC Accounting Safety

Use this reference when a task may submit Slurm jobs on systems with accounts,
credits, allocations, reservations, or project reporting.

## Account Choice

Some Slurm sites require accounts before jobs can run. Account choice is not
just a technical detail: credits can have monetary value, and account use is
often tied to project reporting.

If the user has access to multiple charge accounts, ask which account to use
before writing a final submission script or submitting a job. Do not choose an
account only because it has enough balance, appears first, or was used in a
previous job.

When creating a job script, do not assume `#SBATCH --account=...` is required.
Include it only when the site/profile requires it, the user provides it, an
existing project template uses it, or accounting helpers indicate jobs are
charged to accounts. Omit the directive on systems that do not use accounts.

## Quote Before Submit

When a configured quote helper exists, quote the exact job shape before real
submission and present the maximum estimated cost to the user.

The quote must use the same account and Slurm resource options as the planned
submission: cluster, partition, reservation, QoS, walltime, node count, task
count, CPU count, memory, GPU request, array range, and job count.

A quote becomes stale when any resource-shape input changes, including problem
size, walltime, node count, task count, CPUs, memory, GPU request, partition,
cluster, reservation, QoS, account, job count, or array range. Re-quote and
present the updated maximum cost before submitting.

## Pilot-First Is Not Cost Approval

For multi-job runs, submit one representative pilot first, wait for completion,
and inspect accounting plus output before launching the larger workload.
Pilot-first reduces wasted queue time and credits, but it does not replace
cost checks. Quote the pilot before submitting it, then quote the remaining
workload again after the pilot succeeds if job shape or job count changes.

## Failure Handling

Treat allocation failures as resource, partition, account, QoS, reservation,
memory, or availability problems to diagnose. Do not respond by silently
choosing a different account, partition, or resource shape when that would
change cost or policy implications.
