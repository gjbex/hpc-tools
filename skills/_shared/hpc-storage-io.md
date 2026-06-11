# HPC Storage And I/O

Use this reference for conceptual storage choices, quota interpretation, local
scratch handling, and shared-filesystem search hygiene.

## Filesystem Roles

Identify home, project/data, shared scratch, archive, and node-local scratch
separately. Do not assume home or data filesystems are suitable for heavy job
I/O; on many HPC systems they are NFS-mounted and not intended for parallel
reads and writes.

Use scratch filesystems for jobs with parallel I/O or heavy temporary I/O when
site documentation or profile references identify them as appropriate.

## Quotas

Treat quota warnings seriously:

- block quota can block clones, builds, and generated output;
- file-count quota can fail jobs even when block usage is below quota;
- summarize both block usage and file-count usage when either is near or over
  quota.

For cleanup requests, first report the target path, approximate size,
filesystem, and the quota or operational pressure the cleanup would address.
Do not delete files or environments unless the user explicitly asks.

## Node-Local Scratch

For workloads with many frequent reads and writes, consider node-local scratch
when the storage reference shows SSD or NVMe local scratch. Local scratch exists
only for the job allocation, so job scripts must stage inputs in, stage outputs
out, and preserve useful partial output with traps or periodic checkpoint and
stage-out logic.

Use the site-provided node-local scratch variable when one exists. Do not
hardcode paths in generic skills. Treat local scratch capacity as shared node
state, not scheduler-reserved capacity.

## Shared Filesystem Search Hygiene

Avoid broad recursive searches on HPC filesystems. Do not run blind `find`
searches from top-level shared storage roots such as `VSC_DATA`, `VSC_SCRATCH`,
project, data, scratch, or archive directories; these trees often contain many
files and can create heavy metadata load. `VSC_HOME` is usually smaller but
should still not be searched blindly.

Ask the user for a narrower path, job ID, directory name, or filename pattern
before searching. If a search is truly necessary, constrain it to a known
narrow directory and use cheap checks such as `ls`, `test -e`,
`du -sh <specific-path>`, or a bounded
`find <specific-path> -maxdepth <N> ...`.

## Artifact Analysis

For benchmark, sweep, and probe workflows, transfer compact CSV, JSON, logs, and
summary files locally for analysis when possible. Keep raw probe or job output
outside durable profile reference directories, then consolidate the conclusions
into profile references under the hpc-tools config directory.
