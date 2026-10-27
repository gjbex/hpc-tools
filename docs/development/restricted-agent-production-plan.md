# Restricted-agent production implementation plan

Status: proposed on 2026-10-26; no work package in this plan is complete.

This plan closes the remaining gap between the implemented restricted-agent
boundary and a production-qualified Codex harness running in an Apptainer
container inside a Slurm allocation. It builds on the existing
[restricted-agent deployment guide](../restricted-agent.md),
[parent-agent lifecycle](../parent-agent-lifecycle.md), and
[real-cluster qualification checklist](real-cluster-qualification.md).

The implementation must keep the host-side `hpc-mcp` process, profile,
delegation manifest, authorization ledger, scheduler commands, and scheduler
credentials outside the harness container. The container receives only the
restricted MCP relay, explicitly declared filesystem mounts, its model
credential, and the network capability selected by the protected operator
policy.

## Required outcome

A production candidate must provide all of the following:

- a reproducible, digest-identified Codex SIF built from the reviewed
  definition file;
- a parent batch template that can start from an operator-reviewed delegation
  template without knowing the Slurm job ID in advance;
- an explicit fail-closed choice between model-only access, indexed web search,
  and live web search;
- no command-network access for model-generated shell commands in the initial
  implementation;
- no host home, scheduler client, scheduler credential, manifest, ledger, or
  undeclared writable path inside the harness container;
- a private single-client Unix socket as the only MCP capability channel;
- recorded image, configuration, task, manifest, policy, and source
  provenance; and
- evidence from the complete real-cluster qualification checklist for every
  supported site and partition.

Local tests can establish command construction, parsing, packaging, and
fail-closed behavior. They cannot establish Slurm requeue policy, dependent-job
semantics, Apptainer site mounts, SQLite behavior on a cluster filesystem, or
network enforcement on a compute node.

## Current baseline

The current checkout already provides:

- `hpc_tools/data/containers/agent/Apptainer.def`, with pinned Codex and Node
  versions and negative checks for SSH, Slurm, and Munge commands;
- `codex-agent`, which creates an ephemeral `CODEX_HOME`, installs only the
  image-specific delegated Slurm skill, and runs non-interactive Codex;
- `hpc-mcp-relay` and `hpc_tools.mcp_bridge`, which connect one container-side
  stdio client to one private host-side Unix socket;
- `hpc-agent-launch`, which validates private paths, starts the `slurm-job` MCP
  preset outside the container, applies explicit binds and containment flags,
  records attempt provenance, and manages controller lifecycle;
- a restricted seven-tool MCP surface with quote, validate, submit, observe,
  account, cancel, ownership, idempotency, resource-budget, and quoted-credit
  enforcement;
- `restricted-agent.slurm`, including advance warning, same-ID requeue, append
  logs, and signal forwarding; and
- local tests covering the packaged bundle, boundary command construction,
  ledger behavior, lifecycle, cleanup, and MCP restrictions.

The supported local suite passed 478 tests on 2026-10-26 after the repository
uv pin was updated to 0.13.5. Plugin and skill validation also passed.
Repository hygiene remained independently blocked by existing generated build,
cache, egg-info, and bytecode artifacts; those artifacts are not evidence about
the restricted-agent boundary.

## Frozen decisions for this plan

These decisions deliberately keep the first production pilot narrow. Changing
one requires an explicit plan update and synchronized fixture changes.

1. **Codex only.** Other harnesses need separate images, entrypoints,
   configuration, authentication, and negative tests.
2. **Single node and one Slurm task.** Multiple CPUs and arrays remain
   supported. Multi-task, multi-node, GPU, and GRES support remain out of scope.
3. **No TCP MCP listener.** The private Unix socket remains the only MCP
   transport into the container.
4. **No host-home configuration copy.** The image contains reviewed Codex
   configuration. The host `hpc-tools` profile remains host-only.
5. **No arbitrary command egress.** The initial network contract always sets
   Codex workspace command networking to disabled. Model/authentication traffic
   and hosted web search are separate capabilities.
6. **Three network modes only:** `model-only`, `model-indexed-search`, and
   `model-live-search`. Unknown or omitted modes fail closed.
7. **Site controls enforce egress.** Codex sandbox settings are defence in
   depth, not the outer network boundary. A compute-node firewall,
   administrator-approved network namespace, or allowlisting proxy must enforce
   destination policy.
8. **No inbound port mapping.** The harness requires outbound model traffic;
   mapping a host port into the container does not grant or constrain that
   traffic.
9. **The trusted launcher materializes the final manifest.** The batch job does
   not need a pre-known Slurm job ID, and the initial implementation does not
   add an `sbatch --hold`/`scontrol release` bootstrap dependency.
10. **Existing profile and delegation limits remain authoritative.** Network
    policy narrows the run; it never expands profile, scheduler, filesystem, or
    credit authority.

## Target topology

```text
Slurm parent allocation, host namespace
├── hpc-agent-launch
│   ├── materialized private delegation manifest
│   ├── protected hpc-tools profile and authorization ledger
│   ├── hpc-mcp --executor local --preset slurm-job
│   ├── Slurm/Munge clients and scheduler credentials
│   └── private single-client Unix socket in SLURM_TMPDIR
└── Apptainer Codex harness
    ├── reviewed network-mode-specific Codex configuration
    ├── ephemeral CODEX_HOME and authentication state
    ├── hpc-mcp-relay
    ├── work_root                                  read/write
    ├── output_root and input_roots                 read-only
    └── no home, ledger, manifest, Slurm, SSH, or Munge access
```

## Dependency order

| Work package | Deliverable | Depends on |
| --- | --- | --- |
| WP1 | Protected network-policy contract | Current manifest and runtime baseline |
| WP2 | Network-mode enforcement in image and launcher | WP1 |
| WP3 | Atomic manifest-template materialization | WP1 |
| WP4 | Reproducible image identity and build workflow | WP2 |
| WP5 | Hardened parent batch template and operator documentation | WP2, WP3, WP4 |
| WP6 | Local and installed-distribution acceptance | WP1--WP5 |
| WP7 | Real-cluster pilot and qualification decision | WP6 |

Each work package should be a reviewable change. Do not enable a partially
implemented network mode, manifest version, or batch workflow merely because a
later package is planned.

## WP1: Protected network-policy contract

Targets: `hpc_tools/delegation.py`, delegation examples and schema,
`hpc_tools/mcp/resources.py`, runtime summaries, audit/provenance fixtures, and
delegation tests.

Work:

1. Bump the delegation manifest to version 4. Version 3 is a frozen
   quoted-credit contract and must be rejected rather than silently migrated.
2. Add one required strict table:

   ```toml
   [network]
   mode = "model-only"
   ```

   Accepted values are exactly `model-only`, `model-indexed-search`, and
   `model-live-search`. Reject unknown keys, missing tables, duplicate keys,
   unsupported modes, and wrong types before any ledger or scheduler access.
3. Add an immutable `AgentNetworkPolicy` value to `DelegationManifest`. Map the
   three modes to `disabled`, `indexed`, and `live` Codex web-search settings.
   All modes retain disabled command networking.
4. Include the selected mode in the manifest public summary, `hpc://runtime`,
   attempt provenance, audit export, and relevant authorization events. Do not
   expose proxy credentials or private network configuration.
5. Update the versioned JSON schema, minimal/full examples, frozen fixtures,
   the image-only skill, and documentation in the same change.
6. Decide whether the current ledger columns can retain the policy through the
   canonical manifest digest and audit event. If a queryable network field is
   added to a protected table, bump the ledger schema and reject the old schema;
   do not perform an implicit migration.

Tests:

- parser acceptance for all three modes;
- rejection of version 3, absent policy, unknown mode, and unknown keys;
- public/private serialization boundaries;
- runtime and audit summaries contain the selected mode but no private network
  data;
- expiry, parent binding, credit policy, and existing allowlists remain
  unchanged.

Exit criteria: one protected manifest unambiguously selects the web-search
capability, and no runtime component needs to infer policy from environment
variables or Codex defaults.

## WP2: Network-mode enforcement

Targets: `hpc_tools/data/containers/agent/codex-config*.toml`, `codex-agent`,
`Apptainer.def`, `hpc_tools/restricted_launch.py`, boundary tests, and packaged
bundle tests.

Work:

1. Package three complete, reviewed Codex configuration files. Each must make
   `hpc-mcp-relay` required, set the selected `web_search` mode explicitly, and
   set workspace command network access to false.
2. Have the launcher derive the container network mode only from the parsed
   protected manifest and pass it as a fixed launcher-controlled value. Do not
   accept an independent job-script or agent-command override.
3. Make `codex-agent` select exactly one packaged configuration through a
   closed `case` statement. Missing or unknown values must exit before login or
   MCP initialization.
4. Keep `--strict-config`, `--ephemeral`, JSONL output, workspace-write
   sandboxing, and the required MCP setting.
5. Replace accidental proxy inheritance with an explicit network environment
   contract. If a site needs `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, a custom
   CA bundle, or related lower-case variants, read them from a separate
   operator-owned mode-0600 file outside every bind root. Parse and copy only an
   exact allowlist into a launcher-created private environment file. Reject
   `APPTAINER_*`, `SINGULARITY_*`, loader, shell-startup, and arbitrary variable
   names.
6. Do not place secret proxy values in argv, logs, provenance, or the public
   runtime resource. Record only whether an allowlisted network environment was
   supplied and its content hash.
7. Retain the current no-home, no-CWD, no-hostfs, no-default-bind, clean
   environment, and explicit filesystem bind behavior.
8. Document that these settings do not stop a compromised harness from using
   the shared host network outside the Codex sandbox. Qualification therefore
   requires an independently enforced site egress policy.

Tests:

- exact mode-to-config selection;
- no mode override through the agent command or ambient environment;
- command networking is false in every packaged configuration;
- required MCP initialization remains fail-closed;
- proxy/CA allowlist acceptance and rejection;
- secrets absent from dry-run output, provenance, and diagnostics;
- ambient `APPTAINERENV_` and `SINGULARITYENV_` injection remains blocked;
- all current mount and forbidden-command tests remain green.

Exit criteria: the protected manifest deterministically selects the Codex
web-search mode, while command-network access stays disabled and network secrets
do not cross unrelated interfaces.

## WP3: Atomic manifest-template materialization

Targets: a new strict template parser, `hpc_tools/restricted_launch.py`, agent
container assets, delegation tests, lifecycle tests, and operator docs.

Work:

1. Define a version-1 operator template containing all delegation authority
   except `parent_job_id`, `issued_at`, and `expires_at`. Add bounded
   `lifetime_seconds` and an `id_prefix`; the launcher forms a stable delegation
   ID using the exact Slurm parent job ID.
2. Add mutually exclusive launcher modes:

   - existing `--manifest PATH` for an already materialized advanced-operator
     workflow; or
   - `--manifest-template PATH --manifest-output PATH` for the normal batch
     workflow.

3. On the first controller generation, parse and validate the private template,
   inject `SLURM_JOB_ID` and launcher-owned UTC timestamps, render canonical
   manifest TOML, and create the output atomically with mode `0600`, no symlink
   traversal, and no overwrite.
4. On requeue, never regenerate or extend authority. Require the existing
   manifest to match the template hash, profile, parent job ID, and output path;
   then apply the ordinary expiry and lifecycle checks.
5. If first-generation materialization fails, start neither the MCP bridge nor
   the agent container and leave a clear protected diagnostic. Do not create or
   mutate the ledger before the final manifest validates.
6. Record template and final-manifest hashes in attempt provenance and the
   operator audit view.
7. Keep manifest templates and materialized manifests outside all container bind
   roots. Do not add them to the Codex image or plugin skill bundle.

Tests:

- deterministic field injection with a fixed clock and job ID;
- atomic creation, permissions, symlink rejection, and existing-file refusal;
- no authority extension on requeue;
- mismatch and expiry failures occur before bridge, container, ledger, or
  scheduler effects;
- existing pre-materialized-manifest mode remains valid;
- template and manifest paths cannot overlap exposed roots.

Exit criteria: an operator can submit the parent script through the existing
validated Slurm workflow without knowing its job ID in advance, and requeue
cannot refresh or widen the original delegation.

## WP4: Reproducible image identity and build workflow

Targets: `Apptainer.def`, packaged agent bundle, optional build-job template,
launcher image validation, documentation, and distribution tests.

Work:

1. Replace the mutable OCI base reference with the reviewed tag plus digest.
   Retain exact Node and Codex versions and update the label and `%test`
   assertion together when either changes.
2. Add a documented update procedure that records the upstream base digest,
   Codex version, definition diff, build command, SIF SHA-256, and test result.
3. Add a required expected parent-agent image SHA-256 to the reviewed launch
   inputs. The launcher hashes the SIF before starting the MCP bridge and fails
   on mismatch. Do not rely only on path and file permissions.
4. Keep built SIFs, Apptainer caches, build roots, and credentials out of Git.
5. Provide a small build-job template when image construction is too expensive
   for a login node. It must use site-selected project/scratch storage and a
   private cache, and must stage the final SIF plus checksum to durable storage.
6. Retain the fast `agent-boundary` image so mount, socket, and environment
   tests do not require Codex authentication or the full image.
7. Consider SIF signing as a site deployment option. SHA-256 verification is
   mandatory for this plan; signature trust configuration is site-specific.

Tests and checks:

- packaged definition contains a digest-pinned base and exact Codex version;
- expected digest accepts the intended SIF and rejects a modified copy before
  bridge startup;
- `apptainer test` succeeds for both boundary and full agent images;
- the full image still contains no SSH, Slurm, or Munge command;
- the image contains no copied user home, auth cache, manifest, ledger, or
  host profile;
- generated bundles and source/wheel distributions contain all required
  templates and no SIF artifact.

Exit criteria: the exact parent-agent image used by a run is reviewed,
identified before execution, and recorded in provenance.

## WP5: Parent batch template and operator workflow

Targets: `restricted-agent.slurm`, `task.md`, `docs/restricted-agent.md`,
reference documentation, troubleshooting, and template tests.

Work:

1. Change the generic template to `#!/bin/bash -l`, or establish an equally
   explicit site-independent environment contract. Add early checks for
   `hpc-agent-launch`, the configured Apptainer executable, the protected input
   files, and their permissions.
2. Use the manifest-template launcher mode and derive the materialized manifest
   path from a protected directory plus `SLURM_JOB_ID`.
3. Keep `--requeue`, advance `USR1`, append-mode logs, and background launcher
   signal forwarding. State that `warning_seconds` must equal the `#SBATCH`
   warning value.
4. Keep account, cluster, partition, QoS, reservation, memory, and module lines
   as explicit site adaptations. Do not guess an account or enable a generic
   default partition.
5. Support `--runtime-directory` when the site does not provide a private
   `SLURM_TMPDIR`; require the selected directory to be owner-only mode `0700`.
6. Separate the model credential file from the optional network environment
   file. Both remain mode `0600` and outside every bind root.
7. Preserve a reviewed, bounded task contract with objective, application-level
   success criteria, authorized selections, corrective-resubmission policy, and
   stopping condition.
8. Document parent-job quotation and confirmation separately from delegated-job
   budgets. The parent allocation and its dependent cleanup job are real site
   workloads even though they are outside the delegated computation budget.

Tests:

- template contains the required lifecycle directives and launcher options;
- signal traps still forward and wait correctly;
- no secret, manifest content, or ledger path is copied into the image;
- template generation produces a complete self-contained bundle;
- shell syntax validation for every packaged script;
- documentation examples agree with parser, launcher, and template behavior.

Exit criteria: the generated job script is a safe generic template with a
documented, finite set of site substitutions rather than illustrative steps
that hide required authority or lifecycle decisions.

## WP6: Local and installed-distribution acceptance

Targets: unit tests, acceptance tools, package-data tests, capability snapshots,
documentation tests, and wheel/source-distribution checks.

Work:

1. Add an acceptance scenario for each network mode using the boundary image or
   a fake Apptainer executable. Verify exact argv, configuration choice,
   environment filtering, socket bind, and protected-path omission.
2. Exercise first start, requeue, expired manifest, malformed template, wrong
   image digest, missing model credential, MCP startup failure, and agent failure.
3. Verify no network-policy or manifest-template change alters the seven-tool
   `slurm-job` surface or adds a general filesystem/network/shell tool.
4. Update capability and distribution snapshots deliberately. Treat unexpected
   discovery changes as failures, not snapshot-refresh chores.
5. Build source and wheel distributions and run the restricted boundary from an
   installed artifact, not only the checkout.
6. Run the repository validation contract:

   ```bash
   uv lock --check
   uv run --no-project --python 3.13 python tools/validate_plugin.py .
   uv run --no-project --python 3.13 python tools/validate_skills.py .
   uv run --no-project --python 3.13 python tools/check_repo_hygiene.py .
   uv sync --locked --all-extras --all-groups
   uv run --locked --no-sync python -m py_compile \
       hpc_tools/*.py hpc_tools/plugins/*.py hpc_tools/plugins/cxx/*.py \
       hpc_tools/plugins/python/*.py hpc_tools/plugins/r/*.py \
       hpc_tools/commands/*.py hpc_tools/mcp/*.py tests/*.py tools/*.py
   uv run --locked --no-sync python -m unittest discover -s tests
   ```

Exit criteria: checkout and installed-distribution tests establish the frozen
local contract, all documentation and examples are synchronized, and any
repository-hygiene blocker is resolved or reported independently.

## WP7: Real-cluster pilot and qualification

Targets: one explicitly selected low-cost cluster/partition and the existing
real-cluster qualification checklist. Pilot evidence belongs in protected
operator storage, not this repository.

Work:

1. Record cluster, partition, account, QoS, Slurm version, Apptainer version,
   hpc-tools revision, image digest, template digest, and site policy.
2. Obtain site approval for nested `sbatch`, same-ID requeue, advance signals,
   dependency cleanup, Apptainer execution, and the selected egress mechanism.
3. Quote and validate the parent allocation with the exact site resource shape.
   Use a short wall time, small delegation budgets, disposable paths, and no
   production data.
4. Build or install the reviewed SIF, run `apptainer test`, and verify every
   containment flag on the target compute node.
5. For `model-only`, prove model/authentication traffic succeeds, hosted search
   is unavailable, command-network access is disabled, and direct disallowed
   destinations are blocked by the independent site egress control.
6. Repeat the relevant checks for indexed and live search only if those modes
   are intended to be supported at that site. Treat web and job output as
   untrusted prompt-injection inputs.
7. Exercise normal delegated completion, active work across parent requeue,
   explicit parent cancellation, failed or exhausted continuation, cleanup
   retry, and an unrelated control job.
8. Qualify native credit quotations and reconcile the joined audit export with
   Slurm and site-accounting evidence.
9. Have a second operator review the evidence and record `qualified`,
   `qualified with restrictions`, or `not qualified` for the exact tested
   combination.

Exit criteria: every applicable item in
`docs/development/real-cluster-qualification.md` has evidence, all pass criteria
hold, and the tested site/version combination has an explicit reviewed status.

## Security review checklist

Complete this review in WP6 and repeat it during WP7:

- The agent image has no scheduler, SSH, Munge, ledger, manifest, or host-profile
  authority.
- The private MCP socket is single-client, same-UID checked, owner-only on the
  host, and never passed to delegated worker containers.
- Unknown manifest, template, ledger, and network-policy versions fail closed.
- Network mode cannot be widened by ambient environment, task text, agent argv,
  job output, or MCP data.
- Credentials and proxy secrets do not appear in argv, dry-run output, JSONL
  events, Slurm logs, provenance, audit summaries, or exported examples.
- `work_root` is the only writable parent bind; output and inputs remain
  read-only to the parent; state, manifest, ledger, and network files do not
  overlap any bind root.
- Parent requeue never refreshes expiry, budget, image identity, or network
  authority.
- Cleanup affects all and only exact ledger-owned active jobs.
- Web search, application output, logs, and cluster references are treated as
  untrusted data and cannot expand capabilities.
- The limitations of the shared host kernel, same Unix UID, model credential,
  and eventual dependent-job cleanup are stated plainly.

## Deferred work

The following are not blockers for the first qualified pilot:

- arbitrary command egress from the Codex workspace;
- multi-node, multi-task, MPI, GPU, or GRES delegated jobs;
- other harness implementations;
- automatic credential brokerage or secretless workload identity;
- a persistent service broker for strict cleanup deadlines or sites that reject
  nested submission;
- automatic image-version discovery or unattended image refresh; and
- cross-site qualification portability. Every site/version combination must be
  qualified independently.

## Completion definition

This plan is complete only when WP1--WP6 are implemented and locally accepted,
WP7 has produced a reviewed qualification decision for at least one target
site, and the user-facing documentation clearly separates:

- locally tested software behavior;
- operator-selected policy and credentials;
- cluster-enforced scheduler, storage, and network controls; and
- limitations that remain unverified or deliberately unsupported.
