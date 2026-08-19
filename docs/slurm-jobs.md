# Running Slurm jobs

A reliable Slurm workflow has four stages: understand the site, describe one
resource shape, validate a small representative job, and monitor both scheduler
state and application output. Submission is the short step in the middle, not
the whole workflow.

The examples use an explicit profile and remote working directory. Replace all
accounts, partitions, clusters, paths, and module versions with values verified
for your site.

## Gather current context

Before writing or adapting a job script, inspect the cluster:

```console
hpc --profile example slurm-limits --cluster example-cluster
hpc --profile example hardware
hpc --profile example quota
hpc --profile example balance
```

Not every profile provides quota or balance helpers. If those commands are not
available, use the site's authoritative alternatives.

Confirm these decisions before submission:

- the authorized account and, if applicable, cluster;
- a partition intended for the workload;
- any required or permitted QoS and reservation;
- the node, task, CPU, memory, GPU, and time shape;
- the input, output, temporary-storage, and checkpoint locations;
- the software environment and version constraints;
- the approximate charge or allocation impact.

Never substitute an account, partition, QoS, or reservation merely to make a
validation error disappear. Each can change policy, priority, cost, or who is
allowed to run the work.

## Describe the resource shape

Slurm options express different dimensions. Treat them independently.

| Dimension | Typical option | Question it answers |
| --- | --- | --- |
| Placement | `--nodes` | How many nodes must be allocated? |
| Processes | `--ntasks`, `--ntasks-per-node` | How many processes or ranks will run? |
| Threads | `--cpus-per-task` | How many CPUs may each process use? |
| Memory | `--mem` or `--mem-per-cpu` | How much memory must Slurm reserve? |
| Accelerators | `--gpus`, `--gpus-per-node`, `--gpus-per-task`, `--gres` | Which and how many accelerator resources are required? |
| Duration | `--time` | What is the credible upper bound for the pilot or production run? |
| Policy | `--account`, `--partition`, `--qos`, `--reservation`, `--cluster` | Under which site rules and allocation will it run? |

More resources do not automatically make a job faster. An application must be
able to use the requested processes, threads, memory, and devices. Excessive
requests can increase queue time and cost; insufficient requests can cause
failure or misleading performance.

For threaded libraries, align the application's thread count with
`--cpus-per-task`. For MPI, align the launcher and rank count with `--ntasks`.
For hybrid jobs, document both. Validate binding and placement on the target
site rather than assuming defaults are portable.

## Write a batch script

The following is a conservative single-process template:

```bash
#!/bin/bash -l
#SBATCH --job-name=simulation-pilot
#SBATCH --account=project123
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.err

set -euo pipefail

module purge
module load gcc/14.2.0
module load python/3.13.1

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

python simulation.py \
    --config configs/pilot.toml \
    --output "results/${SLURM_JOB_ID}"
```

Only include account, cluster, partition, QoS, and reservation directives that
the site requires or that you have chosen deliberately. A script copied from
another project can encode the wrong policy even when its executable command is
valid.

Use explicit module versions when reproducibility matters. Record the
application revision and immutable input or configuration identifiers in the
job output. `set -euo pipefail` catches many scripting errors, but it can also
expose commands that legitimately return non-zero; handle those cases locally
and intentionally.

### Choose output locations deliberately

Write logs where they will survive the job and where you can find them by job
ID. Avoid sending high-volume temporary I/O to a metadata-sensitive home or
shared project filesystem.

For suitable workloads, stage inputs to node-local scratch, run there, and copy
results back to durable storage. Ensure that stage-out also runs on expected
termination paths, and validate it with a pilot. Node-local data normally
disappears when the allocation ends.

For long runs, prefer application-native checkpoints and restart files. They
are usually more portable and scientifically inspectable than process-level
checkpointing. Tools such as DMTCP can be useful only when the site supports
them and a representative pilot proves compatibility; MPI, GPU, licensed,
networked, and filesystem-heavy applications can be problematic.

## Quote the exact workload

If the profile provides a site quote helper, quote the same `sbatch` shape you
intend to validate:

```console
hpc --profile example quote sbatch \
    --account=project123 \
    --partition=cpu \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=4 \
    --mem=8G \
    --time=00:10:00 \
    simulation.sbatch
```

An account is mandatory for quoting. A quote is cost evidence, not scheduler
validation or authorization. Re-quote when the duration, resource shape,
array size, or number of separate submissions changes.

## Preview and validate

Assume the script is already present in a remote project directory. First
preview the command that `hpc` would run:

```console
hpc --profile example --dry-run submit \
    --directory '$VSC_DATA/projects/simulation' \
    --test-only \
    simulation.sbatch
```

Then ask Slurm to validate it without enqueueing the job:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --test-only \
    simulation.sbatch
```

`--test-only` uses Slurm's submission validation. It can catch malformed or
unavailable resource requests, but it does not execute the script. It therefore
cannot prove that modules load, input files exist, imports succeed, the program
uses its allocation, or output is scientifically correct.

After validation, submit a deliberately small representative pilot:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    simulation.sbatch
```

A successful real submission is added to the local submission log. If the
remote response cannot be parsed, `hpc` warns that tracking failed; the job may
still have been submitted, so inspect the queue before retrying.

### Use `--validate-first` carefully

This shortcut performs Slurm validation and, if it succeeds, immediately makes
the real submission:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --validate-first \
    simulation.sbatch
```

There is no confirmation pause between the two operations. Use separate
`--test-only` and real-submission commands when you need to inspect the result,
obtain approval, or revise a cost quote between validation and enqueueing.

## Override script directives

The submit command exposes common `sbatch` options, including:

- policy: `--account`, `--cluster`, `--partition`, `--qos`, `--reservation`;
- shape: `--nodes`, `--ntasks`, `--ntasks-per-node`, `--cpus-per-task`;
- memory: `--mem`, `--mem-per-cpu`;
- GPU: `--gres`, `--gpus`, `--gpus-per-node`, `--gpus-per-task`, `--gpu-bind`;
- lifecycle: `--time`, `--dependency`, `--array`;
- identity and output: `--job-name`, `--output`, `--error`, `--export`.

For example, shorten the script's time limit for a pilot:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --time 00:02:00 \
    --test-only \
    simulation.sbatch
```

Command-line `sbatch` options override corresponding `#SBATCH` directives. This
is useful for controlled experiments but can make provenance harder to read.
Record material overrides with the run metadata, and do not use them to conceal
that the checked-in script requests a different workload.

For array index mapping, concurrency caps, task-specific logs, and selective
retries, continue with [Job arrays and parameter sweeps](job-arrays.md).

Do not specify both `--mem` and `--mem-per-cpu` unless the site's Slurm
configuration explicitly permits and defines that combination. Prefer the
single expression that matches how the application consumes memory.

## Run a GPU pilot

A simple one-GPU script might begin:

```bash
#!/bin/bash -l
#SBATCH --job-name=gpu-pilot
#SBATCH --account=project123
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gpus=1
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.err

set -euo pipefail

module purge
module load cuda/13.0

nvidia-smi
python gpu_simulation.py --steps 10
```

GPU request syntax varies by site and Slurm configuration. Some sites require
`--gres=gpu:<type>:<count>` or a particular GPU partition/QoS instead of, or in
addition to, `--gpus`. Follow the local reference and validate the exact shape.

The pilot should verify device visibility, software compatibility, memory use,
output correctness, and whether the CPU-to-GPU ratio is reasonable. A hardware
probe establishes device capabilities; it does not establish application
performance.

## Scale only after the pilot

Before increasing nodes, tasks, GPUs, array size, or run count:

1. confirm the pilot's scientific output;
2. inspect elapsed time and peak memory;
3. verify process, thread, GPU, and affinity behavior;
4. check I/O volume and file counts;
5. revise the time and memory request using evidence;
6. revalidate and re-quote the production shape.

For parameter sweeps or many independent inputs, use a job array rather than a
manual burst of submissions, but first verify one representative task. Array
size and concurrent-task limits are site policy, and the total charge scales
with the number of tasks.

## Monitor the job

While the job is pending or running:

```console
hpc --profile example jobs --cluster example-cluster
hpc --profile example job 123456 --cluster example-cluster
```

If configured, the site's queue helper may provide additional occupancy
context:

```console
hpc --profile example queue
```

After the job leaves the queue, use accounting:

```console
hpc --profile example sacct 123456 --cluster example-cluster
```

Also inspect the standard-output and standard-error files. Scheduler state can
show that a job failed, timed out, or exceeded memory, but application logs
usually explain where and why.

Review the local tracking record with:

```console
hpc --profile example submissions list
hpc --profile example submissions observe <run-id>
```

See [Submission tracking](submissions.md) for annotations and local lifecycle
management. Closing a local record does not cancel a Slurm job.

## Diagnose common outcomes

| Symptom | Evidence to inspect | Likely next action |
| --- | --- | --- |
| Job remains pending | `hpc job`, pending reason, live partition/QoS limits | Correct an invalid request or wait; do not switch policy fields without authorization. |
| Account or QoS rejected | test-only output, associations, site allocation portal | Confirm the permitted combination with authoritative site evidence. |
| `OUT_OF_MEMORY` | `sacct`, application memory logs, pilot measurements | Reduce memory use or request a justified larger amount; check per-node versus per-CPU semantics. |
| `TIMEOUT` | `sacct`, checkpoints, progress rate | Use a measured time limit, reduce the unit of work, or add tested restart support. |
| Module or command not found | job output, `module-spider`, login-shell behavior | Load explicit compatible versions and reproduce the non-interactive environment. |
| Input or output path missing | job output, remote working directory, storage availability | Use absolute or deliberately relative paths and create bounded output directories before submission. |
| GPU not visible or incompatible | job output, GPU request, module/toolkit version, hardware reference | Validate site-specific GPU syntax and software/device compatibility. |
| Job completes but result is wrong | application logs, checks, reference output, configuration provenance | Treat this as an application-validation failure; scheduler success is not scientific correctness. |

When a run fails, preserve its script, exact overrides, logs, job ID, relevant
environment details, and accounting output. That evidence is more useful than
an immediate resubmission with larger resources.

## Completion checklist

A job workflow is complete when:

- the account and policy fields are authorized;
- the resource shape matches application behavior;
- Slurm validation succeeds;
- a representative pilot produces correct output;
- the production shape has been re-quoted where applicable;
- job ID, script revision, inputs, configuration, environment, and overrides
  are recoverable;
- scheduler state, accounting, and application logs have been checked;
- durable results and checkpoints have been staged to the intended storage.

The core CLI intentionally has no cancellation command. Use the site's
documented `scancel` workflow when cancellation is necessary, verify the exact
job ID and cluster first, and do not confuse remote cancellation with local
submission-log maintenance.

Continue with [Tracking work from submission to analysis](submissions.md) to
record result collection, analysis, failure triage, and closure after the
scheduler lifecycle ends.
