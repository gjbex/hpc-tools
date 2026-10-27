# Run an unattended agent in Apptainer

The restricted launcher is an operator workflow for an unattended agent inside
a Slurm allocation. It keeps scheduler authority, the delegation manifest, and
the authorization ledger in a host process. The agent receives only the
restricted MCP surface and explicitly selected filesystem mounts.

This is a capability boundary for one Unix user's unattended process. It is not
equivalent to a VM or a security boundary between mutually distrustful Unix
users: Apptainer shares the host kernel and normally preserves the submitting
uid.

The general C0--C3 profile model and independent scopes are described in
[Capability policy](capabilities.md). The `slurm-job` preset is an additional
deployment restriction: it intersects that profile policy with captured
controller authority and the protected delegation manifest rather than
granting another level.

## Deployment topology

```text
Slurm allocation, host namespace
├── hpc-agent-launch
├── hpc-mcp --executor local --preset slurm-job
│   ├── delegation manifest and SQLite ledger
│   └── Slurm and Munge access
├── private single-client Unix socket bridge
└── Apptainer parent-agent container
    ├── Codex CLI and ephemeral per-run configuration
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

The packaged `agent` container bundle is a runnable Codex CLI image. It contains
the pinned `@openai/codex` package, Python for `hpc-mcp-relay`, a Codex-native
MCP configuration, the image-only `hpc-delegated-slurm` skill, a reviewed task
template, an operator-side delegation template, and a `codex-agent` batch
wrapper. The delegation template is emitted into the build bundle for the
parent job but is not copied into the image. The image contains no SSH, Slurm, or Munge
clients. It does not install the interactive hpc-tools skills for onboarding,
deployment, package management, or live cluster administration. Definitions
for other agents can be added as separate container kinds later; this recipe
deliberately has one testable runtime rather than pretending that agent
configuration is portable.

Build from the generated bundle directory so the `%files` source resolves:

```console
hpc write-container --kind agent restricted-codex-build
cd restricted-codex-build
apptainer build --fakeroot restricted-codex.sif Apptainer.def
apptainer test restricted-codex.sif
```

The Codex and Node versions are pinned, but the OCI base tag is mutable. Replace
it with a reviewed digest when exact build reproducibility matters. Keep the
built SIF out of Git and record its checksum. A Codex version bump is a reviewed
recipe change: update the package version, image label, `%test` assertion, and
the corresponding tests together.

The image `%test` checks the exact Codex version and absence of common SSH,
Slurm, and Munge commands. The host launcher repeats a negative preflight before
every run and also rejects `/etc/slurm`, `/etc/ssh`, and common Munge socket
directories under the actual containment flags.

The image contains three complete Codex configurations. Each uses Codex's
native stdio MCP configuration, makes the relay required, disables command
networking, and sets one explicit web-search mode:

```toml
web_search = "disabled"  # or "indexed" / "live" in the other files
sandbox_mode = "workspace-write"
allow_login_shell = false

[sandbox_workspace_write]
network_access = false

[shell_environment_policy]
inherit = "all"
ignore_default_excludes = false
experimental_use_profile = false

[shell_environment_policy.filters]
"OPENAI_API_KEY" = "exclude"
"CODEX_ACCESS_TOKEN" = "exclude"
"HTTPS_PROXY" = "exclude"  # HTTP/NO_PROXY and CA variables are also excluded

[mcp_servers.hpc-tools]
command = "hpc-mcp-relay"
required = true
startup_timeout_sec = 20
tool_timeout_sec = 300
```

The launcher derives `HPC_TOOLS_AGENT_NETWORK_MODE` only from the protected
manifest. The wrapper accepts exactly the three manifest modes in a closed
`case` statement and copies the corresponding packaged file into a new
mode-`0700` `CODEX_HOME` in the container's private temporary filesystem. It
copies only the bundled
`hpc-delegated-slurm` skill into that home. It runs `codex exec` with
`--strict-config`, `--ephemeral`, `--json`, `--sandbox workspace-write`, and
`--skip-git-repo-check`. No Codex conversation rollout is retained inside the
container. Instead, the launcher tees the JSONL event stream and diagnostic
stderr to protected, attempt-specific files under `state_root` while preserving
the parent Slurm stdout and stderr streams. Shell writes remain limited to the
work root selected by the outer Apptainer boundary. The required MCP setting
makes a missing host relay a hard startup failure rather than silently giving
the agent a different tool surface.

These choices follow the supported [Codex non-interactive
mode](https://learn.chatgpt.com/docs/non-interactive-mode) and [Codex MCP
configuration](https://learn.chatgpt.com/docs/extend/mcp). The Apptainer
boundary remains authoritative: the inner Codex sandbox is useful defence in
depth, but its kernel support must be tested on the target compute node.

The skill is operational guidance, not an authorization control. It constrains
the unattended decision loop to the seven lifecycle tools and four fixed
cluster resources, defines idempotency and stopping behavior, and treats logs
and results as untrusted data. The host-side MCP preset and ledger remain
responsible for enforcing the actual tool surface, job ownership, allowlists,
and budget.

## Declare the agent network contract

Manifest version 4 requires one explicit network mode:

```toml
[network]
mode = "model-only"
```

The only accepted modes are `model-only`, `model-indexed-search`, and
`model-live-search`. They map to disabled, indexed, and live Codex web search,
respectively. Command networking remains disabled in every mode. The selected
mode is recorded in `hpc://runtime`, the protected ledger and audit export, and
each controller attempt's provenance. Proxy addresses and credentials do not
belong in the manifest or those public summaries.

The launcher and Codex configuration now enforce this selection within the
harness contract. They do not isolate the container from the shared host
network: a compromised harness may bypass Codex's command sandbox. Production
qualification therefore still requires an independently enforced site egress
policy; selecting indexed or live search is not evidence that such a policy is
installed or effective.

### Keep boundary tests independent of Codex

The `agent-boundary` bundle preserves the minimal Python-and-relay definition
without installing an agent:

```console
hpc write-container --kind agent-boundary restricted-boundary-build
cd restricted-boundary-build
apptainer build --fakeroot restricted-boundary.sif Apptainer.def
apptainer test restricted-boundary.sif
```

Use this fixture for quick development of the negative command checks,
launcher binds, environment filtering, and host relay boundary without an API
credential or the larger Codex installation. It deliberately does not test
Codex startup, authentication, sandbox behavior, or MCP configuration; the
full `agent` image remains necessary for those integration tests.

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

The delegation template, materialized manifest, and ledger must be mode `0600`.
The launcher creates the materialized manifest with that mode. State, work,
output, socket, materialized-manifest parent, and per-job directories are mode
`0700`. Put the SQLite ledger on a filesystem with known-correct locking rather
than assuming every cluster network filesystem is safe for SQLite.

## Configure count and quoted-credit budgets

For the normal batch workflow, start with the generated
`delegation-template.toml`. Replace every illustrative identity, account,
cluster, container, and path, then make it private. The launcher supplies the
exact Slurm parent job ID and UTC timestamps; the template therefore needs no
pre-known job ID. `lifetime_seconds` must be between 60 seconds and 30 days.
The generated identifier is `<id_prefix>-<SLURM_JOB_ID>`.

```console
chmod 600 /protected/delegation-template.toml
install -d -m 700 /protected/materialized-manifests
```

The launcher writes one canonical manifest atomically and refuses to overwrite
an existing path. Its first comment records the exact template hash, selected
profile, parent job ID, and output path without weakening the strict manifest
schema. On a Slurm requeue, it does not regenerate timestamps or authority: it
requires the existing manifest, verifies that record and the current template
hash, reconstructs the expected bytes, and applies ordinary expiry checks
before opening the ledger. A changed template, missing output, expired
authority, or non-canonical manifest fails closed.
`--dry-run` performs the same rendering, validation, and bind-overlap checks in
a temporary file but does not publish the requested manifest output or create a
ledger.

For the advanced pre-materialized workflow, the existing examples remain
available as `examples/delegations/restricted-agent-credit-minimal.toml` and
the full example beside it. Their parsed-object contract is
`examples/delegations/delegation-manifest-v4.schema.json`; pass those files with
`--manifest` rather than the mutually exclusive template options.

Configure the selected profile with a trusted site adapter:

```toml
[profiles.example]
sam_quote_command = "/opt/site/bin/hpc-tools-credit-quote"
sam_quote_format = "hpc-tools-credit-quote-v1"

[profiles.example.capabilities]
version = 1
max_level = "job-lifecycle"
scopes = ["accounting.read", "job.validate"]
```

The adapter must emit the strict maximum-cost JSON envelope documented in
[Configure cluster profiles](configuration.md). Its unit and scale must exactly
match `[credit_budget]`; hpc-tools performs no conversion. The server refuses
to start a credit-bearing controller when either quote setting is missing or
incompatible.

Use both ceilings when the operator needs both kinds of limit:

```toml
[budget]
max_submissions = 20

[credit_budget]
unit = "credits"
scale = 0
maximum_total = 20000
maximum_per_job = 5000
quote_ttl_seconds = 300
```

They are independent, and whichever limit is reached first refuses another
submission. A zero-cost job still consumes one logical submission. One Slurm
array also consumes one logical submission, but its complete array shape is
quoted and its resource use is multiplied by the number of elements. An exact
idempotent replay consumes neither again.

`quote_ttl_seconds` is the interval during which server-issued quote evidence
may authorize a new reservation. It is not a runtime, queue-wait limit, lease,
or reset interval. Expiry requires a fresh quote -> validate -> submit chain;
it does not release a reservation already recorded. A definite scheduler
failure releases count, resources, and quoted maximum. Successful, uncertain,
terminal, and cancelled jobs retain cumulative count and quoted credit for the
delegation lifetime.

The public runtime summary exposes logical usage and consumed/remaining quoted
maxima so the harness can stop deterministically. It intentionally does not
expose the protected ledger, quote command, account balance, or actual charge.
Use `hpc agent audit` or `hpc agent export` from the host for the operator view.

## Start the parent allocation

Adapt the generated `restricted-agent.slurm` and `task.md`. Keep the explicit
`Use $hpc-delegated-slurm` invocation in the reviewed task. Fill in one bounded
objective, application-level success criteria, any required account/container
selection, corrective-resubmission policy, and stopping condition. If these
leave a material choice ambiguous, the skill reports `blocked` rather than
guessing or trying to ask an absent operator.

Place the reviewed task at the path selected by `prompt_file`, make it private
mode `0600`, and submit the script normally. Pass it with `--prompt-file`; the
launcher snapshots that content before using the snapshot as agent stdin. The
essential invocation is:

```bash
hpc-agent-launch \
    --manifest-template /protected/delegation-template.toml \
    --manifest-output "/protected/materialized-manifests/delegation-${SLURM_JOB_ID}.toml" \
    --ledger /protected/delegations.sqlite3 \
    --config ~/.config/hpc-tools/config.toml \
    --profile example \
    --agent-env-file /protected/codex.env \
    --network-env-file /protected/network.env \
    --agent-image /project/images/restricted-codex.sif \
    --prompt-file /protected/reviewed-task.md \
    -- codex-agent -
```

Keep the template's lifecycle directives aligned with the manifest:

```bash
#SBATCH --requeue
#SBATCH --signal=B:USR1@600
#SBATCH --open-mode=append
```

The append mode matters because a requeue retains the parent Slurm job ID. A
site default that truncates `restricted-agent-%j.out` or `.err` on restart would
otherwise destroy the preceding controller attempt's outer log.

### Profile authority across restarts

Starting a restricted controller requires the selected profile to grant C3
(`job-lifecycle`). Before the launcher submits the dependent cleanup job, it
captures that profile policy in the protected delegation ledger together with
the selected configuration path and SHA-256 digest. Each attempt's
`provenance.json` records the same authority evidence.

The capture is an immutable ceiling for that delegation. On every MCP server
start, tools and resources for new work are filtered by the intersection of
the current profile policy, the captured ceiling, and the fixed `slurm-job`
surface. Narrowing the profile therefore takes effect after the server is
restarted, while widening it cannot grant authority that the delegation did
not capture initially. The server never adds general file, repository,
installation, onboarding, or profile-management tools to this preset.

Controller requeue and final cleanup are different: they are obligations for
jobs already accepted under the captured C3 authority. They continue to use
that captured authority even if the editable profile is later narrowed, so a
configuration change cannot silently orphan ledger-owned jobs. A fresh
delegation still requires C3 at its initial launch. Restart the controller/MCP
server after editing the profile; an already running server retains its startup
snapshot.

### Attempt provenance and event logs

Every launched controller generation creates this protected directory:

```text
<state_root>/agent-attempts/generation-<N>/
├── provenance.json
├── delegation.toml
├── task.md                 # when --prompt-file was supplied
├── codex-config.toml       # when readable from the image
├── codex-events.jsonl
└── codex-stderr.log
```

Files are mode `0600` and directories are mode `0700`. `provenance.json`
records hashes for the prompt, manifest, agent image, Codex configuration, and
captured profile policy and configuration; the public network policy and only
the presence and SHA-256 hash of any allowlisted network environment;
the Codex and hpc-tools versions; the exact agent argv; and the Git commit and
dirty flag for both hpc-tools and `work_root` when those directories are Git
checkouts. Template-based runs additionally record the template path, template
format version, template SHA-256, materialized path, and final manifest SHA-256.
The operator audit view repeats both hashes for every controller generation.
Hashing the complete SIF is intentional evidence but can add startup
I/O for a large image. A missing Git checkout or unavailable in-image metadata
is recorded as `null`; it is not guessed.

The ledger receives a `controller_artifacts` audit event pointing to these
files. `codex-events.jsonl` contains every event emitted by `codex exec --json`;
it is an execution trace, not a transcript of private model reasoning.

The batch shell runs the launcher in the background and forwards `USR1`,
`TERM`, and `INT`; replacing that pattern with a foreground invocation can
delay shell trap handling and defeat the advance-warning path.

The launcher requires `SLURM_JOB_ID` to match the manifest and uses the site's
private `SLURM_TMPDIR` for the MCP socket unless `--runtime-directory` selects
another private mode-`0700` directory. The bridge publishes a PID-bearing
readiness marker only after the socket is listening; the launcher verifies that
the marker belongs to the bridge process before starting the agent container.
The socket pathname alone is not treated as readiness. The launcher then invokes
Apptainer with `--containall`, `--cleanenv`, `--no-home`, and
`--no-mount home,cwd,hostfs,bind-paths`. Sites whose Apptainer version or policy
does not support those flags fail closed and must review an adapted launcher;
silently dropping a containment flag is unsafe.

The outer Apptainer environment removes SSH-agent variables, delegation paths,
credentials, ambient proxy/CA variables, `LD_PRELOAD`, and agent-controlled
`APPTAINERENV_`/`SINGULARITYENV_` injections by constructing a small allowlisted
outer environment. Fixed launcher-controlled options set the temporary home,
manifest-selected network mode, and MCP socket path; the separately parsed
private environment file supplies only credentials and explicitly allowlisted
proxy/CA settings. The launcher also requires the agent command to be exactly
`codex-agent -`, so job-script arguments cannot override the selected
configuration or sandbox.

For programmatic Codex use, OpenAI recommends API-key authentication. Put
`OPENAI_API_KEY=<key>` in the protected mode-`0600` environment file outside
all bind roots and select it with `--agent-env-file`. `CODEX_ACCESS_TOKEN` is
also supported for a site that provisions short-lived workload tokens. The
wrapper feeds the value to `codex login`, then removes both credential variables
from the environment before starting the agent. Apptainer reads the file on the
host; the launcher does not print its values or mount the file. The value and
temporary Codex authentication state are necessarily accessible to the parent
agent process, so a compromised agent could still disclose them. Prefer
short-lived, narrowly scoped credentials or an external credential broker. The
file is never passed to delegated jobs. See [Codex
authentication](https://learn.chatgpt.com/docs/auth).

If the site requires a proxy or custom CA, put only the required assignments in
a separate private mode-`0600` file and pass `--network-env-file`. The exact
allowlist is `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, their lowercase variants,
`SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, and
lowercase variants of those CA names. Empty files, duplicates, arbitrary names,
shell-startup variables, loader variables, and `APPTAINER_*` or `SINGULARITY_*`
names are rejected. The credential and network files are parsed into a
launcher-created mode-`0600` environment file under the private runtime
directory; their source paths and values are neither mounted nor printed.
Those variables remain available to the Codex process for authentication and
transport setup, but the packaged shell-environment policy removes every
credential, proxy, CA, mode-selector, and MCP-socket variable from commands
spawned by Codex. Login shells and shell-profile loading are disabled. This is
defence in depth, not a substitute for short-lived credentials: the Codex
process itself must still be trusted with the values it consumes.

## Parent termination and delegated jobs

Before it starts the agent, the launcher submits one small host-side Slurm job
with an `afterany:<parent-job-id>` dependency and records its exact ID in the
protected ledger. This control job runs `hpc-agent-reap`; neither the executable
nor the cleanup script is present in the agent container. It is intentionally
outside the delegation compute budget.

At the advance wall-time warning, the launcher freezes new submissions, stops
the current agent and MCP bridge, and asks Slurm to requeue the exact parent job
ID. A successful requeue preserves delegated jobs. The restarted parent gets a
new controller generation and must reconcile every active owned job through
`hpc_jobs` before the ledger permits another submission. Codex state is
ephemeral, so the new attempt reconstructs progress from the reviewed task,
runtime resource, ledger-owned IDs, and durable job artifacts.

When the parent reaches a final state, the dependent cleanup job applies the
manifest policy. The defaults are:

```toml
[lifecycle]
on_cancel = "cancel"
on_timeout = "requeue-or-cancel"
on_failure = "cancel"
on_normal_exit_with_active_jobs = "cancel"
max_requeues = 3
warning_seconds = 600
```

Explicit parent cancellation, failed or exhausted requeue, final timeout,
failure, and normal exit with active jobs therefore cancel only the exact
active job IDs owned by that delegation. `leave-running` is possible only when
the protected manifest explicitly selects it. It does not transfer ownership;
the operator must retain a procedure for observing and cancelling those jobs.

The cleanup job first checks `squeue` and then `sacct`, records idempotent
cancellation operations, and reconciles jobs that already ended naturally. A
parent still seen as pending, running, or requeued is not treated as terminal.
Cleanup failures are written to `cleanup-%j.err` and the ledger's
`controller_cleanup` row for operator recovery.

Inspect or export the joined operator view without opening SQLite manually:

```console
hpc agent audit \
    --ledger /protected/delegations.sqlite3 \
    --database ~/.config/hpc-tools/submissions.sqlite3 \
    --delegation-id agent-001

hpc agent export \
    --ledger /protected/delegations.sqlite3 \
    --database ~/.config/hpc-tools/submissions.sqlite3 \
    --delegation-id agent-001 \
    --output /protected/agent-001-audit.json
```

Both commands read the databases in SQLite read-only mode. The report joins
controller attempts and their provenance/log artifacts, authorization audit
events, lifecycle operations, owned Slurm IDs, submission-history events,
delegated output directories, wrapper status, and cleanup state. Export refuses
to overwrite by default and creates a mode-`0600` JSON file. The report may
contain sensitive paths, commands, stderr, or application metadata; sanitize it
before moving it outside the protected operator environment.

This is eventual cleanup, not immediate cleanup: the control job can wait for
resources. Sites that prohibit nested `sbatch`, cannot reliably retain a
dependency across requeue, or require a strict cancellation-latency bound need
a persistent broker on a service or login node instead. Verify the chosen
behavior with the [real-cluster qualification
checklist](development/real-cluster-qualification.md) before production use.

There is another consequence of the dependent-job design: if a requeued parent
remains pending past manifest expiry, no new MCP operation is authorized, but
the cleanup dependency is not yet eligible. Existing delegated jobs are cleaned
only after the parent becomes final. A site that needs cancellation at the
exact expiry time needs a persistent broker or a separately reviewed Slurm
deadline mechanism.

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

- The packaged image currently targets Codex CLI only. Its pinned Codex and
  Node versions require deliberate maintenance, and an OCI digest should be
  recorded for reproducible deployment. Other agent runtimes need their own
  reviewed definition, entrypoint, MCP configuration, and negative tests.
- The generated delegate wrapper currently supports one Slurm node and one
  task, including multiple CPUs assigned to that task. Job arrays are supported.
  Multi-task, multi-node, GPU, and GRES requests fail closed until a site adds
  reviewed `srun`, MPI/PMI, and Apptainer device integration; silently allocating
  resources that the container cannot use would be worse.
- The launcher assumes `sbatch` from within the parent allocation is permitted.
  Sites that prohibit nested submissions need a durable broker on an approved
  service or login node and a separately authenticated transport.
- Parent requeue permission, advance-signal delivery, and `afterany` behavior
  across same-ID requeues are site policy. The automated suite checks state and
  command construction but cannot establish those properties for a cluster.
- The dependent cleanup job provides eventual best-effort enforcement. A
  scheduler outage or queued cleanup job delays cancellation and requires
  operator inspection of its ledger status and logs.
- A pending requeued parent can delay dependency-based cleanup beyond manifest
  expiry. The expired manifest blocks further authority; it does not itself
  make the cleanup job schedulable.
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
  follow the [real-cluster qualification
  checklist](development/real-cluster-qualification.md) on each target site;
  unit tests cannot establish the site's Apptainer or Slurm policy.
