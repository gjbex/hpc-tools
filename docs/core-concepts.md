# Core concepts and safety

The difficult part of remote HPC work is rarely the spelling of one command.
The real problem is preserving the context in which that command is valid:
which system, account, filesystem, software environment, resource shape, and
stage of the workflow it belongs to.

`hpc-tools` makes that context explicit, but it does not replace judgement.
This chapter explains the model users should have before relying on higher-level
commands or agent-assisted workflows.

## Three execution locations

An hpc-tools workflow normally crosses three locations:

1. **Operator machine** — may run `hpc`, stores configuration and durable
   records, and may hold source code or compact result artifacts.
2. **Login node** — receives commands through SSH or runs them directly when
   hpc-tools itself is installed there. It exposes site modules and storage and
   runs Slurm client commands such as `sbatch`, `squeue`, and `sacct`.
3. **Compute node** — executes the scheduled job inside a Slurm allocation.

A command succeeding on the login node does not prove that the same software,
file, network route, GPU, or environment will exist on a compute node. Package
installation and hardware probes should therefore be tested in the execution
context that matters.

The login node is also not a substitute compute node. Use it for bounded
inspection, file management, configuration, and lightweight builds allowed by
site policy—not for unallocated production computation.

## Profiles select site context

A profile is a named collection of cluster and site metadata. For the default
SSH executor it defines either an `ssh_target` or a `host`; a profile used only
with the local executor may omit both. It can also define:

- SSH options and the remote login shell;
- a default remote project directory;
- site-specific quota, queue, balance, statement, and quote commands;
- hardware, Slurm, storage, and status sources;
- a shared reference set;
- a default Slurm cluster;
- an email address for generated probe notifications.

The configuration path is resolved in this order:

1. explicit `hpc --config <path>`;
2. `HPC_TOOLS_CONFIG`;
3. `$XDG_CONFIG_HOME/hpc-tools/config.toml`;
4. `~/.config/hpc-tools/config.toml`.

The profile is selected by `--profile`, then by `default_profile`. If neither
is set and the configuration contains exactly one profile, hpc-tools selects
that single profile. With multiple profiles and no default, it refuses to
guess.

A profile is operational configuration, not a credential store. Prefer an SSH
alias that already implements keys, agents, jump hosts, and other authentication
policy. Do not put passwords or private keys in `config.toml`.

## Executors separate transport from cluster context

For a profile using:

```toml
ssh_target = "example"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
```

hpc-tools uses the SSH executor by default. It constructs an SSH invocation that
runs the requested command through `bash -l -c` on `example`. The login shell is
important on sites where modules, storage variables, or Slurm helpers are
initialized by shell startup files.

If hpc-tools already runs on a login node, select the local executor explicitly:

```bash
hpc --executor local --profile example doctor
```

The local executor invokes the same configured login shell on the current host,
without SSH. This keeps command construction and profile context shared between
laptop and login-node deployments. `HPC_TOOLS_EXECUTOR=local` provides the same
selection for a process, including a long-running MCP server.

It also creates a diagnostic distinction:

- with the SSH executor, if `ssh example` fails, fix SSH before hpc-tools;
- if interactive SSH works but `hpc doctor` fails, inspect the non-interactive
  login shell and its startup configuration;
- if the login-node check succeeds but the job fails, inspect the compute-node
  environment and job script.

The configured `login_shell` must end in `-c`. hpc-tools quotes its arguments,
but a command intentionally passed to `hpc run` is still interpreted by the
selected shell.

Executor selection is not a capability policy. The local executor does not
prove that it is running on a login node, confine the process, or restrict MCP
tools. An unattended Slurm-job deployment needs a separate server-side policy
and resource delegation; selecting `local` alone is insufficient.

## Local and remote path expansion differ

Values such as `$VSC_DATA/Projects` and `$HOME/run` are often meaningful only
on the cluster. Quote them in the local shell when passing them to hpc-tools:

```bash
hpc --profile example storage inspect '$VSC_DATA/Projects/demo'
hpc --profile example submit --directory '$HOME/run' job.slurm
```

The quotes prevent premature local expansion. The remote login shell can then
expand the variables.

An unquoted `$HOME` may silently become the local home directory before
hpc-tools sees it. Conversely, a relative remote path is relative to the
working directory selected by the remote command, not necessarily the local
directory from which `hpc` was invoked.

## Commands can depend on profile capabilities

Not every cluster exposes the same helper commands. Profile fields declare
optional capabilities:

| Profile field | Enables or informs |
| --- | --- |
| `quota_command` | `hpc quota` and the quota part of status |
| `queue_command` | `hpc queue` |
| `sam_balance_command` | `hpc balance` and the balance part of status |
| `sam_statement_command` | `hpc statement` |
| `sam_quote_command` | `hpc quote` |
| hardware or Slurm reference metadata | `hpc hardware` context |
| `status_url` | the service-status part of `hpc status` |

When a selected profile lacks a capability, the corresponding command may be
hidden from profile-specific help or rejected. Do not work around that by
inventing a command from another site; configure the correct site helper or use
the cluster's documented procedure.

## Slurm requests are resource shapes

A Slurm submission is more than a script name. Its *resource shape* includes
the account, cluster, partition, QoS or reservation, walltime, nodes, tasks,
CPUs, memory, GPUs, job count, and array width.

Those dimensions interact. For example:

- increasing walltime can change both schedulability and cost;
- `--mem` and `--mem-per-cpu` express different contracts;
- tasks and CPUs per task distinguish process parallelism from threads;
- a GPU count without the correct partition or binding may be invalid;
- an array of 1,000 small tasks is still a 1,000-job workload;
- a cluster federation may require an explicit cluster even when a partition
  name looks familiar.

Use `hpc slurm-limits` and site documentation before choosing the shape.
Validation answers whether Slurm accepts a request at that moment; it does not
answer whether the request matches the program's parallelism or scientific
needs.

## Accounts are an authorization boundary

A Slurm account is not merely a formatting option. It identifies the project
or allocation charged for a job. When more than one account is possible,
hpc-tools and an assisting agent should not guess.

Before submission:

1. identify the authorized account;
2. determine whether the site requires a cluster, partition, QoS, or
   reservation with it;
3. quote the complete resource shape where a site quote helper exists;
4. re-quote when a cost-relevant dimension changes.

A quote does not grant permission to charge the account. It is an estimate or
policy check produced by the site helper.

## Durable context has several layers

Keep the following state classes distinct:

| State | Typical location | Examples |
| --- | --- | --- |
| installed software | pipx environment or Codex cache | `hpc`, bundled CLI plugins, installed Codex plugin |
| durable local user state | `~/.config/hpc-tools/` or XDG equivalent | profiles, references, reference sets, submission log |
| repository examples | this source checkout | sample profiles, job scripts, sample probe results |
| remote working state | target cluster | checkouts, job scripts, environments, raw outputs, probe results |
| live external state | Slurm and site services | pending jobs, allocation balances, current outages |

Repository examples are templates, not the long-term home for a user's cluster
references. Conversely, raw probe directories and large results do not belong
in the local configuration tree. Store concise, sourced summaries locally and
retain large artifacts in an appropriate project or archival location.

## References preserve stable cluster facts

Profiles can point to Markdown summaries of hardware, Slurm, and storage
documentation. A shared reference set packages cluster-wide facts for reuse by
multiple profiles without including user-specific SSH targets, email addresses,
account balances, or submission history.

A good reference records:

- the fact and its operational interpretation;
- the source URL or probe provenance;
- the date or context in which it was verified;
- important limitations or node-class differences.

References can become stale. Treat a status page or current Slurm query as live
evidence and a consolidated Markdown file as durable background. When they
conflict, investigate rather than silently preferring whichever is convenient.

See [Cluster references and sharing](reference-sets.md) for the sharing boundary.

## The submission log is an event stream

Successful real `hpc submit` operations are recorded locally, normally in:

```text
~/.config/hpc-tools/submissions.jsonl
```

The log is append-only. It records events such as submission, observation,
collection, analysis, and closure, then derives the current workflow state by
replaying them.

This is not a mirror of Slurm and not a result-transfer system:

- `observe` appends a scheduler snapshot;
- `mark-collected` records a path but does not copy it;
- `mark-analysed` records an analysis artifact but does not create it;
- `close` marks the workflow handled but does not cancel a job or delete data.

If a successful `sbatch` response cannot be parsed, hpc-tools warns that the job
was not logged. The remote submission may still exist, so record its job ID
before retrying anything.

See [Submission tracking](submissions.md) for the state model.

## Safety controls and their limits

### `--dry-run` previews selected execution

For a cluster command, global `--dry-run` prints the selected executor's command
rather than executing it:

```bash
hpc --profile example --dry-run storage inspect '$VSC_DATA/project/run'
```

It verifies command construction, not remote validity. The preview does not
prove that a path exists, an account is authorized, or a job will run.

For the default executor this is an SSH preview; for `--executor local` it shows
the local login-shell invocation. Do not assume it disables local commands that
write files, such as packaged-asset generation. Read the individual command
help before invoking a local write.

### `--test-only` asks Slurm not to enqueue

For submissions:

```bash
hpc --profile example submit --test-only job.slurm
```

runs `sbatch --test-only` with the same supplied overrides. It checks scheduler
acceptance without creating a queued job. It cannot execute application code or
validate runtime inputs.

### `--validate-first` is validation followed by submission

For a real submission:

```bash
hpc --profile example submit --validate-first job.slurm
```

hpc-tools first runs `sbatch --test-only`. If that succeeds, it immediately runs
the real `sbatch`. There is no confirmation prompt between the two commands.
Use `--dry-run` and a separate `--test-only` invocation when a human review
point is required.

### MCP confirmation is another boundary

MCP local-write and remote-install tools require `confirm=true`, and remote
installs preview by default. MCP submission additionally requires matching
quote and validation evidence for the same profile, account, job script,
directory, and resource shape.

Confirmation tells the server that the client requested execution. It proves
neither that a human approved the action nor that the underlying scientific or
operational choice is sound; the MCP client must enforce its own approval and
authorization policy. See [MCP integration](mcp.md).

## Classify an operation before running it

| Class | Examples | Principal risk |
| --- | --- | --- |
| local read | `hpc paths`, `hpc submissions list` | stale or misunderstood context |
| remote read | `doctor`, `jobs`, `slurm-limits`, bounded storage inspection | load, privacy, or misleading snapshots |
| local write | writing a probe or container bundle, updating references | overwriting or misplacing local artifacts |
| remote write | cloning a repository, installing a probe or container bundle | modifying the wrong directory or filesystem |
| scheduler action | submitting a job or installation job | charging an account and consuming capacity |
| arbitrary remote command | `hpc run` | whatever the supplied shell command can do |

The generic `hpc run` command is intentionally flexible and therefore cannot
provide task-specific safeguards. Preview it, quote shell metacharacters
carefully, and do not use it as a shortcut around a safer bounded command.

## Pilot before scaling

Validation catches syntax and some policy failures; a pilot catches runtime
assumptions. Before a broad array, multi-node run, long reservation, or costly
GPU sweep:

1. run the smallest scientifically meaningful case;
2. confirm inputs, environment, logs, outputs, and checkpoint behavior;
3. inspect elapsed time and memory rather than trusting requested values;
4. update the quote for the intended production shape;
5. scale in stages when the cost or failure radius is material.

A successful one-task pilot does not by itself validate parallel scaling, but a
failed pilot is much cheaper evidence than a failed full sweep.

## Use shared filesystems deliberately

Home, project, data, scratch, and node-local storage have different lifetime,
quota, sharing, and performance contracts. Discover them instead of assuming
that directory names have universal meaning.

Avoid blind recursive scans at the top of a shared filesystem. Narrow the
operation by run directory, job ID, filename pattern, or known project path.
For I/O-heavy jobs, consider staging inputs to node-local scratch and copying
needed outputs back to persistent storage, with failure-aware cleanup and
stage-out logic.

## Preserve reproducibility beyond hpc-tools

The tool records useful operational context, but a reproducible scientific run
usually also needs:

- the source revision;
- the complete job script and effective command-line overrides;
- module or container versions;
- environment or dependency lock information;
- input identities and checksums where appropriate;
- random seeds and application configuration;
- relevant hardware or node-class context;
- result and analysis artifact locations.

Do not treat a job ID or submission-log entry as a complete provenance record.

## A pre-submission checklist

Before a consequential job, confirm:

- **target** — correct profile, cluster, partition, and remote directory;
- **authority** — correct account and any required QoS or reservation;
- **shape** — nodes, tasks, CPUs, memory, GPUs, walltime, and job count;
- **evidence** — current quote where available and successful validation;
- **runtime** — modules, environment, input paths, output paths, and
  checkpointing;
- **scale** — a relevant pilot has succeeded;
- **follow-up** — job ID, logs, result location, and collection plan are known.

If one of these remains ambiguous, stop before submission. A scheduler accepting
the request is not a substitute for resolving the ambiguity.
