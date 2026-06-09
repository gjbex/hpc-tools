---
name: hpc-r-packages
description: Verify whether an R script can use preinstalled CRAN or Bioconductor packages on a configured HPC profile, and identify any additional R packages the user still needs to install.
---

# HPC R Packages

## Remote Access

Use the installed `hpc` CLI for remote commands:

```bash
hpc --profile <profile> run '<command>'
```

For profile selection, optional helpers, login-gate handling, `--dry-run`, and
remote command patterns, read
[`../_shared/hpc-tools-remote-access.md`](../_shared/hpc-tools-remote-access.md).

## Goal

Before the user submits an R job or even writes a Slurm script, determine
whether the script's R package dependencies are already available through the
site module system. On some systems, common CRAN and Bioconductor packages are
already bundled in modules such as `R-bundle-CRAN` and
`R-bundle-Bioconductor`, so the user may not need a personal package install at
all.

The deliverable is a concrete package status summary:

- packages satisfied by the selected R and bundle modules;
- packages still missing after the best available bundle combination is loaded;
- any ambiguous package names or dynamic dependency logic that need manual
  review.

## Discovery Order

Start by identifying dependencies locally from the script or project files. Use
fast text searches first:

```bash
rg -n 'library\\(|require\\(|requireNamespace\\(' <script-or-project-dir>
rg -n 'BiocManager|renv|pak::pkg_install|install.packages' <script-or-project-dir>
```

If the project contains `renv.lock`, `DESCRIPTION`, `NAMESPACE`, or a package
list file, use those as stronger dependency sources than ad hoc `library()`
calls. Call out any conditional or dynamically constructed package loads, since
simple static scanning can miss them.

## Check Remote R and Bundle Modules

Inspect module availability before assuming the user must install anything:

```bash
hpc --profile <profile> module-spider R
hpc --profile <profile> module-spider R-bundle-CRAN
hpc --profile <profile> module-spider R-bundle-Bioconductor
```

Choose an R module and, when available, the matching CRAN and Bioconductor
bundle versions. Prefer bundle modules over personal installs for common
packages because they are already compiled for the site toolchain.

Verify the actual runtime environment with the same module loads that the user
would use in a job:

```bash
hpc --profile <profile> run 'module load <R-module> <cran-bundle> <bioc-bundle> && R --version'
hpc --profile <profile> run 'module load <R-module> <cran-bundle> <bioc-bundle> && Rscript -e "sessionInfo()"'
```

## Verify Package Availability

For the candidate package set, test whether each package is visible to R after
loading the chosen modules. Prefer `requireNamespace()` checks over trying to
attach every package:

```bash
hpc --profile <profile> run 'module load <R-module> <cran-bundle> <bioc-bundle> && Rscript -e "packages <- c(\"dplyr\", \"DESeq2\"); missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]; if (length(missing)) { writeLines(missing); quit(status = 1) }"'
```

If a package is missing, do not immediately recommend installation. First check
whether a different bundle version, a different R version, or an additional
bundle module would satisfy it. Only after that should the package be listed as
an extra user install requirement.

## Output

Summarize the result in three groups:

- available through the selected R environment;
- missing and likely requiring user installation;
- uncertain because the dependency is conditional, dynamically named, or not
  directly importable from the inspected script.

When packages are missing, list only the missing package names unless the user
asks for installation commands. If the user does ask for installation guidance,
separate CRAN-style installs from Bioconductor-style installs and keep the
commands consistent with the selected R module version.

## Limits

Do not claim a package is unavailable based only on static code inspection or
on `module spider` output. The decisive check is whether `Rscript` with the
chosen module loads can resolve `requireNamespace("<pkg>", quietly = TRUE)`.

Do not assume that because one bundle module exists, it contains every common R
package. The bundles reduce installation work, but verification must still be
package-specific.
