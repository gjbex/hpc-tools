# Run an unattended agent in Apptainer

The restricted launcher is an operator workflow for an unattended agent inside
a Slurm allocation. It keeps scheduler authority, the delegation manifest, and
the authorization ledger in a host process. The agent receives only the
restricted MCP surface and explicitly selected filesystem mounts.

This is a capability boundary for one Unix user's unattended process. It is not
equivalent to a VM or a security boundary between mutually distrustful Unix
users: Apptainer shares the host kernel and normally preserves the submitting
uid.

## Deployment topology

```text
Slurm allocation, host namespace
├── hpc-agent-launch
├── hpc-mcp --executor local --preset slurm-job
│   ├── delegation manifest and SQLite ledger
│   └── Slurm and Munge access
├── private single-client Unix socket bridge
└── Apptainer parent-agent container
    ├── hpc-mcp-relay
    ├── work root (read/write)
    ├── completed/delegate output root (read-only)
    ├── common inputs (read-only)
    └── no Slurm, SSH, Munge, manifest, or ledger access
```

The MCP client starts `hpc-mcp-relay`, not `hpc-mcp`. The relay forwards stdio
bytes through a private read-only socket bind. The host bridge accepts one
connection from the same Unix uid and starts the real server outside the
container. The socket is the capability channel; it is never passed to
delegated computation containers.

## Prepare the agent image

The packaged `agent` container bundle is a minimal boundary base containing
Python and `hpc-mcp-relay`, with no SSH, Slurm, or Munge clients. It deliberately
does not install a particular agent. Write the bundle, then extend the reviewed
definition with the site's non-interactive agent runtime.

Build from the generated bundle directory so the `%files` source resolves:

```console
hpc write-container --kind agent restricted-agent-build
cd restricted-agent-build
apptainer build --fakeroot restricted-agent.sif Apptainer.def
apptainer test restricted-agent.sif
```

Replace the example base-image tag with a reviewed digest when exact build
reproducibility matters. Keep the built SIF out of Git and record its checksum.
The host launcher repeats a negative preflight before every run. It rejects an
agent or approved worker image exposing common SSH, Slurm, or Munge commands,
`/etc/slurm`, `/etc/ssh`, or common Munge socket directories under the actual
containment flags.

Configure the in-image MCP client with the equivalent of the generated
`mcp.json`:

```json
{
  "mcpServers": {
    "hpc-tools": {
      "command": "hpc-mcp-relay",
      "args": []
    }
  }
}
```

## Define the filesystem boundary

A delegation that permits new jobs needs a `[filesystem]` table:

```toml
[allowed]
containers = ["/project/images/worker-2026-08-27.sif"]
roots = ["/scratch/project/agent-001/work"]

[filesystem]
state_root = "/scratch/project/agent-001-private"
work_root = "/scratch/project/agent-001/work"
output_root = "/scratch/project/agent-001/output"
input_roots = ["/project/data/common"]
apptainer_path = "/usr/bin/apptainer"
max_file_blocks = 2097152
max_open_files = 1024
```

All paths are absolute literals, must not overlap, and must not contain
symlinks. `state_root` contains generated Slurm wrappers and immutable payload
snapshots and is never mounted into the agent. `work_root` is the only
read/write parent-agent bind. `output_root` is mounted read-only into the
parent; the host creates one subdirectory per logical request and gives a
delegate container read/write access only to its own subdirectory.
`input_roots` are read-only in both containers.

The manifest and ledger must be mode `0600`. State, work, output, socket, and
per-job directories are mode `0700`. Put the SQLite ledger on a filesystem with
known-correct locking rather than assuming every cluster network filesystem is
safe for SQLite.

## Start the parent allocation

Adapt the generated `restricted-agent.slurm` and submit it normally. The
essential invocation is:

```console
hpc-agent-launch \
    --manifest /protected/agent-001.toml \
    --ledger /protected/delegations.sqlite3 \
    --profile example \
    --agent-image /project/images/restricted-agent.sif \
    -- your-agent --non-interactive
```

The launcher requires `SLURM_JOB_ID` to match the manifest and uses the site's
private `SLURM_TMPDIR` for the MCP socket unless `--runtime-directory` selects
another private mode-`0700` directory. It invokes Apptainer with
`--containall`, `--cleanenv`, `--no-home`, and
`--no-mount home,cwd,hostfs,bind-paths`. Sites whose Apptainer version or policy
does not support those flags fail closed and must review an adapted launcher;
silently dropping a containment flag is unsafe.

The outer Apptainer environment removes SSH-agent variables, delegation paths,
credentials, `LD_PRELOAD`, and agent-controlled
`APPTAINERENV_`/`SINGULARITYENV_` injections by constructing a small allowlisted
outer environment. The container explicitly receives only a temporary home and
the MCP socket path from this layer.

If the agent requires dedicated credentials or endpoint configuration, place
only those values in a protected mode-`0600` file outside all bind roots and
select it with `--agent-env-file`. Apptainer reads the file on the host; the
launcher does not print its values or mount the file. The values are necessarily
visible to the parent agent process and a compromised agent could disclose
them, so prefer short-lived, narrowly scoped credentials or an external
credential broker. The file is never passed to delegated jobs.

## Submit a delegated computation

In restricted mode, quotation, validation, and submission require the same
`container` and `idempotency_key`. The job script must be a regular non-symlink
file below `work_root`. The server hashes and snapshots at most 1 MiB of script
content into `state_root`; evidence binds the payload hash, container path, and
idempotency key. Editing the work copy afterward invalidates earlier evidence
rather than changing the staged computation.

The agent cannot set Slurm `--output`, `--error`, or `--export`. The server sets
stdout and stderr below the per-job output directory and forces
`--export=NONE`. Its generated wrapper launches the approved SIF with:

- the immutable payload snapshot read-only;
- the complete work root read-only;
- common inputs read-only;
- only that request's output directory read/write;
- a clean environment and no parent MCP socket.

Only the submitted payload script is snapshotted. Other files below
`work_root` remain writable by the parent agent and can change while a delegate
is queued or running. Put stable datasets, dependencies, and configuration in
operator-managed `input_roots`, or use content-addressed/versioned work files
when the exact computation must be reproducible.

The output directory contains `.hpc-tools-incomplete` while the wrapper is
running and an atomically replaced `.hpc-tools-status.json` after the container
exits. Successful completion removes the incomplete marker. Failed or killed
jobs can leave partial application outputs, so consumers must check Slurm state,
the status file, and application-level completion invariants before use.

`max_file_blocks` and `max_open_files` become shell resource limits in the
delegate wrapper. The file-block unit is defined by the host `/bin/sh` and must
be verified on the target site; many shells use 512-byte or 1024-byte blocks.
These limits do not cap aggregate bytes or total directory entries.
Use scheduler/site filesystem quotas for enforceable aggregate byte and inode
limits. Per-job directories prevent unrelated delegates from concurrently
writing the same output tree; applications that create multiple writers inside
one job must still provide their own coordination and atomic-output protocol.

## Known limitations

- The generated delegate wrapper currently supports one Slurm node and one
  task, including multiple CPUs assigned to that task. Job arrays are supported.
  Multi-task, multi-node, GPU, and GRES requests fail closed until a site adds
  reviewed `srun`, MPI/PMI, and Apptainer device integration; silently allocating
  resources that the container cannot use would be worse.
- The launcher assumes `sbatch` from within the parent allocation is permitted.
  Sites that prohibit nested submissions need a durable broker on an approved
  service or login node and a separately authenticated transport.
- The bridge authenticates the Unix uid and possession of its private socket,
  not a distinct process identity. The restricted MCP registry and ledger
  remain the authorization boundary.
- Network access is not disabled because the agent may require its model
  endpoint. The design depends on withholding scheduler/network credentials,
  not on network isolation.
- Apptainer still exposes the host kernel and necessary pseudo-filesystems.
  Site-configured device and system mounts must be reviewed on the actual
  cluster.
- A real SIF build, socket relay, scheduler validation, and delegate pilot must
  be exercised on each target site; unit tests cannot establish the site's
  Apptainer or Slurm policy.
