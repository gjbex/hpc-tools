# Reference Sets

`hpc-tools` now supports shareable cluster reference bundles under:

```text
~/.config/hpc-tools/reference-sets/<name>/
```

Each reference set contains a `manifest.toml` plus the durable shared files
that describe one cluster family:

- `hardware.md`
- `slurm.md`
- `storage.md`
- optional `probe-hardware-report.md`

Profiles can attach one of these bundles with:

```bash
hpc --profile <profile> references attach <name>
```

When `reference_set = "<name>"` is present in a profile, `hpc hardware`
resolves hardware, Slurm, storage, and status source metadata from that shared
bundle before falling back to profile-local metadata.

## Current Workflow

Create a shared bundle from an existing profile:

```bash
hpc --profile <profile> references create <name>
```

Inspect and validate it:

```bash
hpc references show <name>
hpc references validate <name>
```

Export it for another user:

```bash
hpc references export <name> --output <name>-reference-set.tar.gz
```

Import and attach it on another machine or account:

```bash
hpc references import <name>-reference-set.tar.gz
hpc --profile <profile> references attach <name>
```

Detach it later if needed:

```bash
hpc --profile <profile> references detach
```

## What Is Shared

Reference sets are for cluster-global context:

- hardware summaries
- Slurm policy summaries
- storage summaries
- consolidated probe reports
- source URLs, operational status URLs, and provenance stored in `manifest.toml`

They are not for user-specific state:

- `config.toml`
- `ssh_target`, `user`, `email`
- account balances or quote history
- `submissions.jsonl`
- raw probe-result directories

## First-Slice Constraints

The current implementation keeps the format intentionally narrow:

- one manifest format version: `1`
- one top-level archive directory on export/import
- three required reference files: hardware, Slurm, storage
- one optional consolidated probe report
- profile attach/detach only updates `reference_set = ...` in `config.toml`

## Next Steps

The follow-on work should stay in the same feature family rather than creating
parallel mechanisms.

1. Add support for extra shared artifacts beyond the first three references and
   `probe-hardware-report.md`, such as `partition-report.md` or future probe
   summaries, by extending `manifest.toml`.
2. Add a `hpc references materialize <name> --profile <profile>` command that
   writes explicit profile-local copies when a user wants a detached snapshot.
3. Add optional signing or checksums in the manifest so imported bundles can be
   verified beyond basic file presence.
4. Add `hpc references refresh <name> --from-profile <profile>` to update an
   existing shared bundle in place after new probe results are consolidated.
5. Extend onboarding and cluster-discovery workflows so they recommend
   `references create/export` once a cluster description has stabilized.
6. Consider connector-friendly publish/pull workflows later, but only after the
   local archive/import path has proven stable.
