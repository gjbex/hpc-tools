# Troubleshooting

Diagnose hpc-tools by layers. A failure reported by the CLI can originate in
the local installation, configuration, SSH, login-shell initialization, site
helpers, Slurm policy, application, filesystem, or optional agent integration.
Changing several layers at once makes the result harder to interpret.

Start with the smallest failing command, preserve its complete output, and
compare it with a direct authoritative check where possible.

## Use a layer-by-layer checklist

1. **Installation** — which executable and package version are running?
2. **Configuration** — which config file and profile were resolved?
3. **Command construction** — what does `--dry-run` show?
4. **SSH** — does the same target work directly without hpc-tools?
5. **Remote shell** — are modules and site variables initialized?
6. **Site capability** — is the configured helper current and permitted?
7. **Slurm** — what do queue, pending reason, validation, and accounting say?
8. **Application** — what do standard output, standard error, and result checks
   say?
9. **Local lifecycle** — does the submission database describe the same job?
10. **Agent layer** — did Codex or MCP receive the same profile, environment,
    command, and evidence?

Do not solve a diagnosis by disabling host-key checking, broadening filesystem
permissions, selecting another account, requesting more resources, or using
`force` until evidence identifies that change as appropriate.

## `hpc` is not found

Inspect installation and command resolution:

```console
command -v hpc
pipx list
pipx ensurepath
```

Start a new shell if `pipx ensurepath` changed shell configuration. If both a
pipx and editable installation exist, `command -v hpc` identifies the one
actually executed. Source edits do not update a release-style `pipx install .`
snapshot.

Install the normal released CLI with:

```console
pipx install hpc-tools
hpc --help
hpc paths
```

Do not install the Codex plugin as a substitute; it does not provide the
executable.

## Configuration cannot be loaded

Show location rules without requiring a profile:

```console
hpc paths
```

The effective config is selected by explicit `--config`, then
`HPC_TOOLS_CONFIG`, then `$XDG_CONFIG_HOME/hpc-tools/config.toml`, then
`~/.config/hpc-tools/config.toml`.

Check for an unintended environment override:

```console
env | grep '^HPC_TOOLS_CONFIG=\|^XDG_CONFIG_HOME='
hpc --config ./candidate-config.toml --profile example --dry-run doctor
```

Common configuration errors are:

- invalid TOML quoting or table syntax;
- no `[profiles.<name>]` table;
- a `default_profile` that is not defined;
- neither `ssh_target` nor `host` in a profile used with the SSH executor;
- non-string optional fields;
- `login_shell` not ending in `-c`;
- a reference path that exists only on another machine.

Use an explicit candidate file to diagnose it rather than overwriting the
normal config. Do not post an unsanitized config publicly; it can contain
hosts, usernames, email addresses, paths, and site commands.

## A profile cannot be selected

Run:

```console
hpc --profile example --help
```

With multiple profiles, hpc-tools refuses to guess unless `default_profile` is
set. Check spelling and table nesting. A profile name is the suffix of
`[profiles.<name>]`, not its SSH alias unless you deliberately made them equal.

When testing another configuration tree, pass `--config` and `--profile`
together so the profile is resolved from the intended file.

## A documented command is missing

Some commands appear only when the selected profile declares a capability:

- `quota` needs `quota_command`;
- `queue` needs `queue_command`;
- `balance`, `statement`, and `quote` need their corresponding accounting
  commands;
- `hardware` needs reference or source context.

Compare:

```console
hpc --profile example --help
hpc plugins list
```

The bundled `python`, `r`, `cxx`, and `benchmark` commands come from Python
entry-point plugins installed with the package. They are unrelated to whether
the Codex plugin is installed.

Do not copy a site helper command from another cluster merely to make a command
appear. Verify its syntax, output, and authorization locally first.

## SSH works interactively but not through hpc-tools

Compare the same target and constructed command:

```console
ssh example-login
hpc --profile example --dry-run doctor
hpc --profile example doctor
```

Check:

- the profile resolves the same SSH alias, user, host, port, jump host, and
  identity as the direct command;
- the Codex or MCP process inherited the required SSH-agent environment;
- host-key prompts and multifactor authentication can be handled in the
  execution context;
- `ssh_options` did not override a working `~/.ssh/config` setting;
- the remote account is not blocked by maintenance or a login gate;
- the command does not require a terminal when hpc-tools invokes SSH
  non-interactively.

Keep complex connection policy in `~/.ssh/config` where possible. Do not fix
host-key failures with `StrictHostKeyChecking=no`; verify the host identity and
known-host entry.

## Remote variables or modules are absent

The default profile shell is:

```toml
login_shell = ["bash", "-l", "-c"]
```

Inspect the environment seen by hpc-tools:

```console
hpc --profile example site-env
hpc --profile example module-spider GCC
```

Compare with a non-interactive login shell through the same SSH target. Shell
startup files often contain interactive-only guards; the module setup or site
variables may lie below a premature `return`.

Protect remote variables from local expansion:

```console
hpc --profile example storage inspect '$VSC_DATA/projects'
```

Single quotes ensure the local shell passes `$VSC_DATA` to the remote shell.
If double quotes or no quotes are used, a local value—or an empty string—can be
substituted before SSH.

Do not hard-code a variable's value from one user or cluster into generic
documentation or configuration. Verify where it is defined and whether it is
available in batch jobs as well as login shells.

## Modules cannot be found or loaded

Search before loading:

```console
hpc --profile example module-spider Python
hpc --profile example module-spider OpenMPI
```

Module availability can depend on a cluster, node generation, prerequisite
module, or hidden compatibility hierarchy. Read the complete spider output and
test the exact load sequence in the intended context.

If an interactive load works but a batch job fails, compare:

- `#!/bin/bash -l` and shell initialization;
- `module purge` and load order;
- exact module versions rather than defaults;
- cluster or architecture modules;
- the node class used by the job;
- environment export settings supplied to `sbatch`.

A module name proves catalogue presence, not ABI compatibility with an existing
venv, R library, executable, MPI, or CUDA stack.

## Slurm rejects an account, partition, QoS, or reservation

Run current discovery for the exact cluster and partition:

```console
hpc --profile example slurm-limits \
    --cluster example-cluster \
    --partition cpu
```

Then validate the exact request:

```console
hpc --profile example submit \
    --directory '$VSC_DATA/projects/simulation' \
    --account project123 \
    --cluster example-cluster \
    --partition cpu \
    --test-only \
    simulation.sbatch
```

Check user/account associations, allowed partitions, QoS combinations,
reservations, time and memory limits, GPU syntax, and site allocation status.
The account with the largest balance is not automatically authorized for this
work.

Do not remove policy options one by one until Slurm accepts the request. That
can silently move work to an unintended allocation or partition. Resolve the
permitted combination from current site evidence or support.

## A job remains pending

Inspect live queue state and the one job:

```console
hpc --profile example jobs --cluster example-cluster
hpc --profile example job 123456 --cluster example-cluster
```

The pending reason can indicate priority, resources, dependency, association or
QoS limits, reservation timing, licences, maintenance, or an unavailable node
shape. A concurrency-capped array can also have intentionally pending elements.

Do not assume a long wait means the request is invalid. Conversely, do not
request more resources to escape the queue: larger or rarer shapes often wait
longer. Compare the request with current limits and decide whether a smaller
scientifically valid pilot or another documented partition is appropriate.

When cancellation is necessary, verify the job ID and cluster, preview the
request with global `--dry-run`, and then use `hpc cancel`. A successful request
must still be confirmed through queue state or accounting.

## A completed job has no useful result

Query accounting and inspect both logs and application output:

```console
hpc --profile example sacct 123456 --cluster example-cluster
hpc --profile example submissions list
```

Slurm `COMPLETED` normally means the batch script returned success. It does not
prove that the application ran the intended workload, produced every expected
file, or passed scientific checks.

Check the executable revision, inputs, configuration, working directory,
module or image, exit handling, stage-out, output naming, disk/quota state, and
application invariants. `set -euo pipefail` catches many shell errors but does
not turn a weak application success condition into a strong one.

Do not mark results collected until the artifact has been inspected.

## A probe produces incomplete output

First establish scheduler state and retain the entire probe directory. Probe
scripts often continue after an optional tool fails so that other evidence is
not lost. A successful Slurm state can therefore coexist with missing-tool or
permission errors inside individual files.

Check:

- the job's standard output and error;
- `probe-manifest.tsv` status rows;
- files containing `command not found`, permission, timeout, or unsupported
  hardware messages;
- requested partition, node class, CPUs, GPUs, memory, and exclusivity;
- whether the tool exists only under a module;
- whether the observation can be generalized beyond that node.

Do not rerun a broad probe until the missing evidence is both necessary and
collectable. Use a targeted follow-up and preserve failed output as provenance.

## Package installation fails on a compute node

Determine which layer failed:

| Evidence | Likely layer |
| --- | --- |
| import or namespace missing | language package or wrong runtime environment |
| compiler/header/linker error | native dependency or incompatible toolchain |
| download or DNS error | compute-node network policy or unavailable mirror |
| quota, inode, or no-space error | unsuitable environment/cache location |
| illegal instruction or loader error | architecture or ABI mismatch |
| module unavailable in the job | batch environment or node-class mismatch |

Inspect the complete installation log and use `hpc python verify-install` or
`hpc r verify-install` only on output produced by the corresponding workflow.
These parsers do not perform a new remote import.

Do not install into system Python/R, broaden permissions, or add unreviewed
repositories. Search compatible site bundles first, then prepare a small
project environment or reviewed container as appropriate.

## Submission-database state looks stale or wrong

List active and complete views:

```console
hpc submissions list
hpc submissions list --all
```

Then observe through the profile that submitted the job:

```console
hpc --profile example submissions observe <run-id>
```

Remember:

- `RUN_ID` is local; `JOBID` belongs to Slurm;
- observation uses accounting, which can lag and temporarily report `UNKNOWN`;
- jobs submitted outside hpc-tools are not discovered automatically;
- a parsed-submission failure can leave a real job without a local record;
- `mark-collected` and `mark-analysed` trust the supplied text path;
- `close` is terminal in the local view and does not cancel the job;
- logs are not synchronized between workstations.

Do not edit or reorder `submissions.sqlite3` as a routine fix. Preserve it, check
the event stream and active config path, and close or supersede records
deliberately.

## A restricted unattended agent failed

Start with the parent job's scheduler state and append-preserved outer logs,
then build the supported joined audit view:

```console
sacct -j <parent-job-id> -o JobID,State,ExitCode,Elapsed,NodeList
less restricted-agent-<parent-job-id>.err
less restricted-agent-<parent-job-id>.out
hpc agent audit --ledger /protected/delegations.sqlite3 \
    --delegation-id <delegation-id>
```

The audit report points to each generation's `provenance.json`, structured
`codex-events.jsonl`, diagnostic log, owned delegated job IDs, server-generated
output directories, wrapper status, and cleanup record. Use `hpc agent export`
to preserve a private mode-`0600` incident artifact. Check live `squeue` and
terminal `sacct` state separately; the audit command deliberately performs no
remote calls or mutations.

## The Codex plugin is installed but workflows are absent

Check:

```console
codex plugin list
test -f ~/plugins/hpc-tools/.codex-plugin/plugin.json
test -f ~/plugins/hpc-tools/skills/hpc-slurm-jobs/SKILL.md
```

Confirm that the personal marketplace points at the intended checkout. After
an update, rerun the registration/cachebuster workflow from [Installation and
maintenance](installation.md) and start a new Codex task.

The plugin can be present while `hpc` is missing; install the Python package
separately. It can also provide skills while MCP startup fails.

## MCP cannot start or expose tools

Check the server command and package installation:

```console
command -v hpc-mcp
command -v hpc
pipx list
hpc paths
```

Common causes are:

- the package was installed without the `mcp` extra;
- `hpc-mcp` is not on the `PATH` inherited by the client;
- the client's MCP entry does not invoke the expected command;
- the client/task predates plugin installation;
- the plugin checkout and Python package expose different tool versions;
- the server sees another `HPC_TOOLS_CONFIG` or `XDG_CONFIG_HOME`;
- configuration fails before tool discovery.

Inspect the MCP client logs. A manually launched stdio server may appear to
hang because it is waiting for protocol input. Do not use that alone as proof
of a startup failure.

If submission evidence is rejected, repeat quote and validation in the same
running server process with exactly the same profile, account, script path,
directory, and overrides. Evidence does not survive a server restart because
the process-local signing secret changes. See [MCP integration](mcp.md) for
the evidence limitations.

## Collect useful diagnostic information

Before reporting a bug, collect a small, sanitized bundle of facts:

```console
command -v hpc
hpc --help
hpc paths
hpc plugins list
hpc --profile example --dry-run doctor
hpc --profile example --json doctor
```

Include:

- hpc-tools installation method and version or source commit;
- operating system and Python version;
- exact command with secrets and personal paths redacted;
- complete standard output, standard error, and exit code;
- selected config path and a minimal sanitized profile;
- whether direct SSH succeeds;
- cluster and relevant Slurm job ID;
- scheduler/accounting state and application logs;
- whether the failure occurs in CLI, Codex, MCP, or all three;
- for MCP, client name, server command, discovery logs, and tool parameters
  with sensitive data removed.

Do not include private keys, tokens, passwords, one-time codes, full SSH-agent
state, confidential input data, or an unsanitized configuration/submission database.

Separate a cluster incident from a reproducible hpc-tools defect. A useful
report states what was expected, what happened, which layer failed, and the
smallest safe reproduction.
