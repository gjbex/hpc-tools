# AGENTS.md

## Scope

This repository contains the `hpc-tools` Python CLI, example Slurm probe
scripts, example reference files, and Codex skills for working with remote
Slurm-based HPC systems.

The repository is also a Codex plugin. `.codex-plugin/plugin.json` packages the
skills for Codex, while `setup.cfg` packages the Python CLI. Keep those
distribution surfaces separate.

This plugin is related to, but separate from, `scientific-computing-skills`.
Use `hpc-tools` for operational HPC workflows and cluster safety; refer to
`scientific-computing-skills` for general scientific software engineering such
as testing, CI, profiling, numerical review, packaging, reproducibility, and
release preparation.

## Repository Rules

- Treat `examples/` as templates and sample data.
- Do not store durable user-generated cluster references in this repository.
- Store user profile references under `~/.config/hpc-tools/profiles/<profile>/`.
- Store shared cluster reference sets under
  `~/.config/hpc-tools/reference-sets/<name>/`.
- Install the released CLI with pipx for normal use:
  `pipx install hpc-tools`
- Use `pipx install .` only for release-style testing from this checkout.
- Use editable installs only for development:
  `python3 -m pip install --user -e .`
- Register CLI extensions through the `hpc_tools.plugins` entry-point group
  instead of hardcoding every workflow into the core CLI.
- Treat the Codex plugin as a skills distribution layer. Installing the Codex
  plugin does not install the `hpc` CLI, configure SSH, or authorize Slurm job
  submission.
- Do not confuse the Codex plugin with the `hpc_tools.plugins` Python
  entry-point group. Document and validate both surfaces when a change affects
  both.
- Install Codex skills by copying skill directories into `~/.codex/skills`, not
  by symlinking to this checkout.
- Use `hpc write-hardware-probe` or `hpc install-hardware-probe` for hardware
  probe scripts after installation; do not require the repository checkout for
  onboarding a new cluster.
- Use `hpc paths` to show config, durable reference, copied skill, packaged
  probe-template, and uninstall cleanup locations.

## Skill Routing

- Treat `skills/_shared/` as the conceptual HPC guidance layer. Keep the
  top-level `hpc-*` skills action-oriented around `hpc-tools` commands, and
  link to shared references for Slurm concepts, accounting safety, storage/I/O,
  and benchmark methodology instead of duplicating broad advice.
- Use `hpc-cluster-onboarding` for first-time setup of a new Slurm cluster.
- Use `hpc-cluster-discovery` for partition limits, QoS/account limits, array
  limits, and hardware probe interpretation.
- Use `hpc-filesystem-environment` for storage, quotas, modules, and conda.
- Use `hpc-python-packages` for checking whether a Python script's imports are
  already satisfied by site Python or bundle modules, and for planning a small
  virtualenv install only for packages still missing. When available, prefer
  the bundled `hpc python ...` plugin commands for reusable local dependency
  scanning and venv install-job generation.
- Use `hpc-r-packages` for checking whether an R script's CRAN or
  Bioconductor dependencies are already satisfied by site R modules or bundle
  modules, and for listing only the packages that still need installation. When
  available, prefer the bundled `hpc r ...` plugin commands for reusable local
  dependency scanning.
- Use `hpc-slurm-jobs` for job scripts, submission, queue state, and accounting.
- Use `hpc-slurm-job-arrays` for parameter sweeps, many-input-file runs,
  `atools` workflows, resumable array bookkeeping, and aggregating per-task
  output.
- Use `hpc-slurm-benchmark` for remote Slurm benchmarks, scaling runs,
  pilot-first benchmark sweeps, artifact collection, and local analysis.
- Use `hpc-deploy-build` for remote clone/build/test workflows.
- Use `hpc-container-workflows` for Apptainer definition-file workflows,
  especially HPCCM-generated recipes that must be regenerated before each
  build, and for deciding when to build containers in a Slurm job.

## Validation

After changing skills, README onboarding instructions, examples, or tests, run:

```bash
python3 tools/validate_plugin.py .
python3 tools/validate_skills.py .
python3 tools/check_repo_hygiene.py .
python3 -m unittest discover -s tests
```
