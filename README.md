# hpc-tools

`hpc-tools` provides a small `hpc` command for common SSH and Slurm interactions
with remote HPC systems. Hosts are configured as named profiles, so the same
commands can target `genius`, another login node, or a local SSH alias.

This repository is also structured as a Codex plugin. The Codex plugin ships
skills for safe, profile-driven HPC work; it does not install the `hpc` CLI,
configure SSH, or authorize Slurm submissions.

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

## Codex Plugin

The Codex plugin metadata lives in
[.codex-plugin/plugin.json](.codex-plugin/plugin.json) and points Codex at the
skills under [skills](skills). Install or update the Codex plugin separately
from the Python package. The plugin makes the skills available to Codex; it does
not install the `hpc` command.

Clone the plugin into the standard local plugin directory:

```bash
mkdir -p ~/plugins
git clone https://github.com/gjbex/hpc-tools.git ~/plugins/hpc-tools
```

If `~/plugins/hpc-tools` already exists, inspect it before installing. A valid
checkout should contain `.git`, `.codex-plugin/plugin.json`, `skills/`, and
`hpc_tools/`:

```bash
find ~/plugins/hpc-tools -maxdepth 2 -type f -print
```

If it is already a Git checkout, update it instead of cloning:

```bash
git -C ~/plugins/hpc-tools pull --ff-only
```

If it is an old scaffold with only `.codex-plugin/plugin.json`, move it aside
before cloning the real repository:

```bash
mv ~/plugins/hpc-tools \
  ~/plugins/hpc-tools.scaffold-backup-$(date -u +%Y%m%dT%H%M%SZ)

git clone https://github.com/gjbex/hpc-tools.git ~/plugins/hpc-tools
```

Register the checkout in the default personal Codex marketplace, then install
the plugin from that marketplace. The registration command creates or updates
the `hpc-tools` entry in `~/.agents/plugins/marketplace.json`; it does not
modify the plugin checkout:

```bash
python3 ~/plugins/hpc-tools/tools/register_personal_marketplace.py \
  ~/plugins/hpc-tools

codex plugin add hpc-tools@personal
```

Verify the installed source contains the bundled skills:

```bash
codex plugin list
test -f ~/plugins/hpc-tools/skills/hpc-slurm-jobs/SKILL.md
```

Start a new Codex thread after installation so the newly installed skills are
available in the session.

After installing the Codex plugin, install the CLI with `pipx install hpc-tools`
if the `hpc` command is not already available.

Keep these surfaces separate:

- Codex plugin: cluster, Slurm, filesystem, package, benchmark, and container
  workflow skills for Codex.
- Python package: the `hpc` executable, packaged probe templates, and the
  `hpc_tools.plugins` CLI extension API.
- User state: profile configuration, reference sets, submission logs, and
  consolidated cluster notes under `$XDG_CONFIG_HOME/hpc-tools` or
  `~/.config/hpc-tools`.

See [ROUTING.md](ROUTING.md) for skill selection, safety rules, and the
difference between Codex plugin packaging and the `hpc_tools.plugins` Python
entry-point group.

## Related Plugins

`hpc-tools` is intentionally separate from
[`scientific-computing-skills`](https://github.com/gjbex/scientific-computing-skills).
Use this plugin for operational HPC work: SSH profiles, Slurm jobs, accounting,
site filesystems, modules, job arrays, probes, and cluster-specific workflows.
Use `scientific-computing-skills` for broader scientific software engineering:
testing, CI, profiling, benchmarking methodology, numerical review, packaging,
reproducibility, documentation, and release preparation.

The two plugins can complement each other, but neither depends on the other.
Keep `hpc-tools` separate because it guides actions that may touch real
clusters, charge accounts, or modify remote state.

Do not run `create_basic_plugin.py --force` against this repository. That helper
is for creating a new plugin scaffold, and can overwrite a real checkout with an
empty scaffold.

To update the plugin later, update the local checkout, refresh the plugin
version cachebuster, and reinstall from the personal marketplace:

```bash
git -C ~/plugins/hpc-tools pull --ff-only

python3 ~/plugins/hpc-tools/tools/register_personal_marketplace.py \
  ~/plugins/hpc-tools

python3 ~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  ~/plugins/hpc-tools

codex plugin add hpc-tools@personal
```

Start a new Codex thread after reinstalling.

## MCP Server

`hpc-tools` includes an experimental `hpc-mcp` console command that exposes a
guarded MCP interface for agents through the official FastMCP framework. This
is a structured interface over the same profile, reference, plugin,
Slurm-inspection, submission-log, probe, and container helpers used by the CLI.
The Codex plugin manifest points at `.mcp.json`, which starts the MCP server
with the `hpc-mcp` command. Installing the Codex plugin does not install that
command; install the Python package first.

Install the optional MCP dependency in a development checkout with:

```bash
uv pip install -e ".[mcp]"
```

Run the server with:

```bash
hpc-mcp
```

The MCP interface supports read-only context tools such as:

- `hpc_profiles_list`
- `hpc_paths`
- `hpc_profile_show`
- `hpc_hardware_context`
- `hpc_hardware_sources`
- `hpc_references_list`
- `hpc_references_show`
- `hpc_plugins_list`
- `hpc_submissions_list`
- `hpc_status`
- `hpc_jobs`
- `hpc_job`
- `hpc_slurm_limits`
- `hpc_module_spider`
- `hpc_storage_inspect`
- `hpc_site_env`

It also supports confirm-gated write and install tools:

- `hpc_references_create`
- `hpc_references_import`
- `hpc_references_attach`
- `hpc_submissions_mark_collected`
- `hpc_submissions_mark_analysed`
- `hpc_submissions_close`
- `hpc_write_probe`
- `hpc_install_probe`
- `hpc_write_container`
- `hpc_install_container`

Local writes and remote installs require `confirm=true`. Remote install tools
return command previews by default; they only execute when `confirm=true` and
`dry_run=false`.

Slurm submission is exposed only as an evidence-gated sequence:

1. `hpc_quote_job`
2. `hpc_validate_job`
3. `hpc_submit_job`

`hpc_submit_job` requires matching quote and validation evidence for the same
profile, account, jobscript, remote directory, and Slurm resource shape, plus
`confirm=true`. Stale or dry-run evidence is rejected.

It also exposes durable local context as MCP resources:

- `hpc://paths`
- `hpc://config`
- `hpc://profiles/{profile}`
- `hpc://profiles/{profile}/hardware`
- `hpc://profiles/{profile}/slurm`
- `hpc://profiles/{profile}/storage`
- `hpc://reference-sets/{name}`
- `hpc://submissions/active`
- `hpc://submissions/all`

Profile and reference resources resolve from the active hpc-tools config tree
and installed reference-set directory, not from repository examples.

## Plugins

`hpc-tools` now supports plugin commands. The core CLI keeps generic SSH,
reference, and Slurm functionality, while language- or workflow-specific
helpers can live in plugins.

The repository currently ships bundled `benchmark`, `python`, and `r` plugins, so after installation you
can use:

```bash
hpc plugins list
hpc plugins info benchmark
hpc plugins info python
hpc plugins info r
hpc benchmark summarize results/
hpc benchmark compare baseline.csv candidate.csv --candidate-threads 8
hpc python scan path/to/script-or-project
hpc python inspect-deps path/to/script-or-project
hpc --profile <profile> python check path/to/script-or-project --module Python/<version>
hpc --profile <profile> python plan-install path/to/script-or-project --module Python/<version> --venv <remote-venv> --partition <partition> --output install-python-packages.slurm
hpc --profile <profile> python submit-install install-python-packages.slurm --directory <remote-dir> --account <account>
hpc --profile <profile> python verify-install --job-output <remote-job-output> --package <import-name>
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
status_url = "https://status.vscentrum.be/tier2_leuven.html"
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
`storage_reference`, `storage_url`, and `status_url` are optional metadata
fields. They let users and Codex skills inspect site-specific hardware,
partitions, filesystems, Slurm policy, and active service notices without
hardcoding those details in the generic skills. Local reference files should be
concise Markdown summaries of the relevant web documentation.

`reference_set` is optional. When it is set, `hpc hardware` resolves hardware,
Slurm, storage, and status source metadata from the shared reference set under
`~/.config/hpc-tools/reference-sets/<name>/` before falling back to any
profile-local metadata. This is the preferred way to reuse one cluster-wide
reference bundle across multiple users.

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
status_url = "https://status.example.org/"
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
hpc doctor
hpc paths
hpc plugins list
hpc plugins info python
hpc plugins info r
hpc doctor
hpc site-env
hpc storage inspect .
hpc storage inspect $VSC_DATA/Projects/demo
hpc repo status --directory $VSC_DATA/Projects/demo
hpc python scan analysis.py
hpc python inspect-deps .
hpc --profile genius python check analysis.py --module SciPy-bundle/2025.07-gfbf-2025b --module matplotlib/3.10.5-gfbf-2025b
hpc --profile genius python plan-install analysis.py --module SciPy-bundle/2025.07-gfbf-2025b --module matplotlib/3.10.5-gfbf-2025b --venv /path/to/remote/project/.venv-icelake-scipy-mmh3 --partition batch_icelake --output install-python-packages.slurm
hpc --profile genius python submit-install install-python-packages.slurm --directory $VSC_DATA/Projects/demo --account <account>
hpc --profile genius python verify-install --job-output /path/to/job.out --package mmh3
hpc r scan Script/Main_casestudy1.R
hpc --profile genius r check Script/Main_casestudy1.R --module R/4.4.2-gfbf-2024a --cran-bundle R-bundle-CRAN/2024.11-foss-2024a --bioc-bundle R-bundle-Bioconductor/3.20-foss-2024a-R-4.4.2
hpc --profile genius r plan-install Script/Main_casestudy1.R --module R/4.4.2-gfbf-2024a --cran-bundle R-bundle-CRAN/2024.11-foss-2024a --bioc-bundle R-bundle-Bioconductor/3.20-foss-2024a-R-4.4.2 --partition batch_icelake --output install-r-packages.slurm
hpc --profile genius r submit-install install-r-packages.slurm --directory $VSC_DATA/Projects/demo/Script --account <account>
hpc --profile genius r verify-install --job-output /path/to/job.out --package PrevMap --package INLA --package dlnm
# use an Apptainer container when the stack is large or startup load matters more than another local install
hpc write-container --kind generic generic-container/
hpc install-container --kind generic --directory $VSC_DATA/Projects/demo/container
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
hpc status          # full status, quota, balance, and submissions report
hpc quota                  # if quota_command is configured
hpc projects
hpc clone https://github.com/org/repo.git --branch main
hpc clone https://github.com/org/repo.git --branch main --directory $VSC_SCRATCH/repos
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
hpc job 123456 --cluster wice
hpc slurm-limits --cluster wice --partition batch
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
hpc --profile genius --dry-run repo status --directory "$VSC_DATA/Projects/foo"
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
Detailed semantics for the `STATE` and `ACTION` columns, plus a state-transition
diagram, are documented in [docs/submissions.md](docs/submissions.md).

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
   hpc --profile example --dry-run doctor
   hpc --profile example doctor
   ```

2. Discover Slurm partitions and controller limits:

   ```bash
   hpc --profile example slurm-limits
   hpc --profile example slurm-limits --cluster <cluster> --partition <partition>
   ```

   If the site uses Slurm federation or multiple clusters, repeat with
   `-M <cluster>`.

3. Discover account and QoS policy:

   ```bash
   hpc --profile example slurm-limits
   ```

   If `sacctmgr` is restricted, use site documentation, example job scripts, and
   `sbatch --test-only` errors to identify required account or QoS directives.

4. Discover storage and quota commands:

   ```bash
   hpc --profile example storage inspect .
   hpc --profile example site-env
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

The Codex plugin exposes reusable skills under [skills](skills). They
generalize the original Genius-specific workflows so agents can work with any
configured `hpc-tools` profile:

- [skills/_shared/hpc-tools-remote-access.md](skills/_shared/hpc-tools-remote-access.md)
  contains the shared remote command/profile guidance used by the domain skills.
- [skills/_shared](skills/_shared) also contains conceptual HPC references for
  Slurm resource semantics, accounting safety, storage/I/O choices, and
  benchmark methodology. The top-level `hpc-*` skills stay action-oriented and
  link to these references when conceptual advice is needed.
- [skills/hpc-cluster-onboarding](skills/hpc-cluster-onboarding) for guiding a
  first-time setup and information collection process for an arbitrary
  Slurm-based HPC system.
- [skills/hpc-cluster-discovery](skills/hpc-cluster-discovery) for discovering
  cluster hardware, scheduler, storage, and node-class facts from profile
  references, live commands, and hardware-probe output.
- [skills/hpc-filesystem-environment](skills/hpc-filesystem-environment) for
  storage, quota, ownership, module, and conda environment inspection.
- [skills/hpc-python-packages](skills/hpc-python-packages) for checking Python
  import availability through site Python and bundle modules before planning a
  small virtualenv install for packages still missing.
- [skills/hpc-r-packages](skills/hpc-r-packages) for checking CRAN and
  Bioconductor dependency availability through site R and bundle modules before
  planning user package installs.
- [skills/hpc-deploy-build](skills/hpc-deploy-build) for cloning, building, and
  verifying software on a remote HPC profile.
- [skills/hpc-slurm-jobs](skills/hpc-slurm-jobs) for queue inspection, Slurm job
  scripts, submission, accounting, and output follow-up.
- [skills/hpc-slurm-job-arrays](skills/hpc-slurm-job-arrays) for parameter
  sweeps, many-input-file array workflows, `atools`-style task bookkeeping,
  reruns of failed array elements, and output aggregation.
- [skills/hpc-slurm-benchmark](skills/hpc-slurm-benchmark) for Slurm-backed
  benchmark runs, pilot-first sweeps, result collection, and local analysis.
- [skills/hpc-container-workflows](skills/hpc-container-workflows) for
  Apptainer definition-file workflows, especially HPCCM-generated recipes and
  container builds that should run through Slurm.

If a Codex plugin install path is not available, the skills can still be
installed manually by copying the skill directories and shared reference
directory. Copying, rather than symlinking, lets the user delete the
`hpc-tools` checkout after installation:

```bash
mkdir -p ~/.codex/skills
cp -R skills/_shared ~/.codex/skills/_shared
cp -R skills/hpc-cluster-onboarding ~/.codex/skills/hpc-cluster-onboarding
cp -R skills/hpc-cluster-discovery ~/.codex/skills/hpc-cluster-discovery
cp -R skills/hpc-filesystem-environment ~/.codex/skills/hpc-filesystem-environment
cp -R skills/hpc-python-packages ~/.codex/skills/hpc-python-packages
cp -R skills/hpc-r-packages ~/.codex/skills/hpc-r-packages
cp -R skills/hpc-deploy-build ~/.codex/skills/hpc-deploy-build
cp -R skills/hpc-slurm-jobs ~/.codex/skills/hpc-slurm-jobs
cp -R skills/hpc-slurm-job-arrays ~/.codex/skills/hpc-slurm-job-arrays
cp -R skills/hpc-slurm-benchmark ~/.codex/skills/hpc-slurm-benchmark
cp -R skills/hpc-container-workflows ~/.codex/skills/hpc-container-workflows
```

Each skill assumes the `hpc` CLI is installed and the relevant profile is
configured. Optional commands such as `hpc quota` and `hpc queue` are used only
when the selected profile exposes them.

## Validation

Before publishing plugin or skill changes, run the repo-local checks:

```bash
python3 tools/validate_plugin.py .
python3 tools/validate_skills.py .
python3 tools/check_repo_hygiene.py .
python3 -m unittest discover -s tests
```
