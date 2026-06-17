# Routing

Use these routing notes when this repository is installed as a Codex plugin.
The Codex plugin ships skills; the Python package still ships the `hpc`
executable through `pipx install hpc-tools`.

## Boundary

- Codex plugin: skill guidance for using and extending `hpc-tools`.
- Python package: the `hpc` CLI, packaged Slurm templates, and the
  `hpc_tools.plugins` command-extension API.
- User state: profiles, reference sets, submission logs, and consolidated
  cluster notes under `~/.config/hpc-tools`.
- Remote state: cluster checkouts, job scripts, raw probe output, and benchmark
  artifacts on the target system until compact artifacts are intentionally
  copied back for local analysis.

Do not treat installing the Codex plugin as installing the CLI, configuring SSH,
or authorizing Slurm submissions.

## Skill Selection

- `hpc-cluster-onboarding`: first-time setup for a Slurm cluster profile,
  profile references, SSH/login checks, and installed-tool orientation.
- `hpc-cluster-discovery`: hardware, scheduler, partition, storage, and
  node-class discovery through configured profiles and durable references.
- `hpc-filesystem-environment`: home/data/scratch/project storage, quotas,
  ownership, modules, conda environments, and filesystem placement.
- `hpc-slurm-jobs`: job scripts, quotes, validation, submission, queue state,
  accounting, and single-job follow-up.
- `hpc-slurm-job-arrays`: parameter sweeps, many-input-file runs, `atools`
  workflows, array bookkeeping, reruns, and result aggregation.
- `hpc-slurm-benchmark`: local-versus-remote benchmark planning, pilot-first
  Slurm benchmark jobs, scaling sweeps, artifact collection, and local analysis.
- `hpc-deploy-build`: clone, update, build, and verify software on an HPC login
  node through `hpc-tools`.
- `hpc-python-packages`: Python import checks, module-stack checks, and small
  virtualenv install plans for missing packages.
- `hpc-r-packages`: R package checks, CRAN/Bioconductor bundle checks, and
  runtime module guidance for non-R system dependencies.
- `hpc-container-workflows`: Apptainer and HPCCM definition-file workflows,
  container build jobs, and install/refresh paths.

Use `skills/_shared/` only as supporting reference material. Top-level skills
should stay action-oriented and should link to shared files instead of copying
large conceptual sections.

## Safety Model

- Quote before submitting Slurm jobs; re-quote when job count, size, walltime,
  reservation, or resource shape changes.
- Ask which account to charge when multiple accounts are possible.
- Use a pilot-first workflow before larger sweeps or broad job arrays.
- Prefer `hpc submit --validate-first` for real submissions.
- Avoid blind top-level scans on shared filesystems such as home, data, scratch,
  project, or site-specific equivalents; ask for a narrower path, job ID,
  filename pattern, or run directory first.
- Keep raw probe data and large outputs out of `~/.config`; store only
  consolidated Markdown references and compact local analysis artifacts there.
- Prefer local analysis after transferring compact benchmark or log artifacts
  instead of repeated remote shell analysis.

## Plugin Naming

This repository uses two plugin concepts:

- A Codex plugin, described by `.codex-plugin/plugin.json`, that makes this
  skill bundle installable in Codex.
- The `hpc_tools.plugins` Python entry-point group, documented in
  `docs/plugins.md`, that adds workflow-specific `hpc` CLI subcommands.

Keep these surfaces documented separately.
