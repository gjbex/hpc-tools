# Restricted agent image build record

Copy this record next to the durable SIF and replace every `RECORD` value. Do
not put the built SIF, registry credentials, or private cache contents in Git.

- Build date (UTC): RECORD
- Builder and site: RECORD
- hpc-tools revision and dirty-tree state: RECORD
- Definition SHA-256: RECORD
- Base image tag: `node:22.16.0-bookworm-slim`
- Base image index digest:
  `sha256:048ed02c5fd52e86fda6fbd2f6a76cf0d4492fd6c6fee9e2c463ed5108da0e34`
- Node version: `22.16.0`
- Codex CLI version: `0.150.1`
- Build command: RECORD
- Apptainer version: RECORD
- SIF path: RECORD
- SIF SHA-256: RECORD
- `apptainer test` result and time: RECORD
- Definition diff reviewed by: RECORD
- Optional SIF signature identity and verification policy: RECORD or not used

The launcher requires the recorded SIF SHA-256 through
`--agent-image-sha256`. A signature may add site-managed publisher identity,
but it does not replace the mandatory hash check.
