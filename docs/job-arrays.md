# Job arrays and parameter sweeps

A Slurm job array submits many instances of one batch script under one parent
job. Arrays suit independent tasks that differ only by an input, parameter set,
or random seed. They reduce submission overhead, but they do not make an
application parallel. Every task still needs a correct resource request, and
the campaign can amplify pressure on filesystems, databases, and licences.

## Decide whether an array is appropriate

Use an array when:

- tasks can run independently and in any order;
- each task has a stable mapping from its index to its inputs;
- each task writes to a distinct output location;
- failed tasks can be repeated without corrupting successful results;
- tasks are long enough to justify scheduler overhead, or can be bundled.

Use Slurm dependencies for a small number of ordered stages and a workflow
system for a larger dependency graph. Do not make array tasks poll for other
tasks' output.

## Establish the task contract

Define what one task means before writing the script:

- the manifest row or parameter represented by an index;
- program, configuration, and immutable input revision;
- CPUs, memory, accelerators, and credible time limit for one task;
- unique output and log names;
- success condition and expected result files;
- whether a retry replaces, resumes, or rejects existing output.

An explicit manifest is safer than deriving filenames from directory order.
For example:

```text
task_id	input_path	output_path
0	inputs/sample-a.nc	results/sample-a.json
1	inputs/sample-b.nc	results/sample-b.json
2	inputs/sample-c.nc	results/sample-c.json
```

This tab-separated example assumes fields contain no tabs or newlines. For
general CSV quoting, parse the manifest in the application or with a CSV
library rather than extending shell parsing.

## Write an array script

This script requires exactly one row for the current index and gives every
task separate logs and results:

```bash
#!/bin/bash -l
#SBATCH --job-name=simulation-sweep
#SBATCH --account=project123
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x-%A_%a.out
#SBATCH --error=logs/%x-%A_%a.err

set -euo pipefail

task_id=${SLURM_ARRAY_TASK_ID:?This script must run as a Slurm array}
manifest=manifests/sweep.tsv

row=$(awk -F '\t' -v id="$task_id" '
    NR > 1 && $1 == id { print; matches++ }
    END { if (matches != 1) exit 1 }
' "$manifest")

IFS=$'\t' read -r manifest_id input_path output_path <<< "$row"
[[ "$manifest_id" == "$task_id" ]] || exit 1

module purge
module load gcc/14.2.0
module load python/3.13.1

export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:?}
mkdir -p "$(dirname "$output_path")"

python simulation.py --input "$input_path" --output "$output_path"
```

`%A` is the parent array job ID and `%a` is the task index. Use both in
log names. Create the remote `logs` directory before submission: Slurm normally
opens its output files before the script can create it.

## Discover array limits

Inspect current limits and the intended partition:

```console
hpc --profile example slurm-limits --cluster example-cluster --partition cpu
hpc --profile example hardware
```

Interpret limits carefully:

- `MaxArraySize=N` normally permits indices `0` through `N-1`; it is not the
  number of tasks allowed to run simultaneously.
- association and QoS limits can separately restrict submitted, pending, or
  running jobs;
- a partition can impose smaller resource limits than the cluster-wide values;
- site policy can be stricter than values visible to an ordinary user.

If a required limit is not visible, consult the site's current documentation
or support service. Do not infer permission from another partition or cluster.

## Pilot a small slice

Validate two tasks with a concurrency cap of one:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --array '0-1%1' \
    --test-only \
    sweep.sbatch
```

Then run the same small slice:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --array '0-1%1' \
    sweep.sbatch
```

`--test-only` checks scheduler acceptance; it does not read the manifest or run
the application. Verify that each pilot selects the intended row, creates
unique complete output, uses the allocation, fits its time and memory request,
and can be retried predictably.

Quote the pilot when a site quote helper exists. Quote again before production
with the full array size and shape. A 1,000-task array is a 1,000-task workload
even if only 20 tasks run concurrently.

## Submit the production array

Slurm supports indices, ranges, lists, strides, and concurrency caps:

```text
0-999%20        indices 0 through 999, at most 20 running at once
0,4,9           three selected tasks
1-100:5%10      every fifth index, at most 10 running at once
```

Submit the reviewed shape:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --array '0-999%20' \
    sweep.sbatch
```

The cap is an upper bound, not a promise of simultaneous starts. Choose it
from evidence about resource use, scheduler limits, licences, external
services, and I/O—not from the desired completion time alone.

## Bundle very short tasks

Thousands of second-long tasks create disproportionate scheduler and
filesystem overhead. Bundle several manifest rows per task when the retry
trade-off is acceptable. A useful starting rule is to aim for tens of minutes
of work per scheduled task, then adjust from site guidance and measurements.
This is a rule of thumb, not a universal minimum.

Keep chunk mapping deterministic and record per-row status. Bundling reduces
overhead but increases work lost when a scheduled task fails.

Some sites provide `atools` commands such as `aenv`, `alog`, `arange`,
`areduce`, `aload`, or `acreate`. hpc-tools does not install `atools`; check the
site's installed version and documentation before relying on its syntax.

## Monitor and diagnose the campaign

Use the parent job ID with normal queue and accounting commands:

```console
hpc --profile example jobs --cluster example-cluster
hpc --profile example job 123456 --cluster example-cluster
hpc --profile example sacct 123456 --cluster example-cluster
```

Accounting may show the parent, elements such as `123456_17`, and step rows.
Separate scheduler state from scientific success: exit code zero does not prove
that output is complete or valid.

The local submission record describes the array campaign, not every element's
lifecycle. Preserve the manifest and use an application result index or array
tool when each element needs independent bookkeeping. See [Tracking work from
submission to analysis](submissions.md).

| Symptom | First check |
| --- | --- |
| Every task fails immediately | Inspect one complete log for a shared script, module, path, or manifest error. |
| Only some indices fail | Compare failed manifest rows with successful rows for input or resource differences. |
| Tasks remain pending | Inspect pending reasons, the concurrency cap, and association/QoS limits. |
| Results overwrite one another | Fix naming and determine whether existing evidence remains trustworthy. |
| Performance collapses at scale | Repeat at lower concurrency and measure shared I/O or service contention. |

## Retry only justified failures

Fix shared defects first, preserve the manifest, and submit explicit indices:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --array '17,42,106-109%2' \
    sweep.sbatch
```

Do not rerun all tasks merely because selecting failures is inconvenient. That
wastes allocation and can overwrite good evidence. Conversely, a shared
software or input-version bug can invalidate nominally successful results too.

Close the campaign only after checking completeness against the manifest,
validating representative outputs, recording retries and exclusions, and
aggregating into a new artifact rather than modifying task results in place.

