# Everyday cluster operations

The routine `hpc` workflow is deliberately conservative: inspect the selected
cluster, construct a bounded remote command, and keep submission evidence
locally. It is not a general remote shell or an automatic cluster-management
system.

The examples below use an explicit profile. This is slightly more verbose than
relying on a default, but it makes copied commands safer.

## Start with the command context

Show the commands enabled by the profile:

```console
hpc --profile example --help
```

Preview an SSH-backed operation before running it:

```console
hpc --profile example --dry-run storage inspect '$VSC_DATA/project'
```

Use `--json` when another program will consume the result:

```console
hpc --profile example --json doctor
```

Global options belong before the subcommand. `--dry-run` previews remote SSH
commands; it is not a promise that every command is offline or side-effect
free. A command that reads a configured web page, for example, may still make a
local HTTP request.

## Get a daily overview

If the profile has the necessary capabilities, run:

```console
hpc --profile example status
```

The status view combines several independent sources:

- a configured cluster-status web page;
- remote quota information;
- remote account-balance information;
- the local submission log.

This is a convenience summary, not a transactional snapshot. Sources can have
different update times, and the command reports failure when a required piece
is absent or unavailable. Diagnose each source separately rather than assuming
that a failed combined status means the cluster itself is down.

Use the focused commands when you need current evidence:

```console
hpc --profile example doctor
hpc --profile example quota
hpc --profile example balance
hpc --profile example submissions list
```

Commands such as `quota` and `balance` appear only when the selected profile
defines their site-specific helpers.

## Inspect the remote environment

Use `doctor` after an account, SSH, or site-environment change:

```console
hpc --profile example doctor
```

Use `site-env` to inspect common environment variables, helper commands, and
the module system visible in a login shell:

```console
hpc --profile example site-env
```

If results differ from an interactive SSH session, compare how the two shells
are initialized. `hpc` normally uses a login shell, but site dotfiles can still
behave differently in non-interactive use.

## Consult cluster references

Show the configured cluster reference context:

```console
hpc --profile example hardware
```

To inspect provenance instead of rendered reference content:

```console
hpc --profile example hardware --source
hpc --profile example hardware --path
```

Despite the command name, the rendered context can include hardware, Slurm,
and storage references. `--source` reports configured URLs; `--path` reports
local reference paths. They are mutually exclusive. Reference material is
durable context, not proof of current availability. Check live Slurm
information before choosing resources for an important run.

## Check storage without broad scans

Inspect a specific directory or filesystem:

```console
hpc --profile example storage inspect '$VSC_DATA/project'
```

The command reports bounded directory, filesystem, usage, and mount context. It
does not recursively inventory the tree, change permissions, or delete files.

Check site quota information separately when configured:

```console
hpc --profile example quota
```

Use the results to answer different questions:

- `df`-style capacity describes the filesystem as a whole;
- quota output describes your user or project limits;
- `du`-style usage estimates data reachable below the selected path;
- inode or file-count quotas can be exhausted while byte capacity remains.

Do not launch an unbounded recursive scan on a shared filesystem merely to make
these values agree. Large metadata walks can be slow and disruptive.

## Find project workspaces

When `projects_dir` is configured, list its contents with:

```console
hpc --profile example projects
```

Clone a repository into that default root:

```console
hpc --profile example clone \
    https://github.com/example/simulation.git
```

Or select the destination explicitly:

```console
hpc --profile example clone \
    https://github.com/example/simulation.git \
    --directory '$VSC_DATA/projects' \
    --name simulation-test
```

Inspect an existing remote worktree:

```console
hpc --profile example repo status \
    --directory '$VSC_DATA/projects/simulation'
```

Cloning changes remote state. Preview the command and confirm the destination
first. `repo status` is read-only; `hpc` does not automatically pull, merge,
clean, or discard changes.

## Search the module catalogue

Search for modules before hard-coding an environment:

```console
hpc --profile example module-spider gcc
hpc --profile example module-spider openmpi
```

Record explicit, compatible versions in job scripts. Search output shows what
the module system knows about, not necessarily what is supported on every node
class or compatible with an existing environment.

## Observe Slurm work

List current jobs visible to you:

```console
hpc --profile example jobs
```

At a federated site, narrow the cluster when interpreting a job:

```console
hpc --profile example jobs --cluster example-cluster
hpc --profile example job 123456 --cluster example-cluster
```

The queue is the best source while a job is pending or running. Once it leaves
the queue, query accounting:

```console
hpc --profile example sacct 123456 --cluster example-cluster
```

If a site-specific `queue` helper is configured, it may add occupancy or policy
context:

```console
hpc --profile example queue
```

Queue state, accounting state, and output files answer different questions.
Use all three when diagnosing a failure. See [Running Slurm jobs](slurm-jobs.md)
for submission and troubleshooting.

## Review local submission evidence

Successful real submissions are recorded locally. List them with:

```console
hpc --profile example submissions list
```

Observe a known submission or annotate its local lifecycle:

```console
hpc --profile example submissions observe <run-id>
hpc submissions mark-collected <run-id> --path /remote/results/output.dat
hpc submissions mark-analysed <run-id> --path /remote/results/report.md
hpc submissions close <run-id> --reason done
```

The submission log is an audit aid, not scheduler truth. Jobs submitted by
other tools will not appear automatically, and a local annotation cannot alter
the remote job. See [Submission tracking](submissions.md) for the full model.

## Common routines

### Before starting work

```console
hpc --profile example doctor
hpc --profile example quota
hpc --profile example jobs --cluster example-cluster
```

### Before a resource-intensive run

```console
hpc --profile example slurm-limits --cluster example-cluster
hpc --profile example balance
hpc --profile example hardware
```

Then validate and submit a small pilot as described in
[Running Slurm jobs](slurm-jobs.md).

### After a job disappears from the queue

```console
hpc --profile example sacct 123456 --cluster example-cluster
hpc --profile example submissions observe
```

Also inspect the job's standard-output and standard-error files in the remote
working directory.

## Know the boundaries

The core CLI does not provide generic file transfer, arbitrary remote file
deletion, or Slurm job cancellation. Use the site's documented tools for those
operations and verify targets carefully. In particular, do not interpret
`submissions close` as `scancel`: it closes only the local tracking record.

Optional CLI extensions can add domain workflows. Check the selected profile's
help and [CLI plugin system](plugins.md), but do not assume that installing the
Codex plugin also installed every Python CLI extension.

For project environments and remote compilation, continue with
[Software environments and dependencies](software-environments.md) and
[Deploying and building software remotely](remote-builds.md).
