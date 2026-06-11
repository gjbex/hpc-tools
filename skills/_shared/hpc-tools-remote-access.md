# HPC Tools Remote Access

Use the installed `hpc` CLI for all remote interaction. Prefer
`--profile <name>` when the user names a cluster/profile; otherwise use the
configured default profile:

```bash
hpc --profile <profile> run '<command>'
```

Commands run through the profile's configured login shell. If SSH prints a
firewall, browser, or login-gate URL, wait for the user to complete that step,
then retry the same command.

## Profile Discovery

Check the selected profile before relying on optional helpers:

```bash
hpc --profile <profile> --help
hpc --profile <profile> --dry-run doctor
```

Use only helpers that appear in help for the selected profile:

- `hpc projects` requires `projects_dir`.
- `hpc quota` requires `quota_command`.
- `hpc queue` requires `queue_command`.
- `hpc balance` requires `sam_balance_command`.
- `hpc statement` requires `sam_statement_command`.
- `hpc quote` requires `sam_quote_command`.
- `hpc hardware` appears when hardware, Slurm, or storage references are configured.

If the profile exposes site context, inspect it before making hardware,
partition, storage, I/O, or scheduler-policy recommendations:

```bash
hpc --profile <profile> hardware
hpc --profile <profile> hardware --source
```

## Command Pattern

Use consolidated commands for standard diagnostics:

```bash
hpc --profile <profile> doctor
hpc --profile <profile> site-env
```

For commands that depend on modules or environment setup, load modules and run
the work in the same remote command:

```bash
hpc --profile <profile> run 'module load <module> && cd <remote-dir> && <command>'
```

Use `--dry-run` when command construction is uncertain or when quoting,
directory selection, or profile expansion needs to be inspected before
execution.

## Safety

Do not delete files, cancel jobs, overwrite environments, or mutate remote
state unless the user explicitly asks for that action. For cleanup requests,
first report the target path, approximate size, filesystem, and the quota or
operational pressure the cleanup would address.

Before submitting jobs on systems with charge accounts, confirm the correct
account when the user has access to multiple accounts. Do not infer it only
from prior jobs or available balance; credits may have monetary value and are
often used for project usage reporting.

When a configured quote helper is available, get a credit-cost quote using the
same account and Slurm resource options that will be used for submission.
Present the estimated maximum cost to the user before submitting the job.

Avoid broad recursive searches on HPC filesystems. Do not run `find` from
top-level shared storage roots such as `VSC_DATA`, `VSC_SCRATCH`, project,
data, scratch, or archive roots; these trees often contain many files and can
create heavy metadata load on shared filesystems. `VSC_HOME` is usually smaller
but should still not be searched blindly. Prefer asking the user for a more
specific path, job ID, directory name, or filename pattern before searching. If
a search is truly necessary, constrain it to a known narrow directory and use
cheap checks such as `ls`, `test -e`, `du -sh <specific-path>`, or a bounded
`find <specific-path> -maxdepth <N> ...`.
