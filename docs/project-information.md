# Limitations, support, and project information

hpc-tools is an actively developed, profile-based interface for recurring SSH
and Slurm work. It is useful precisely because it narrows the problem, but that
also means some tempting expectations are outside its contract. Read this page
before depending on it as infrastructure or distributing a derivative.

## Current limitations and deliberate non-features

### It is not a cluster management system

hpc-tools operates with an ordinary user's SSH and Slurm permissions. It does
not create accounts, distribute SSH keys, configure Slurm, manage nodes, or
override site policy. A profile records how to reach a site; it does not grant
access.

The core does not provide general remote file transfer, recursive deletion,
bulk scheduler filtering, or arbitrary administrator operations. Job
cancellation is limited to one validated job identifier per call. Those
boundaries reduce accidental damage but do not make the tool read-only:
cloning, remote installation, reference attachment, local file writes, job
submission, and cancellation all change state. `hpc run` can execute any
command the user can execute remotely and must be treated accordingly.

### Scheduler acceptance is not workflow correctness

`sbatch --test-only` checks whether Slurm accepts a request at that moment. It
does not establish that:

- the requested account is authorized for the intended work;
- the job is affordable, efficient, or likely to start promptly;
- CPU, memory, GPU, topology, and filesystem choices match the application;
- the program will produce a scientifically valid result;
- an array's total concurrency is safe for the site or downstream storage.

Cost quoting is available only when a profile defines a compatible site helper.
Sites without that helper still require a user or support service to review
account and resource choices.

### Local records are not scheduler truth

The submission database is a local append-only aid. It does not automatically
synchronize with Slurm, transfer results, hash artifacts, reopen closed runs,
or coordinate concurrent writers. `mark-collected`, `mark-analysed`, and
`close` record user assertions; they do not perform or verify the named work.

An active local record can refer to a completed job until `submissions observe`
is run. Conversely, closing a record does not cancel the job. Keep the Slurm
job ID, cluster, output paths, and scientific provenance in the workflow's own
records as well.

### Reference material becomes stale

Reference sets are snapshots of prose and observations. Structural validation
does not prove that a partition, module, filesystem, price, limit, or policy is
still current. Probe results describe the allocated node and runtime context,
not necessarily every node in a partition. Always compare durable references
with live Slurm output and current site documentation before a consequential
run.

Imported reference archives are untrusted input. hpc-tools prevents archive
members from escaping their intended directory, but it cannot make imported
instructions true or safe.

### Site integrations and parsers are necessarily incomplete

Quota, queue, balance, statement, quote, and status helpers depend on profile
configuration and the site's output. Module, Slurm-limit, dependency, job
output, and benchmark parsers are best-effort interpretations, not standards
compliance layers.

Python and R scanners cannot reliably discover dynamic imports, generated code,
optional features, compiled libraries, external commands, or all mapping
differences between import and distribution names. C/C++ scans provide hints,
not a complete build model. Container templates are editable starters rather
than reproducible images until the user pins, builds, tests, and records them.

### Agent interfaces retain the user's authority boundary

The Codex plugin supplies guidance and the MCP server supplies structured tools;
neither installs the CLI, configures SSH, selects a default Slurm account, or
creates human authorization. MCP `confirm=true` is a tool argument, not proof
that a person reviewed the operation. It must be combined with the agent host's
approval policy, constrained credentials, narrow filesystem access, and normal
cluster controls.

The MCP interface is experimental. It deliberately omits a general remote
command tool and exposes submission only through quote, validation, and submit
evidence. Those safeguards reduce common mistakes but are not an isolation
boundary for hostile agents or a substitute for cluster policy.

## Supported runtime and cluster assumptions

The packaged Python project currently declares Python 3.10 or newer. The
repository's continuous integration exercises Python 3.10, builds the MkDocs
site strictly, validates the plugin and skills, compiles the Python sources,
and runs the unit test suite. That is evidence for the tested development
configuration, not a promise that every Python/OS/Slurm combination is covered.

Normal remote operation assumes:

- a local `ssh` client and working noninteractive SSH access;
- a Unix-like remote login environment;
- a Slurm installation exposing the commands needed by the chosen workflow,
  commonly `sbatch`, `squeue`, `sacct`, `sinfo`, `scontrol`, and `sacctmgr`;
- a login shell capable of accepting a command after `-c`; the default is
  `bash -l -c`;
- site module and storage commands only where the corresponding inspection is
  requested;
- Apptainer and a site-permitted build route only for the container workflow;
- CUDA tools and suitable GPU allocation only for the CUDA probe.

Slurm versions, accounting configuration, federation setup, permissions, and
site wrappers differ. Some inspection sections can therefore be empty or
permission-denied on an otherwise usable cluster. Begin with `hpc doctor`, then
validate the exact commands required for the intended workflow.

There is no published operating-system or Slurm-version support matrix in the
repository. Do not infer one from a successful run on a single cluster.

## Compatibility and upgrade expectations

The current package and Codex plugin identify themselves as version `0.1.0`.
The project does not currently publish a formal backward-compatibility policy.
Treat the CLI, profile schema, plugin API, MCP schemas, and local data formats
as pre-stable interfaces:

- human-readable table spacing and headings are not machine APIs;
- native JSON output is command-specific and not governed by one versioned
  top-level schema;
- the MCP interface is explicitly experimental;
- reference-set manifests are versioned and currently require
  `format_version = 1`;
- submission databases use SQLite `PRAGMA user_version` for schema versioning.

Before upgrading an installation used in automation:

1. record the old and proposed package versions;
2. back up `config.toml`, reference sets, and `submissions.sqlite3`;
3. read the available repository changes or release information;
4. test `hpc --help`, `hpc plugins list`, profile loading, and representative
   JSON output in a disposable environment;
5. run a dry run and a small scheduler validation before a real submission.

Pin the package version when repeatable behavior matters. A version pin avoids
unreviewed upgrades; it does not freeze the cluster's policy, modules, or
scheduler behavior.

## Reporting a bug

For a nonsensitive defect, use the
[hpc-tools issue tracker](https://github.com/gjbex/hpc-tools/issues). Search for
an existing report first and include a minimal, reproducible description:

- hpc-tools version and installation method;
- local Python and operating-system information;
- the command, with profile names and paths anonymized where necessary;
- whether the failure is local, SSH, login-shell, Slurm, site-helper, plugin,
  MCP, or documentation related;
- actual and expected behavior;
- exit status and the smallest useful standard output/error excerpt;
- whether plain SSH and the equivalent site command work independently;
- a minimal sanitized profile fragment if configuration is relevant.

Do not post passwords, private keys, access tokens, full account statements,
allocation balances, private hostnames, usernames, job data, or proprietary
source. Prefer the diagnostic layers in [Troubleshooting](troubleshooting.md)
over uploading an entire configuration or log.

The repository currently has no published `SECURITY.md` or dedicated private
vulnerability-reporting channel. Do not disclose a suspected vulnerability or
sensitive exploit details in a public issue. Use an already established trusted
private route to the maintainer; if none exists, open only a nonsensitive issue
requesting a private contact and withhold the vulnerability details.

## Requesting a new cluster workflow

A useful workflow request explains the user decision and safety boundary, not
only a desired wrapper command. Include:

- the scientific or operational goal;
- the exact manual commands currently used, with secrets removed;
- what is portable Slurm behavior and what is site-specific;
- required profile fields, modules, filesystems, and scheduler capabilities;
- read-only, local-write, remote-write, submission, and destructive effects;
- expected previews, confirmation points, and evidence retained after a run;
- representative sanitized inputs and outputs;
- failure modes, recovery steps, and a small validation scenario;
- whether the behavior belongs in the core CLI, an `hpc_tools.plugins`
  extension, a Codex skill, or a combination.

Site-specific commands with a narrow audience usually belong in a CLI plugin
or profile field rather than the core command tree. General scientific-software
engineering guidance belongs in `scientific-computing-skills`; hpc-tools should
remain focused on operational cluster workflows and safety.

Do not propose committing durable user-generated cluster references to this
repository. Personal profile material belongs under
`~/.config/hpc-tools/profiles/PROFILE/`; a deliberately shared bundle belongs
under the user's reference-set directory and can be exported explicitly.

## Release notes and version sources

The authoritative package version is declared in `setup.cfg`; the Codex plugin
has a separate version in `.codex-plugin/plugin.json`. A release that changes
both distribution surfaces should keep them aligned and validate both.

The repository currently has no dedicated changelog or release-notes file.
Until one is added, users must inspect the repository history and any release
information published alongside the distribution before upgrading. Absence of
a release note is not evidence that an upgrade is behavior-preserving.

For maintainers, useful release notes should call out at least:

- new, changed, renamed, or removed commands and profile fields;
- JSON, MCP, manifest, and submission-database format changes;
- new local or remote write behavior and confirmation requirements;
- minimum Python or dependency changes;
- migration and rollback steps;
- validation performed and known cluster-specific limitations.

## License and acknowledgements

The current repository checkout contains no `LICENSE` file and the package
metadata declares no license. Do not infer permission to copy, modify,
redistribute, or incorporate the project from its public availability alone.
A clear license should be added before others are expected to reuse or
redistribute the project; obtain explicit permission from the rights holder in
the meantime.

The package metadata names Geert Jan Bex as the author. hpc-tools builds on
Python and its declared libraries (`packaging`, PyYAML, TOML readers/writers,
and optional FastMCP), and interoperates with external systems such as OpenSSH,
Slurm, environment modules, Git, Apptainer, R, Python environment tooling, and
CUDA when those workflows are selected. Those projects retain their own names,
licenses, documentation, and support channels.

## Contributor and extension-developer documentation

Start with [CLI plugin system](plugins.md) when adding a workflow. Register CLI
extensions through the `hpc_tools.plugins` entry-point group rather than
hardcoding unrelated workflows into the core. Keep the Python CLI distribution
separate from the Codex plugin: the former is packaged by `setup.cfg`, while
the latter is described by `.codex-plugin/plugin.json` and can point to the
optional MCP server.

Repository contributors should also read the repository-level `README.md`,
`AGENTS.md`, and `ROUTING.md` before changing ownership boundaries or workflow
routing. Important conventions include:

- treat `examples/` as templates and sample data;
- keep shared conceptual HPC guidance under `skills/_shared/` and top-level
  skills task-oriented;
- store no durable user-generated cluster references in the repository;
- install normal releases with pipx and reserve editable installs for
  development;
- add tests for CLI contracts, file formats, skills, and documentation
  assertions affected by the change;
- preserve confirmation and evidence chains when adding write or submission
  behavior.

### Submission database schema

This is an internal development contract, not a user-facing interchange
format. The authoritative implementation is `hpc_tools/submissions.py`. Schema
changes must increment `SCHEMA_VERSION`, add an explicit migration when existing
data must be supported, and update the tests and this section together.

Schema version 1 is identified by:

```sql
PRAGMA user_version = 1;
```

It contains one append-only event table and one replay index:

```sql
CREATE TABLE submission_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX submission_events_by_run
ON submission_events (run_id, sequence);
```

The columns have these responsibilities:

| Column | Internal contract |
| --- | --- |
| `sequence` | Database insertion order used to replay lifecycle events. |
| `event_id` | Generated unique identifier for the stored event. |
| `run_id` | Local submission/run identifier used for grouping and lookup. |
| `event_type` | Indexed event discriminator duplicated from the JSON payload. |
| `occurred_at` | ISO 8601 timestamp duplicated from the JSON payload. |
| `payload_json` | Complete event object consumed by the existing event reducer. |

`event_type`, `occurred_at`, and `run_id` deliberately duplicate values from
`payload_json`. The relational columns support validation and future indexed
queries, while the JSON payload preserves the existing event representation.
The reducer currently treats `payload_json` as the complete lifecycle event and
reconstructs records in `sequence` order.

Each connection applies:

```sql
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;
```

The rollback journal is intentional: WAL mode depends on shared-memory
semantics that are often unsuitable for NFS-backed HPC home directories. This
does not make every network or parallel filesystem safe for SQLite. A
concurrent broker should use node-local or otherwise verified storage, and one
database must not be treated as a distributed multi-node service.

Schema creation acquires an immediate transaction before checking the version
again, so concurrent first writers cannot independently initialize the
database. Event batches are validated before opening the database and inserted
with one transaction. A failed batch therefore must not leave a partial event
set. Newly created database files are restricted to mode `0600`.

There is currently no legacy JSONL importer and no schema migration because the
format has not entered production. A database whose `user_version` is not
`SCHEMA_VERSION` is rejected rather than guessed, modified, or partially read.

Build documentation as described in
[Build the documentation](contributing/documentation.md). The repository's
required validation covers plugin metadata, skills, repository hygiene, Python
compilation, unit tests, and a strict MkDocs build. A focused test is useful
during development, but it does not replace the full validation surface before
release.
