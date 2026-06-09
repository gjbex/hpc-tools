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
- the architecture-specific user library location that should be used if local
  package installation is still required;
- any ambiguous package names or dynamic dependency logic that need manual
  review.

## Discovery Order

Start by identifying dependencies locally from the script or project files. Use
the bundled `hpc r scan` plugin command when it is available:

```bash
hpc r scan <script-or-project-dir>
```

For profile-aware workflows, prefer the plugin commands when they cover the
task:

```bash
hpc --profile <profile> r check <script-or-project-dir> --module <R-module>
hpc --profile <profile> r plan-install <script-or-project-dir> --module <R-module> --partition <partition> --output install-r-packages.slurm
hpc --profile <profile> r submit-install install-r-packages.slurm --directory <remote-dir> --account <account>
hpc --profile <profile> r verify-install --job-output <remote-job-output> --package <pkg>
```

If the plugin is unavailable or the scan needs manual confirmation, fall back to
fast text searches:

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

When the site publishes architecture-aware guidance for local R libraries, use
it. On VSC systems, user-installed packages should be segregated by OS version,
CPU microarchitecture, and R version:

```bash
${VSC_DATA}/Rlibs/${VSC_OS_LOCAL}/${VSC_ARCH_LOCAL}/R-${EBVERSIONR}
```

That matters because many R package installs pull in compiled dependencies, and
those extensions are often built with host-specific optimization flags. A
package library built on one CPU class may be suboptimal or unusable on
another. Therefore:

- report package availability under the exact module stack the user intends to
  run;
- when installation is needed, recommend an architecture-aware user library
  path rather than a single shared per-version directory;
- tell the user to install from an interactive session on the same node class
  they expect to use for jobs when compiled dependencies are involved.

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

When you move from verification to installation guidance, also inspect whether
the package or its hard dependencies require compilation. For CRAN packages,
`NeedsCompilation` is a useful first signal, but do not stop there; a pure-R
top-level package can still depend on compiled packages underneath. If the
site-specific R library layout depends on architecture, installation advice
must follow that layout.

## Output

Summarize the result in three groups:

- available through the selected R environment;
- missing and likely requiring user installation;
- uncertain because the dependency is conditional, dynamically named, or not
  directly importable from the inspected script.

When local installation is required, also report:

- the exact R module and bundle modules used for verification;
- the recommended user library root for the target site, if known;
- whether the installation should be done on a compute node of the intended CPU
  class because compiled dependencies are likely.

## Compute-Node Install Workflow

When package installation should be architecture-specific, prefer a short Slurm
install job on the target partition over a login-node install. This is the
recommended workflow on sites such as VSC when the package stack may compile
native extensions with host-specific optimization flags.

Use a pilot-first process:

1. write a small install job script for the intended partition and CPU class;
2. load the exact `R`, `R-bundle-CRAN`, and `R-bundle-Bioconductor` modules
   chosen during verification;
3. set `R_LIBS_USER` to the architecture-aware library root;
4. install only the packages still missing after bundle checks;
5. end the job with an explicit `requireNamespace()` verification block;
6. quote the pilot job when the site uses credits;
7. submit with validation first;
8. after completion, inspect the job output and confirm that the packages
   resolve from the intended library path.

A good install script should:

- fail fast if it lands on the wrong architecture, for example by checking
  `VSC_ARCH_LOCAL`;
- use temporary build space such as `${VSC_SCRATCH_NODE}`, `${TMPDIR}`, or
  `/tmp` for downloaded tarballs and build artifacts;
- print the final `.libPaths()` and `sessionInfo()` so the completed job log
  records exactly which library tree and module stack were used;
- verify the target package set explicitly, for example `PrevMap`, `INLA`, and
  `dlnm`, rather than assuming a successful `install.packages()` call is enough.

Use `hpc submit --validate-first` for the pilot install job so `sbatch
--test-only` runs before the real submission. After the job finishes, prefer
verification in this order:

- the package status lines printed by the job's final `requireNamespace()`
  block;
- the architecture-qualified `.libPaths()` recorded in the job output;
- optional package-directory existence checks in the user library root.

If the package source is not available from the current CRAN index, do not stop
at “package is unavailable.” Check whether the required version is archive-only
and install from the archived tarball explicitly. This commonly applies to
older research code that expects pinned package versions.

When packages are missing, list only the missing package names unless the user
asks for installation commands. If the user does ask for installation guidance,
separate CRAN-style installs from Bioconductor-style installs and keep the
commands consistent with the selected R module version and library path
convention.

## Limits

Do not claim a package is unavailable based only on static code inspection or
on `module spider` output. The decisive check is whether `Rscript` with the
chosen module loads can resolve `requireNamespace("<pkg>", quietly = TRUE)`.

Do not assume that because one bundle module exists, it contains every common R
package. The bundles reduce installation work, but verification must still be
package-specific.

Do not suggest a generic `R_LIBS_USER` path on sites that document
architecture-aware library layouts. Prefer the site guidance when it is known.
