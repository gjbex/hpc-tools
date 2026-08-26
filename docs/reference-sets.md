# Cluster references and sharing

Cluster work depends on facts that are easily scattered across site pages,
personal notes, job scripts, and probe output. hpc-tools uses concise local
references to keep hardware, Slurm, and storage context visible through a
profile. A reference set packages the cluster-global part for reuse or sharing.
It is a snapshot, not a live copy of site documentation.

## Profile references and shared sets

Profile-local references normally live below:

```text
~/.config/hpc-tools/profiles/<profile>/
```

Shared reference sets live below:

```text
~/.config/hpc-tools/reference-sets/<name>/
```

Each set has one manifest, three required files, and one optional report:

```text
<name>/
├── manifest.toml
├── hardware.md
├── slurm.md
├── storage.md
└── probe-hardware-report.md  # optional
```

Manifest format 1 records creation metadata, source profile, file names,
authoritative source URLs, and an optional status URL. Use `hpc paths` to show
the active locations.

## Choose what to share

Include durable, cluster-global summaries such as:

- CPU, memory, accelerator, and node-class descriptions;
- partitions, array limits, QoS concepts, and scheduler policy;
- filesystem purposes, retention, quota, backup, and I/O guidance;
- a concise consolidated hardware-probe report;
- authoritative documentation and operational-status links.

Keep observations attributable. Say whether a fact came from documentation,
scheduler output, or a dated representative probe, especially on heterogeneous
clusters.

Do not include user-specific or sensitive state:

- `config.toml`, SSH targets, usernames, email addresses, or keys;
- Slurm accounts, balances, quote history, or allocation details;
- `submissions.sqlite3` or personal job history;
- tokens, private project paths, or unpublished input details;
- raw probe directories or large result trees.

A set should help another authorized user understand the site; it must not
transfer your identity, authorization, or research data.

## Prepare the source profile

`references create` copies the resolved references from the selected profile.
That profile must provide existing hardware, Slurm, and storage files. Complete
onboarding and inspect the context first:

```console
hpc --profile example hardware
hpc --profile example slurm-limits --cluster example-cluster
hpc --profile example storage inspect '$VSC_DATA'
```

Review the Markdown itself and remove stale, personal, or unsupported claims.
A probe observation is not automatically representative of an entire cluster.

If a profile already has a set attached, that set takes precedence over
profile-local references. Creating another set will snapshot the attached
context. Detach it first, or use a profile whose local references are selected,
when newly edited local files are meant to be packaged.

## Create, inspect, and validate

Use a descriptive, versioned name rather than `latest` or a path-like value:

```console
hpc --profile example references create example-cluster-2026-08
hpc references show example-cluster-2026-08
hpc references validate example-cluster-2026-08
hpc references list
```

Creation copies the required files and a probe report when it is found beside
the profile references. It copies configured source URLs into the manifest.
Later edits to profile files do not update this snapshot.

`show` reports paths, metadata, and URLs; it does not print or review the
Markdown. `validate` checks the supported manifest shape, safe in-set paths,
and declared-file presence. It does not check:

- whether statements are correct or current;
- whether URLs still resolve;
- whether a probe covers all node types;
- authorship, signatures, or checksums;
- whether content is safe to trust.

Read the files before attaching or exporting the set.

## Attach a set to a profile

```console
hpc --profile example references attach example-cluster-2026-08
hpc --profile example hardware
```

Attachment adds the following to the selected profile in `config.toml`:

```toml
reference_set = "example-cluster-2026-08"
```

The set supplies hardware, Slurm, storage, status, and probe metadata before
hpc-tools falls back to corresponding profile-local values. Attachment does
not delete those local values, which makes detachment reversible but can hide
stale local information.

Detach with:

```console
hpc --profile example references detach
hpc --profile example hardware
```

Detachment removes only `reference_set`. It neither deletes the installed set
nor updates older profile-local references. When using a non-default config,
pass the same global `--config` option to attach or detach.

## Export safely

```console
hpc references export example-cluster-2026-08 \
    --output example-cluster-2026-08-reference-set.tar.gz
```

Without `--output`, the current directory receives
`<name>-reference-set.tar.gz`. Export refuses to overwrite an archive unless
`--force` is supplied.

Before sharing:

1. inspect or extract the archive in a temporary location;
2. read all Markdown and the manifest;
3. search for identity, account, project, and private path information;
4. confirm sources, dates, cluster, audience, and limitations;
5. distribute a checksum through a trusted channel when integrity matters.

The current format embeds no checksum or digital signature. Transport security
and any independent integrity check remain the users' responsibility.

## Import and review

```console
hpc references import example-cluster-2026-08-reference-set.tar.gz
hpc references show example-cluster-2026-08
hpc references validate example-cluster-2026-08
```

Import accepts exactly one top-level directory, rejects absolute and
parent-traversing paths, rejects links and unsupported member types, and
validates structure before installation. These protections reduce extraction
risk; they do not establish that the Markdown or URLs are trustworthy.

Treat an imported set as untrusted content:

- verify an independently communicated checksum when available;
- read every file before exposing it to an automated agent workflow;
- compare policy and limit claims with current site sources;
- confirm that it describes the cluster used by the target profile;
- resolve conflicts and stale observations before attachment.

Then attach and verify it:

```console
hpc --profile example references attach example-cluster-2026-08
hpc --profile example hardware
```

`--force` on import replaces an installed set with the same name. Back up or
confirm the old directory is disposable before using it.

## Update without hiding history

There is no automatic refresh command. Hardware, policy, modules, and storage
change independently, and silent in-place refresh would obscure provenance.

Prefer this sequence:

1. update and review profile-local source references;
2. create a new dated or versioned set;
3. validate and compare old and new files;
4. attach the new set to the intended profile;
5. verify `hpc hardware` and a representative workflow;
6. retain or archive the old set as provenance requires.

Although `references create --force` can replace a set, replacement deletes
that set's directory before recreating it. Do not use it when a previous
snapshot or hand edits must be preserved.

Refresh after material changes such as new hardware, scheduler-policy changes,
or storage migration. A dated snapshot is not current merely because its files
still validate.

## Resolve common problems

| Problem | Response |
| --- | --- |
| Create reports missing references | Finish all three summaries and check their configured paths. |
| New local edits do not appear | Check whether an attached set took precedence; detach if appropriate and create a new version. |
| Validation succeeds but content is wrong | Review against authoritative sources; validation is structural. |
| The wrong cluster is described | Detach the set and compare both contexts; names do not bind sets semantically to profiles. |
| Import refuses an existing name | Compare or back up the installed set; prefer a new versioned name over `--force`. |
| Detach reveals old information | Review, update, or remove the retained profile-local references. |

Reference sets reduce duplicated notes, but shared mistakes also propagate
efficiently. Preserve sources, dates, scope, and uncertainty so another user
can tell which statements remain safe to act on.
