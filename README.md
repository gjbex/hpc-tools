# hpc-tools

`hpc-tools` provides a small `hpc` command for common SSH and Slurm interactions
with remote HPC systems. Hosts are configured as named profiles, so the same
commands can target `genius`, another login node, or a local SSH alias.

## Install

For normal released use, install the CLI with `pipx`:

```bash
pipx install hpc-tools
pipx ensurepath
hpc --help
```

From the repository root, use `pipx` only when testing a local release-style
install:

```bash
pipx install .
```

Use an editable install only when developing `hpc-tools` itself:

```bash
python3 -m pip install --user -e .
```

## Plugins

`hpc-tools` now supports plugin commands. The core CLI keeps generic SSH,
reference, and Slurm functionality, while language- or workflow-specific
helpers can live in plugins.

The repository currently ships a bundled `r` plugin, so after installation you
can use:

```bash
hpc plugins list
hpc plugins info r
hpc r scan path/to/script-or-project
hpc --profile <profile> r check path/to/script-or-project --module R/<version>
hpc --profile <profile> r plan-install path/to/script-or-project --module R/<version> --partition <partition> --output install-r-packages.slurm
hpc --profile <profile> r submit-install install-r-packages.slurm --directory <remote-dir> --account <account>
hpc --profile <profile> r verify-install --job-output <remote-job-output> --package <pkg>
```

Future external plugins can be installed into the same `pipx` environment with
`pipx inject`, for example:

```bash
pipx inject hpc-tools hpc-tools-r
```

The first-slice plugin design and follow-on work are documented in
[docs/plugins.md](docs/plugins.md).

## Configuration

By default, `hpc` reads:

```text
$XDG_CONFIG_HOME/hpc-tools/config.toml
```

When `XDG_CONFIG_HOME` is not set, it falls back to:

```text
~/.config/hpc-tools/config.toml
```

Path precedence is: explicit `--config`, then `HPC_TOOLS_CONFIG`, then
`XDG_CONFIG_HOME`, then `~/.config`.

Two example configuration files are provided:

- [examples/ssh-alias-config.toml](examples/ssh-alias-config.toml) uses a target
  from `~/.ssh/config`, such as `ssh genius`.
- [examples/user-host-config.toml](examples/user-host-config.toml) uses explicit
  `user` and `host` fields.

SSH alias example:

```toml
default_profile = "genius"

[profiles.genius]
ssh_target = "genius"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
projects_dir = "$VSC_DATA/Projects"
quota_command = "myquota"
queue_command = "slurm_queuestate"
sam_balance_command = "sam-balance"
sam_statement_command = "sam-statement"
sam_quote_command = "sam-quote"
hardware_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/hardware.md"
hardware_url = "https://docs.vscentrum.be/leuven/tier2_hardware.html"
slurm_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/slurm.md"
slurm_url = "https://docs.vscentrum.be/leuven/slurm_specifics.html"
storage_reference = "~/.config/hpc-tools/profiles/kuleuven-tier2/storage.md"
storage_url = "https://docs.vscentrum.be/leuven/tier2_hardware/storage.html"
default_cluster = "wice"
email = "user@example.org"
```

`ssh_target` is passed directly to `ssh`, so it can be a configured SSH alias
from `~/.ssh/config`. For example, if `ssh genius` already expands to the right
host, username, agent forwarding, and credentials, use `ssh_target = "genius"`.
`ssh_options` is passed before the target; `["-x"]` disables X11 forwarding for
non-interactive commands.

User/host example:

```toml
[profiles.some-cluster]
host = "login.somewhere"
user = "myuser"
ssh_options = ["-x"]
```

`projects_dir` is interpreted by the remote shell. Values such as
`$VSC_DATA/Projects` are intentionally not expanded locally.

`email` is optional. When it is present, `hpc write-hardware-probe` and
`hpc install-hardware-probe` can add Slurm email notifications with
`--mail-notifications`. The generated script uses `#SBATCH --mail-type=END,FAIL`
and never requests start notifications. Use `--mail-user <address>` to add
notifications with an explicit address instead of a configured profile email.

`quota_command`, `queue_command`, `sam_balance_command`,
`sam_statement_command`, and `sam_quote_command` are optional. If a profile does
not define one of them, the corresponding `quota`, `queue`, `balance`,
`statement`, or `quote` subcommand is hidden from help for that profile and
rejected if invoked anyway.

`hardware_reference`, `hardware_url`, `slurm_reference`, `slurm_url`,
`storage_reference`, and `storage_url` are optional metadata fields. They let
users and Codex skills inspect site-specific hardware, partitions, filesystems,
and Slurm policy without hardcoding those details in the generic skills. Local
reference files should be concise Markdown summaries of the relevant web
documentation.

`reference_set` is optional. When it is set, `hpc hardware` resolves hardware,
Slurm, and storage references from the shared reference set under
`~/.config/hpc-tools/reference-sets/<name>/` before falling back to any
profile-local reference paths. This is the preferred way to reuse one
cluster-wide reference bundle across multiple users.

Keep generated profile references outside the repository so the checkout can be
deleted after installation. The recommended layout is under the hpc-tools config
directory, normally `$XDG_CONFIG_HOME/hpc-tools` or `~/.config/hpc-tools`:

```text
<hpc-tools-config-dir>/
├── config.toml
├── reference-sets/
│   └── <name>/
│       ├── manifest.toml
│       ├── hardware.md
│       ├── slurm.md
│       ├── storage.md
│       └── probe-hardware-report.md
└── profiles/
    └── <profile>/
        ├── hardware.md
        ├── slurm.md
        ├── storage.md
        ├── partition-report.md
        ├── probe-hardware-report.md
        └── probe-results/
```

Point the profile at those durable files:

```toml
[profiles.example]
ssh_target = "example"
login_shell = ["bash", "-l", "-c"]
hardware_reference = "~/.config/hpc-tools/profiles/example/hardware.md"
slurm_reference = "~/.config/hpc-tools/profiles/example/slurm.md"
storage_reference = "~/.config/hpc-tools/profiles/example/storage.md"
```

Or attach a shared reference set:

```toml
[profiles.example]
ssh_target = "example"
login_shell = ["bash", "-l", "-c"]
reference_set = "kuleuven-tier2"
```

## Commands

```bash
hpc run 'hostname'
hpc paths
hpc plugins list
hpc plugins info r
hpc r scan Script/Main_casestudy1.R
hpc --profile genius r check Script/Main_casestudy1.R --module R/4.4.2-gfbf-2024a --cran-bundle R-bundle-CRAN/2024.11-foss-2024a --bioc-bundle R-bundle-Bioconductor/3.20-foss-2024a-R-4.4.2
hpc --profile genius r plan-install Script/Main_casestudy1.R --module R/4.4.2-gfbf-2024a --cran-bundle R-bundle-CRAN/2024.11-foss-2024a --bioc-bundle R-bundle-Bioconductor/3.20-foss-2024a-R-4.4.2 --partition batch_icelake --output install-r-packages.slurm
hpc --profile genius r submit-install install-r-packages.slurm --directory $VSC_DATA/Projects/demo/Script --account <account>
hpc --profile genius r verify-install --job-output /path/to/job.out --package PrevMap --package INLA --package dlnm
hpc references list
hpc references create kuleuven-tier2
hpc references export kuleuven-tier2 --output kuleuven-tier2-reference-set.tar.gz
hpc references import kuleuven-tier2-reference-set.tar.gz
hpc references attach kuleuven-tier2
hpc references detach
hpc write-probe --kind hardware hardware-probe.slurm
hpc write-probe --kind cuda-device-properties cuda-probe/
hpc install-probe --kind hardware --directory <remote-dir>
hpc install-probe --kind cuda-device-properties --directory <remote-dir>
hpc write-hardware-probe hardware-probe.slurm
hpc install-hardware-probe --directory <remote-dir>
hpc quota                  # if quota_command is configured
hpc projects
hpc clone https://github.com/org/repo.git --branch main
hpc module-spider Rust
hpc queue                  # if queue_command is configured
hpc balance                # if sam_balance_command is configured
hpc statement --account <account> --start 2026-01-01 --end 2026-01-31
hpc quote srun -M wice -p gpu_a100 -N 1 --gpus=2 -t 02:00:00 -A <account>
hpc hardware               # if hardware or Slurm reference metadata is configured
hpc hardware --source
hpc hardware --path
hpc jobs                  # defaults to --cluster all
hpc jobs --cluster wice
hpc submit job.slurm
hpc submit --test-only job.slurm
hpc submit --validate-first job.slurm
hpc submit --array 4 --time 00:05:00 --cpus-per-task 4 job.slurm
hpc submit --gpus-per-node 1 --gpu-bind closest gpu-job.slurm
hpc submit --cluster mindwell --partition gpu_b200 --reservation pilot --gpus-per-node 1 gpu-job.slurm
hpc sacct 123456 --cluster wice
hpc submissions list
hpc submissions observe
hpc submissions mark-collected <run-id> --path results/
hpc submissions mark-analysed <run-id> --path reports/benchmark.md
hpc submissions close <run-id> --reason done
```

Use `--profile` to select a profile and `--dry-run` to print the SSH command
without executing it:

```bash
hpc --profile genius --dry-run run 'cd "$VSC_DATA/Projects/foo" && git status'
```

`hpc paths` is a local command that does not require a configured profile. Use
it to inspect the config location, durable profile-reference location, copied
Codex skill location, shared reference-set location, packaged hardware-probe
template, packaged CUDA device-property template/source, and uninstall cleanup
notes.

`hpc references` manages shareable cluster reference bundles:

- `hpc references create <name>` copies the selected profile's effective
  hardware, Slurm, storage, and probe-hardware references into
  `~/.config/hpc-tools/reference-sets/<name>/`.
- `hpc references export <name>` writes a `.tar.gz` archive that another user
  can import with `hpc references import`.
- `hpc references attach <name>` writes `reference_set = "<name>"` into the
  selected profile so `hpc hardware` resolves the shared bundle.

The detailed workflow and follow-on implementation plan live in
[docs/reference-sets.md](docs/reference-sets.md).

`hpc submit --validate-first` runs `sbatch --test-only` with the same options
and submits only if validation succeeds. `hpc submit` records successful real
Slurm submissions in an append-only local event log at
`~/.config/hpc-tools/submissions.jsonl`. Use
`hpc submissions list` to show active submissions, `hpc submissions observe` to
append current Slurm accounting observations for active jobs, and
`hpc submissions close <run-id>` to hide handled runs from the default active
view. The log remains append-only; current state is derived by replaying events.

## Scope

The initial implementation deliberately avoids destructive operations. Cleanup,
job cancellation, and file deletion should remain explicit until the command
surface has enough validation and safeguards.

## Uninstall

Remove the installed Python package and `hpc` console command with:

```bash
pipx uninstall hpc-tools
```

This does not remove user-managed state such as copied Codex skills, profile
configuration, generated references, or remote probe output. Run `hpc paths`
before uninstalling if you want to inspect those locations. The durable local
state is normally under `$XDG_CONFIG_HOME/hpc-tools` or `~/.config/hpc-tools`;
copied skills are normally under `~/.codex/skills`.

## Hardware Probing

For clusters where hardware documentation is missing or incomplete, generate
the packaged Slurm probe script locally for inspection or editing:

```bash
hpc write-probe --kind hardware hardware-probe.slurm
hpc write-hardware-probe hardware-probe.slurm
hpc --profile example write-hardware-probe hardware-probe.slurm --mail-notifications
```

To install the packaged probe script directly on the remote system, use:

```bash
hpc --profile example install-probe --kind hardware --directory <remote-dir>
hpc --profile example install-hardware-probe --directory <remote-dir>
hpc --profile example install-hardware-probe --directory <remote-dir> --mail-notifications
```

It records CPU/cache hierarchy, NUMA hints, memory, filesystems, block devices,
memory bandwidth/latency through Intel MLC when available, GPU inventory when
available, and relevant Slurm environment variables from inside a real
allocation. The repository also keeps a readable copy at
[examples/job-scripts/hardware-probe.slurm](examples/job-scripts/hardware-probe.slurm).

Adapt site-required `#SBATCH` directives such as `--account`, `--clusters`, or
`--partition`. For meaningful Intel MLC results, probe an entire node: keep
`#SBATCH --exclusive`, and on sites that enforce CPU cgroups add a
partition-specific `#SBATCH --cpus-per-task=<full-node-core-count>`. Also adjust
`#SBATCH --time` if Intel MLC or other probes take longer on the target node.
When the profile defines `email`, add `--mail-notifications` for long-queued
probe jobs if the user wants completion/failure notifications.
Then submit with:

```bash
hpc submit hardware-probe.slurm --directory <remote-dir>
```

The script writes a `hardware-probe-<host>-<jobid>` directory in the submission
directory unless `HPC_PROBE_OUTPUT_DIR` is set.

For GPU programming limits that `nvidia-smi` does not report, such as CUDA L2
cache size, shared-memory limits, register limits, compute capability, and
launch dimensions, the package also includes a CUDA device-property example:
`hpc_tools/data/cuda-device-properties.slurm` plus the buildable source under
`hpc_tools/data/cuda/`. Use `hpc paths` to locate these packaged assets after
installation, or write/install the bundle directly:

```bash
hpc write-probe --kind cuda-device-properties cuda-device-properties/
hpc --profile example install-probe --kind cuda-device-properties --directory <remote-dir>
```

## Onboarding a New Slurm Cluster

When using `hpc-tools` on a new HPC system, first build a small local profile
and reference set. The goal is to collect enough site facts that later build,
filesystem, and Slurm workflows can make site-aware choices without embedding
site-specific assumptions in the generic skills.

Start with a minimal profile in the hpc-tools config file shown by `hpc paths`,
normally `$XDG_CONFIG_HOME/hpc-tools/config.toml` or
`~/.config/hpc-tools/config.toml`:

```toml
[profiles.example]
ssh_target = "example"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
```

If there is no SSH alias, use explicit `user` and `host` fields instead:

```toml
[profiles.example]
user = "myuser"
host = "login.example.edu"
ssh_options = ["-x"]
login_shell = ["bash", "-l", "-c"]
```

Then collect information in this order:

0. Verify local installation:

   ```bash
   command -v hpc
   hpc --help
   ```

   If `hpc` is not found, install the released CLI:

   ```bash
   pipx install hpc-tools
   pipx ensurepath
   hpc --help
   ```

   If you are testing from the `hpc-tools` repository root before release, use
   a local release-style install instead:

   ```bash
   pipx install .
   hpc --help
   ```

1. Verify access and Slurm commands:

   ```bash
   hpc --profile example --dry-run run 'hostname'
   hpc --profile example run 'hostname; whoami; pwd'
   hpc --profile example run 'command -v sbatch; command -v sinfo; command -v scontrol; command -v sacctmgr || true'
   ```

2. Discover Slurm partitions and controller limits:

   ```bash
   hpc --profile example run 'sinfo -a -o "%P|%a|%l|%D|%c|%m|%G|%f"'
   hpc --profile example run 'scontrol show partition'
   hpc --profile example run 'scontrol show config | grep -Ei "ClusterName|MaxArraySize|MaxJobCount|MaxSubmitJobs|MaxTasksPerNode|SchedulerParameters"'
   ```

   If the site uses Slurm federation or multiple clusters, repeat with
   `-M <cluster>`.

3. Discover account and QoS policy:

   ```bash
   hpc --profile example run 'sacctmgr -n -P show assoc where user=$USER format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES 2>/dev/null || true'
   hpc --profile example run 'sacctmgr -n -P show qos format=Name,MaxJobsPU,MaxSubmitJobsPU,MaxTRESPU,GrpJobs,GrpSubmitJobs,GrpTRES,MaxWall 2>/dev/null || true'
   ```

   If `sacctmgr` is restricted, use site documentation, example job scripts, and
   `sbatch --test-only` errors to identify required account or QoS directives.

4. Discover storage and quota commands:

   ```bash
   hpc --profile example run 'pwd; df -hT .; mount | sed -n "1,80p"'
   hpc --profile example run 'env | grep -Ei "HOME|DATA|SCRATCH|WORK|PROJECT|TMP|SLURM" | sort'
   hpc --profile example run 'command -v quota; command -v lfs; command -v beegfs-ctl; command -v mmlsquota; command -v module || true'
   ```

   Record home, project/data, shared scratch, and node-local scratch separately.
   Avoid assuming home storage is suitable for parallel I/O.

5. Discover representative compute hardware:

   Install the packaged probe script on the remote system, adding common
   site-required directives when needed, and submit one probe per representative
   node class or partition:

   ```bash
   hpc --profile example install-hardware-probe --directory <remote-dir> \
       --account <account> --cluster <cluster> --partition <partition> \
       --mail-notifications
   hpc --profile example submit --test-only hardware-probe.slurm --directory <remote-dir>
   hpc --profile example submit hardware-probe.slurm --directory <remote-dir>
   ```

Use the collected facts to create concise durable Markdown files under the
profile reference directory shown by `hpc paths`, normally
`$XDG_CONFIG_HOME/hpc-tools/profiles/<profile>/` or
`~/.config/hpc-tools/profiles/<profile>/`, then add their paths and source URLs
to the profile config. Those local references become the context that
`hpc hardware` and the Codex skills use for future work. The repository's
`examples/references/` files are templates and examples, not the long-term home
for user-generated cluster references.

The `hpc-cluster-onboarding` Codex skill can guide this process interactively:
ask the agent to onboard a new Slurm cluster for `hpc-tools`, provide the SSH
target or profile name, and let it step through access checks, Slurm discovery,
account/QoS inspection, storage discovery, and hardware probing.

## Codex Skills

The repository also includes reusable Codex skills under [skills](skills). They
generalize the original Genius-specific workflows so agents can work with any
configured `hpc-tools` profile:

- [skills/_shared/hpc-tools-remote-access.md](skills/_shared/hpc-tools-remote-access.md)
  contains the shared remote command/profile guidance used by the domain skills.
- [skills/hpc-cluster-onboarding](skills/hpc-cluster-onboarding) for guiding a
  first-time setup and information collection process for an arbitrary
  Slurm-based HPC system.
- [skills/hpc-cluster-discovery](skills/hpc-cluster-discovery) for discovering
  cluster hardware, scheduler, storage, and node-class facts from profile
  references, live commands, and hardware-probe output.
- [skills/hpc-filesystem-environment](skills/hpc-filesystem-environment) for
  storage, quota, ownership, module, and conda environment inspection.
- [skills/hpc-deploy-build](skills/hpc-deploy-build) for cloning, building, and
  verifying software on a remote HPC profile.
- [skills/hpc-slurm-jobs](skills/hpc-slurm-jobs) for queue inspection, Slurm job
  scripts, submission, accounting, and output follow-up.
- [skills/hpc-slurm-benchmark](skills/hpc-slurm-benchmark) for Slurm-backed
  benchmark runs, pilot-first sweeps, result collection, and local analysis.

Install them into a Codex skills directory by copying the skill directories and
the shared reference directory. Copying, rather than symlinking, lets the user
delete the `hpc-tools` checkout after installation:

```bash
mkdir -p ~/.codex/skills
cp -R skills/_shared ~/.codex/skills/_shared
cp -R skills/hpc-cluster-onboarding ~/.codex/skills/hpc-cluster-onboarding
cp -R skills/hpc-cluster-discovery ~/.codex/skills/hpc-cluster-discovery
cp -R skills/hpc-filesystem-environment ~/.codex/skills/hpc-filesystem-environment
cp -R skills/hpc-deploy-build ~/.codex/skills/hpc-deploy-build
cp -R skills/hpc-slurm-jobs ~/.codex/skills/hpc-slurm-jobs
cp -R skills/hpc-slurm-benchmark ~/.codex/skills/hpc-slurm-benchmark
```

Each skill assumes the `hpc` CLI is installed and the relevant profile is
configured. Optional commands such as `hpc quota` and `hpc queue` are used only
when the selected profile exposes them.
