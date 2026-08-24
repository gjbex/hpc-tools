# Reference

This chapter collects the user-visible contracts of hpc-tools in one place.
Use it when you already know the workflow and need an exact command, field, or
file format. For explanations and worked sequences, follow the links to the
task-oriented chapters.

The installed command is the final authority for the installed version:

```bash
hpc --help
hpc <command> --help
hpc <command> <subcommand> --help
```

External packages can add commands through the CLI plugin system, so an
installation may expose more commands than this core reference lists. Inspect
the effective command tree with `hpc --help` and `hpc plugins list`.

## Command form and global options

```text
hpc [--json] [--profile PROFILE] [--config CONFIG] [--dry-run] COMMAND ...
```

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show help for the current command level and exit. |
| `--profile PROFILE` | Select a named profile instead of `default_profile`. If the configuration contains exactly one profile, it is selected when neither option is present. |
| `--config PATH` | Read a particular TOML configuration file. This takes precedence over the default configuration path. |
| `--dry-run` | Print SSH-backed commands instead of running them. It does not turn every local operation into a preview, and `status` can still retrieve a configured web status page. |
| `--json` | Request structured output. Most commands use the generic envelope described under [Output formats](#output-formats); a small set emits command-specific JSON directly. |

Put global options before the command in scripts. The CLI currently accepts
`--json` at other positions too, but relying on conventional option placement
makes invocations easier to read and forward.

## Complete CLI command reference

The syntax below uses `NAME` for a required value and `[NAME]` for an optional
one. Repeated options are explicitly marked.

### Local setup and metadata

| Command | Purpose |
| --- | --- |
| `hpc paths` | Print the active configuration, reference, copied-skill, packaged-template, and uninstall locations. |
| `hpc plugins list` | List core and external CLI plugins. Columns are `NAME`, `VERSION`, `SOURCE`, and `DESCRIPTION`. |
| `hpc plugins info NAME` | Show the name, version, source, and description of one plugin. |

### Shared cluster references

These commands operate on the local reference-set directory. Only `create`,
`attach`, and `detach` need a selected profile.

| Command | Purpose and important options |
| --- | --- |
| `hpc references list` | List installed reference sets. |
| `hpc references show NAME` | Show the resolved files, sources, and metadata for one set. |
| `hpc references validate NAME` | Validate the manifest and required files. |
| `hpc references create NAME [--force]` | Copy the selected profile's hardware, Slurm, and storage references into a new set. `--force` replaces an existing destination. |
| `hpc references export NAME [--output PATH] [--force]` | Write a compressed archive. The default is `./NAME-reference-set.tar.gz`. |
| `hpc references import ARCHIVE [--force]` | Validate and install an archive. Imported text remains untrusted input even when the archive is structurally valid. |
| `hpc references attach NAME` | Set `reference_set = "NAME"` on the selected profile in the active configuration file. |
| `hpc references detach` | Remove `reference_set` from the selected profile. Direct per-profile reference fields remain available. |

See [Cluster references and sharing](reference-sets.md) for precedence,
provenance, safe import, and refresh guidance.

### Cluster inspection

| Command | Purpose and important options |
| --- | --- |
| `hpc doctor` | Show remote identity and whether core Slurm commands are available. |
| `hpc status` | Combine a configured status page, quota, account balance, and active local submissions. Missing configured helpers count as failures. |
| `hpc site-env` | Show selected environment variables, common storage tools, and the module-system version. |
| `hpc hardware [--source | --path]` | Render configured hardware, Slurm, and storage context; restrict output to source URLs or local paths with the optional flags. |
| `hpc storage inspect [PATH]` | Run bounded read-only checks for one remote path; the default is the remote working directory. |
| `hpc quota` | Run the profile's `quota_command`. |
| `hpc module-spider NAME` | Search the remote Lmod module catalogue. |
| `hpc slurm-limits [-M CLUSTER] [-p PARTITION] [--qos QOS]` | Inspect controller, partition, node, QoS, and user-association limits. |

### Remote workspace

| Command | Purpose and important options |
| --- | --- |
| `hpc projects` | List the selected profile's `projects_dir`. |
| `hpc repo status -C DIRECTORY` | Show status, remotes, and latest commit for a remote Git checkout. |
| `hpc clone URL [-b BRANCH] [-C DIRECTORY] [--name NAME]` | Clone a remote repository. The parent directory defaults to `projects_dir`. |
| `hpc run REMOTE_COMMAND` | Run one string through the configured remote login shell. This is an unrestricted escape hatch, not a safety boundary. |

### Packaged probes and containers

Probe directive options are `--account`, `--cluster`/`--clusters`,
`--partition`, `--qos`, `--time`, and `--cpus-per-task`. Add email directives
with `--mail-user ADDRESS`, or use `--mail-notifications` to take the address
from the selected profile's `email` field.

| Command | Purpose and important options |
| --- | --- |
| `hpc write-probe [OUTPUT] [--kind hardware|cuda-device-properties] [--force]` | Write a local probe script or bundle. `OUTPUT=-` is supported for the hardware script. |
| `hpc write-hardware-probe [OUTPUT] [--force]` | Compatibility shorthand for the hardware form of `write-probe`; output defaults to standard output. |
| `hpc install-probe [--kind hardware|cuda-device-properties] [-C DIRECTORY] [--name NAME] [--force]` | Install probe assets on the selected remote profile. |
| `hpc install-hardware-probe [-C DIRECTORY] [--name NAME] [--force]` | Compatibility shorthand for installing the hardware probe. |
| `hpc write-container --kind generic|r|conda OUTPUT [--name NAME] [--force]` | Write a local starter bundle for an Apptainer build job. |
| `hpc install-container --kind generic|r|conda -C DIRECTORY [--name NAME] [--force]` | Install a starter bundle remotely. It does not build the image. |

See [Probes and cluster discovery](probes.md) and
[Container workflows](containers.md) before submitting generated scripts.

### Site accounting and safety helpers

These commands exist only when the selected profile supplies the corresponding
site command. They are adapters around site tooling, not portable Slurm
commands.

| Command | Purpose and important options |
| --- | --- |
| `hpc quote QUOTE_ARGS...` | Pass a submit form and its resource options to `sam_quote_command`. The arguments must include an account option. |
| `hpc balance` | Run `sam_balance_command`. |
| `hpc statement --account ACCOUNT [--start YYYY-mm-dd] [--end YYYY-mm-dd]` | Run `sam_statement_command` for an account and optional date filters. The site helper defines the boundary semantics. |

### Slurm lifecycle

| Command | Purpose and important options |
| --- | --- |
| `hpc submit JOBSCRIPT [-C DIRECTORY] [--test-only] [--validate-first] [SLURM_OVERRIDES...]` | Run `sbatch` from the remote directory. Successful real submissions are appended to the local submission log. |
| `hpc jobs [-M CLUSTER]` | Show the current user's queued and running jobs. Without a cluster override, it shows the clusters visible to the login context. |
| `hpc job JOBID [-M CLUSTER]` | Query one job in the live queue. Completed jobs normally require `sacct`. |
| `hpc queue` | Run the profile's site-specific `queue_command`. |
| `hpc sacct JOBID [-M CLUSTER]` | Show accounting fields for a job: `JobID`, `JobName`, `Partition`, `Account`, `State`, `ExitCode`, and `Elapsed`. |

`JOBSCRIPT` is interpreted relative to `--directory`. `--test-only` validates
without submitting. `--validate-first` first runs `sbatch --test-only` with the
same overrides and submits only after that command succeeds. Neither check
establishes scientific correctness, suitable scaling, or affordable cost.

### Local submission records

Use `--log PATH` immediately after `submissions` to operate on a non-default
event log.

| Command | Purpose and important options |
| --- | --- |
| `hpc submissions [--log PATH] list [--all]` | Replay the event log and list active records; `--all` includes closed records. |
| `hpc submissions [--log PATH] observe [RUN_ID]` | Query `sacct` through the stored profile and append observations for one or all active runs. |
| `hpc submissions [--log PATH] mark-collected RUN_ID --path PATH` | Record where results were collected. This records the claim; it does not copy or verify the results. |
| `hpc submissions [--log PATH] mark-analysed RUN_ID --path PATH` | Record an analysis artifact path. It does not run or validate the analysis. |
| `hpc submissions [--log PATH] close RUN_ID [--reason TEXT]` | Close a record locally. It does not cancel a Slurm job or remove remote files. |

See [Track work from submission to analysis](submissions.md) for the state and
action model.

### Built-in workflow plugins

The following plugins ship with hpc-tools but use the same extension mechanism
as independently installed plugins.

#### Benchmark

| Command | Purpose and important options |
| --- | --- |
| `hpc benchmark summarize TARGET... [--json]` | Summarize numeric timing values found in CSV, JSON, or JSONL files or directories. |
| `hpc benchmark compare BASELINE CANDIDATE [--candidate-threads N] [--json]` | Compare two summaries and optionally calculate candidate parallel efficiency. |

#### C and C++

| Command | Purpose and important options |
| --- | --- |
| `hpc cxx scan TARGET [--json]` | Scan CMake and C/C++ source files for dependency hints. |
| `hpc cxx fetchcontent PACKAGE [--project-option-prefix PREFIX] [--default-off]` | Render a pinned CMake `FetchContent` snippet for a supported small dependency. |

#### Python

`--package` and `--module` can be repeated where shown.

| Command | Purpose and important options |
| --- | --- |
| `hpc python scan TARGET [--json]` | Discover import names locally. |
| `hpc python inspect-deps TARGET [--json]` | Inspect supported dependency files without changing an environment. |
| `hpc python check TARGET [--package NAME]... [--module NAME]... [--json]` | Test imports under a selected remote module stack. |
| `hpc python plan-install TARGET --output FILE --venv PATH --partition NAME [--package NAME]... [--module NAME]... [--cluster NAME] [--job-name NAME] [--time TIME] [--cpus-per-task N] [--arch-guard NAME] [--no-system-site-packages] [--upgrade-pip] [--force]` | Generate, but do not submit, a virtual-environment installation job. |
| `hpc python submit-install JOBSCRIPT -C DIRECTORY -A ACCOUNT [-M CLUSTER] [-p PARTITION] [--reservation NAME] [-t TIME] [-c N] [-N N] [--remote-name NAME] [--skip-quote] [--no-validate-first]` | Stage and submit a generated install job. Quote and validation steps are on by default when available. |
| `hpc python verify-install --job-output PATH --package NAME... [--require-venv-fragment TEXT] [--json]` | Parse a completed job's verification block and check the expected interpreter path. |

#### R

`--package`, `--archive-package`, and `--extra-repo` can be repeated where
shown.

| Command | Purpose and important options |
| --- | --- |
| `hpc r scan TARGET [--json]` | Discover package references locally. |
| `hpc r check TARGET --module NAME [--package NAME]... [--cran-bundle NAME] [--bioc-bundle NAME] [--json]` | Check packages under a remote R and optional bundle-module stack. |
| `hpc r plan-install TARGET --module NAME --output FILE --partition NAME [--package NAME]... [--cran-bundle NAME] [--bioc-bundle NAME] [--cluster NAME] [--job-name NAME] [--time TIME] [--cpus-per-task N] [--library-root-template EXPR] [--arch-guard NAME] [--archive-package PKG=URL]... [--extra-repo NAME=URL]... [--force]` | Generate, but do not submit, an R library installation job. |
| `hpc r submit-install JOBSCRIPT -C DIRECTORY -A ACCOUNT [-M CLUSTER] [-p PARTITION] [--reservation NAME] [-t TIME] [-c N] [-N N] [--remote-name NAME] [--skip-quote] [--no-validate-first]` | Stage and submit a generated install job. Quote and validation steps are on by default when available. |
| `hpc r verify-install --job-output PATH --package NAME... [--require-lib-fragment TEXT] [--json]` | Parse a completed job's verification block and check the expected library path. |

The scanners are conservative aids, not complete dependency resolvers. Dynamic
imports, generated code, compiled system dependencies, and site policy still
require review. See [Software environments and dependencies](software-environments.md)
and [CLI plugin system](plugins.md).

## Command availability by profile capability

Most remote commands need only a valid SSH target. The following commands have
additional conditions:

| Command or group | Required profile field or condition |
| --- | --- |
| `projects`; default destination of `clone` | `projects_dir` |
| `status` | `status_url`; its quota and balance sections additionally use `quota_command` and `sam_balance_command` |
| `quota`; quota section of `status` | `quota_command` |
| `queue` | `queue_command` |
| `balance`; balance section of `status` | `sam_balance_command` |
| `statement` | `sam_statement_command` |
| `quote` and default quote stage of Python/R `submit-install` | `sam_quote_command` |
| probe `--mail-notifications` | `email` |
| `hardware` | direct reference fields, an attached reference set, or source URLs, depending on the requested view |
| reference-set `create` | readable hardware, Slurm, and storage reference files for the selected profile |
| `submissions observe` | stored records whose profile is present in the active configuration, plus working Slurm accounting access |
| plugin commands | the plugin must be installed; each plugin decides whether an individual subcommand needs a profile |

Commands shown by `hpc --help` are built after loading the selected profile,
so site-specific helpers can be absent rather than merely failing later. A
local command such as `paths`, `plugins list`, reference-set inspection, or a
local scanner can run without a cluster configuration.

## Configuration schema

The configuration is TOML:

```toml
default_profile = "cluster-a"

[profiles.cluster-a]
ssh_target = "cluster-a-login"
projects_dir = "$HOME/projects"
default_cluster = "compute"
```

`default_profile` is optional. Each profile must define either `ssh_target` or
`host`; all other fields are optional.

| Field | Type | Meaning |
| --- | --- | --- |
| `ssh_target` | string | Target passed to SSH, commonly an alias from `~/.ssh/config`. It takes precedence when present. |
| `host` | string | Hostname used when `ssh_target` is absent. |
| `user` | string | Combined with `host` as `user@host`; it does not alter an explicit `ssh_target`. |
| `ssh_options` | array of strings | Additional SSH arguments, with each option and value represented as separate list elements. |
| `login_shell` | string or array of strings | Remote shell prefix. The default is `["bash", "-l", "-c"]`; the parsed value must end in `-c`. |
| `projects_dir` | string | Default remote parent for project listing and cloning. Shell expressions such as `$HOME/projects` are evaluated remotely. |
| `quota_command` | string | Site-specific quota command. |
| `queue_command` | string | Site-specific queue-summary command. |
| `sam_balance_command` | string | Site-specific account-balance command. |
| `sam_statement_command` | string | Site-specific account-statement command prefix. |
| `sam_quote_command` | string | Site-specific cost/credit quote command prefix. |
| `hardware_reference` | string | Local hardware reference file. |
| `hardware_url` | string | Source or supporting hardware URL. |
| `slurm_reference` | string | Local Slurm limits/policy reference file. |
| `slurm_url` | string | Source or supporting Slurm URL. |
| `storage_reference` | string | Local storage reference file. |
| `storage_url` | string | Source or supporting storage URL. |
| `status_url` | string | Cluster service-status page used by `status`. |
| `reference_set` | string | Installed shared reference set attached to the profile. Its values take precedence over direct reference fields. |
| `default_cluster` | string | Default Slurm cluster metadata used where supported; it is not a default account. |
| `email` | string | Address inserted only when probe mail notifications are explicitly requested. |

Unknown TOML keys are currently ignored, not rejected. Do not use that as a
forward-compatibility guarantee: a misspelled field can therefore appear to be
accepted while having no effect. Validate behavior with `hpc doctor`,
`hpc hardware --path`, and the relevant command.

See [Configure cluster profiles](configuration.md) for complete examples and
SSH quoting guidance.

## Slurm submit override options

Options given to `hpc submit` are placed on the `sbatch` command line after
`sbatch` and before the job script. Slurm command-line options therefore
override corresponding `#SBATCH` directives in the script.

| hpc-tools option | Slurm option |
| --- | --- |
| `-A`, `--account` | `--account` |
| `--array` | `--array` |
| `-M`, `--cluster` | `--clusters` |
| `--dependency` | `--dependency` |
| `--error` | `--error` |
| `--export` | `--export` |
| `--job-name` | `--job-name` |
| `--output` | `--output` |
| `-p`, `--partition` | `--partition` |
| `--reservation` | `--reservation` |
| `-t`, `--time` | `--time` |
| `-N`, `--nodes` | `--nodes` |
| `-n`, `--ntasks` | `--ntasks` |
| `--ntasks-per-node` | `--ntasks-per-node` |
| `-c`, `--cpus-per-task` | `--cpus-per-task` |
| `--mem` | `--mem` |
| `--mem-per-cpu` | `--mem-per-cpu` |
| `--gres` | `--gres` |
| `--gpus` | `--gpus` |
| `--gpus-per-node` | `--gpus-per-node` |
| `--gpus-per-task` | `--gpus-per-task` |
| `--gpu-bind` | `--gpu-bind` |

hpc-tools deliberately does not try to reproduce every `sbatch` option. Put a
stable site- or application-specific directive in the script, or request a
well-scoped CLI extension, instead of expecting arbitrary command-line
forwarding.

## Output formats

Human-readable text is the default. Text layouts are intended for people and
may evolve; do not treat spacing or headings as a stable machine API.

For most commands, global `--json` captures the ordinary result in an envelope:

```json
{
  "argv": ["--profile", "cluster-a", "jobs"],
  "returncode": 0,
  "stderr": "",
  "stdout": "..."
}
```

Configuration failure before dispatch instead produces an object containing
`error` and `returncode`. The following commands emit their own command-specific
JSON rather than the envelope:

- `benchmark summarize` and `benchmark compare`;
- `cxx scan`;
- `python scan`, `python inspect-deps`, `python check`, and
  `python verify-install`;
- `r scan`, `r check`, and `r verify-install`.

Inspect a representative result and validate the fields before depending on a
native schema. Native schemas are currently command contracts, not a single
versioned hpc-tools output schema.

Important text tables and remote formats are:

| Producer | Fields |
| --- | --- |
| `plugins list` | `NAME`, `VERSION`, `SOURCE`, `DESCRIPTION` |
| `references list` | `NAME`, `CREATED_AT`, `SOURCE_PROFILE`, `PATH` |
| `submissions list` | `RUN_ID`, `PROFILE`, `CLUSTER`, `JOBID`, `STATE`, `ACTION`, `JOBSCRIPT` |
| `jobs` | job ID, partition, job name, user, compact state, elapsed time, time limit, nodes, reason/node list |
| `job` | job ID, partition, job name, full state, elapsed time, time limit, nodes, reason/node list |
| `sacct` | `JobID`, `JobName`, `Partition`, `Account`, `State`, `ExitCode`, `Elapsed` |
| `benchmark summarize` | target, measure, sample count, mean, minimum, maximum, standard deviation, and sources |

Remote site commands such as `quota`, `queue`, `balance`, and `statement`
retain their site's output. `slurm-limits` is a labelled collection of Slurm
controller, partition, node, QoS, and association output rather than a single
rectangular table.

## Submission-log format

The default log is `submissions.jsonl` in the hpc-tools configuration
directory. It is append-only JSON Lines: each nonblank line is one JSON object.
Every event receives a local ISO 8601 timestamp with timezone information.

The event types are:

| Event | Fields in addition to `timestamp`, `event`, and `run_id` |
| --- | --- |
| `submitted` | `profile`, `job_id`, nullable `cluster`, `remote_directory`, `jobscript`, `submit_command`, and the non-null `slurm_overrides` object |
| `observed` | `profile`, `job_id`, nullable `cluster`, `state`, nullable `exit_code`, nullable `elapsed`, and `raw_output` |
| `results_collected` | optional `path` |
| `analysed` | optional `path` |
| `closed` | optional `reason` |

A generated run ID has the form
`YYYYmmddTHHMMSSZ-PROFILE-JOBID-RANDOM8`. It identifies the local run record;
the Slurm job ID and optional cluster identify the scheduler job.

The reader groups events by `run_id` and replays them in file order. The file
has no schema-version field, locking, remote synchronization, or cryptographic
integrity check. Avoid concurrent writers, protect it as user data, and back it
up before manual repair. A malformed JSON line makes the log unreadable until
that line is corrected. See [Submission tracking](submissions.md) before
editing it.

## Reference-set manifest format

An installed set is a directory named after the set and containing
`manifest.toml`. The current and only supported `format_version` is `1`.

```toml
format_version = 1
name = "cluster-a-2026-08"
created_at = "2026-08-24T12:00:00+02:00"
source_profile = "cluster-a"

[files]
hardware_reference = "hardware.md"
slurm_reference = "slurm.md"
storage_reference = "storage.md"
probe_hardware_report = "probe-hardware-report.md" # optional

[sources]
hardware_url = "https://cluster.example/hardware"
slurm_url = "https://cluster.example/slurm"
storage_url = "https://cluster.example/storage"
status_url = "https://status.example/"
```

The three primary file entries are required and must resolve to regular files
inside the reference-set directory. Source fields, creation metadata, and the
probe report are optional. Validation establishes structure and containment;
it does not establish that the prose is current, accurate, or safe to follow.

## Packaged probes and container templates

The Python package includes:

- `hardware-probe.slurm`, a broad CPU, memory, NUMA, storage, and optional GPU
  observation job;
- `cuda-device-properties.slurm` plus `cuda/CMakeLists.txt` and
  `cuda/device_properties.cu`, a CUDA device-properties bundle;
- `containers/apptainer/create_apptainer_container.slurm`, a generic Apptainer
  starter;
- `containers/r/`, containing an R container job, package installer, APT list,
  and labels;
- `containers/conda/`, containing a conda container job, environment file, and
  labels.

Use `hpc paths` to locate the installed copies and the `write-*` commands to
make editable working copies. Package-managed files may be replaced on upgrade;
do not edit them in place. Generated probes observe the allocated node, not
every node in a partition. Container bundles are starters that require review
and a cluster-supported Apptainer build environment.

## Local files and directories

The default base is `${XDG_CONFIG_HOME}/hpc-tools` when `XDG_CONFIG_HOME` is
set, otherwise `~/.config/hpc-tools`.

| Path | Purpose |
| --- | --- |
| `~/.config/hpc-tools/config.toml` | Default profile configuration. |
| `~/.config/hpc-tools/profiles/PROFILE/` | Durable profile-specific reference files and reports. |
| `~/.config/hpc-tools/reference-sets/NAME/` | Installed shared reference sets. |
| `~/.config/hpc-tools/submissions.jsonl` | Default local submission event log. |
| `~/.codex/skills/` | Optional copied standalone skills. This is separate from both the Python package and a Codex plugin installation. |

These are defaults, not literal paths under every environment. Run `hpc paths`
after setting environment variables to see the effective locations. Normal
package removal with `pipx uninstall hpc-tools` does not remove optional user
state or copied skills.

## Environment variables

| Variable | Effect |
| --- | --- |
| `HPC_TOOLS_CONFIG` | Select the default configuration file when `--config` is absent. |
| `XDG_CONFIG_HOME` | Relocate the hpc-tools configuration directory, reference sets, profile references, and default submission log. |

Remote commands also run in the selected profile's login-shell environment, so
remote variables such as `$HOME`, module initialization, and site-specific
storage variables can affect results. They are properties of the cluster
login environment rather than hpc-tools configuration variables.

## Exit codes and error conventions

| Code | Meaning |
| --- | --- |
| `0` | The requested command completed successfully. This does not imply that a job later completed or that a scientific result is correct. |
| `1` | A command-specific negative result, such as one or more failed `status` sections or missing dependencies reported by a checker. |
| `2` | CLI usage or hpc-tools configuration error. |
| other nonzero | Commonly the exit status propagated from SSH, a remote command, Slurm validation/submission, staging, or a plugin workflow. |

Errors intended for people are normally written to standard error. With the
generic JSON envelope, `stdout`, `stderr`, and `returncode` are fields while the
process itself exits with that same return code. A transport success only says
the command ran; inspect the returned content and, for scheduler actions, the
recorded Slurm state.

## MCP tools and resources

The optional MCP server is a structured agent interface, not an alternative
CLI syntax. Its current read tools cover profiles, paths, hardware context,
reference sets, plugins, submissions, status, jobs, Slurm limits, modules,
storage, and site environment. Confirm-gated tools cover reference changes,
submission-log marks, local probe/container writes, and remote probe/container
installation. Slurm submission is exposed only through the evidence chain:

```text
hpc_quote_job → hpc_validate_job → hpc_submit_job
```

Fixed resources are:

- `hpc://paths`;
- `hpc://config`;
- `hpc://submissions/active`;
- `hpc://submissions/all`.

Resource templates are:

- `hpc://profiles/{profile}`;
- `hpc://profiles/{profile}/hardware`;
- `hpc://profiles/{profile}/slurm`;
- `hpc://profiles/{profile}/storage`;
- `hpc://reference-sets/{name}`.

Tool arguments and result objects are described by the running MCP server and
can change while this interface remains experimental. Read [MCP integration](mcp.md)
for the full tool inventory, confirmation semantics, evidence limitations, and
deployment boundary.

## Glossary

**account**
: A Slurm allocation or charging identity. It is not the SSH user, cluster
  profile, or `default_cluster`, and hpc-tools does not choose it for you.

**active submission**
: A local run record whose replayed action is not `closed`. It may already be
  terminal in Slurm if it has not yet been observed locally.

**cluster**
: A Slurm cluster name used with federation-capable commands. One SSH profile
  can see one or more Slurm clusters.

**CLI plugin**
: A Python extension registered in the `hpc_tools.plugins` entry-point group.
  It extends `hpc`; it is not the Codex plugin.

**Codex plugin**
: The skills and MCP configuration packaged through `.codex-plugin`. Installing
  it does not install the `hpc` Python command or authorize cluster access.

**dry run**
: A preview of an SSH-backed command. It is not universal transaction
  simulation and does not validate scheduler acceptance.

**job ID**
: The identifier returned by Slurm for a scheduler job. In a federation, use
  it together with the cluster when necessary.

**login shell**
: The configured remote shell prefix that initializes the site's interactive
  environment before running a command.

**MCP**
: Model Context Protocol, used here to expose structured hpc-tools resources
  and guarded actions to compatible agents.

**partition**
: A Slurm scheduling partition with its own nodes, limits, and policy. It is
  not necessarily a hardware-homogeneous queue.

**profile**
: A local named SSH and site configuration. It contains no password and is not
  a cluster account.

**QoS**
: Slurm Quality of Service, which can impose limits or priorities in addition
  to account, association, and partition policy.

**reference set**
: A versioned local bundle of hardware, Slurm, and storage prose plus source
  metadata. It is durable context, not live scheduler truth.

**run ID**
: The local hpc-tools identifier linking append-only submission events. It is
  distinct from the Slurm job ID.

**submission log**
: The local JSONL event history created after successful `hpc submit` calls and
  extended by observation and lifecycle-marking commands.

**validation**
: In the submission workflow, `sbatch --test-only` with the proposed options.
  It tests scheduler acceptance at that moment, not cost, performance,
  scientific validity, or future availability.
