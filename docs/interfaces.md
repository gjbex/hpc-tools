# CLI, Codex, and MCP

`hpc-tools` has three related interfaces. Installing one does not implicitly
install, configure, or authorize the others.

| Interface | Intended use | Installed by |
| --- | --- | --- |
| `hpc` CLI | Human-operated shell workflows and readable command output | The `hpc-tools` Python package |
| Codex plugin | Task-oriented skills that guide Codex through cluster workflows | The hpc-tools Codex plugin |
| `hpc-mcp` | Structured tools and resources for agent integrations | The Python package with the `mcp` extra |

## Command-line interface

Use the CLI when a person is actively operating the workflow, shell output is
the desired artifact, or the local installation is still being bootstrapped.
The CLI owns the generic SSH and Slurm commands, packaged templates, local
submission log, and the `hpc_tools.plugins` extension mechanism.

Install it independently with:

```bash
pipx install hpc-tools
```

## Codex plugin

The Codex plugin distributes cluster-oriented skills for onboarding,
discovery, filesystems, packages, builds, Slurm jobs, arrays, benchmarks, and
containers. Those skills can use an installed CLI and configured profiles, but
the plugin does not install the CLI or configure SSH.

Starting a new Codex task is normally required after installing or updating the
plugin so the available skills are refreshed.

## MCP interface

The experimental `hpc-mcp` server exposes structured profile context,
references, submission records, Slurm inspection tools, and confirm-gated
write or install operations. Install the optional dependency separately:

```bash
uv pip install "hpc-tools[mcp]"
hpc-mcp
```

Agent-driven Slurm submission is restricted to an evidence chain that quotes
the workload, validates the same workload, and then submits it with explicit
confirmation. Stale, dry-run, or mismatched evidence is rejected.

## Two meanings of plugin

The repository contains two unrelated plugin mechanisms:

- the **Codex plugin** distributes skills and MCP configuration;
- the **Python entry-point plugins** add workflow-specific subcommands to the
  `hpc` CLI.

See [CLI plugin system](plugins.md) only when developing or packaging a CLI
extension.
