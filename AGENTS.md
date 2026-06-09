# AGENTS.md

## Scope

This repository contains the `hpc-tools` Python CLI, example Slurm probe
scripts, example reference files, and Codex skills for working with remote
Slurm-based HPC systems.

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
- Install Codex skills by copying skill directories into `~/.codex/skills`, not
  by symlinking to this checkout.
- Use `hpc write-hardware-probe` or `hpc install-hardware-probe` for hardware
  probe scripts after installation; do not require the repository checkout for
  onboarding a new cluster.
- Use `hpc paths` to show config, durable reference, copied skill, packaged
  probe-template, and uninstall cleanup locations.

## Skill Routing

- Use `hpc-cluster-onboarding` for first-time setup of a new Slurm cluster.
- Use `hpc-cluster-discovery` for partition limits, QoS/account limits, array
  limits, and hardware probe interpretation.
- Use `hpc-filesystem-environment` for storage, quotas, modules, and conda.
- Use `hpc-r-packages` for checking whether an R script's CRAN or
  Bioconductor dependencies are already satisfied by site R modules or bundle
  modules, and for listing only the packages that still need installation.
- Use `hpc-slurm-jobs` for job scripts, submission, queue state, and accounting.
- Use `hpc-slurm-benchmark` for remote Slurm benchmarks, scaling runs,
  pilot-first benchmark sweeps, artifact collection, and local analysis.
- Use `hpc-deploy-build` for remote clone/build/test workflows.

## Validation

After changing skills, README onboarding instructions, examples, or tests, run:

```bash
python3 -m unittest discover -s tests
```
