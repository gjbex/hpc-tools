# Choose an interface

`hpc-tools` has three user-facing interfaces and one extension mechanism. They
share a project, but installing one does not install or authorize the others.

| Interface | Best suited to | Installed by |
| --- | --- | --- |
| `hpc` CLI | a person operating a workflow and reading shell output | the `hpc-tools` Python package |
| Codex plugin | Codex guiding a task with HPC-specific skills | the hpc-tools Codex plugin |
| `hpc-mcp` | an agent consuming structured tools and resources | the Python package with the `mcp` extra |
| Python CLI plugins | adding domain-specific `hpc` subcommands | packages registered under `hpc_tools.plugins` |

## Start with the CLI

The CLI is the primary human interface and the best bootstrap path. Use it
when:

- you want to see the exact terminal output;
- you are creating or debugging the first profile;
- no agent integration is installed;
- you want an operation to remain explicitly under shell control.

The CLI provides generic SSH and Slurm commands, packaged probes and container
templates, the local submission log, reference-set management, and bundled
workflow plugins.

Install it independently with:

```bash
pipx install hpc-tools
```

Then follow the [Quick start](getting-started.md).

## Add the Codex plugin for guided workflows

The Codex plugin packages skills for cluster onboarding, discovery,
filesystems, Python and R packages, remote builds, Slurm jobs, arrays,
benchmarks, and containers. A skill supplies task-specific instructions and
references; it does not bypass the CLI, SSH, scheduler, or the user's account
authority.

Use the plugin when the work benefits from interpretation and sequencing—for
example, diagnosing a failed job or planning a pilot-first benchmark—rather
than merely running one known command.

The official OpenAI plugin documentation describes plugins as bundles that can
contain skills and MCP servers. In Codex CLI, plugins are installed from a
configured marketplace and become available to a new session. See the
[official plugin documentation](https://learn.chatgpt.com/docs/plugins) for the
product-level model. The `hpc-tools` local-marketplace procedure is documented
in [Installation and maintenance](installation.md#install-the-codex-plugin).
See [Using hpc-tools with Codex](codex.md) for skill routing, example requests,
and action-review boundaries.

Installing this plugin does **not**:

- install the `hpc` or `hpc-mcp` executables;
- create an hpc-tools profile;
- configure SSH credentials;
- authorize a Slurm account or a real submission.

## Use MCP for structured agent integration

The experimental `hpc-mcp` server presents hpc-tools context as named tools and
resources. It is useful when an agent needs structured profile data, reference
content, submission records, or bounded inspection results rather than parsing
terminal text.

MCP write and remote-install tools require explicit confirmation. Slurm
submission uses a quote → validate → submit evidence chain, and the server
rejects failed, dry-run, tampered, or shape-mismatched evidence. These gates
reduce accidental actions, but they do not make a resource request authorized,
appropriate, or affordable. Evidence timestamps currently have no age-expiry
rule; see [MCP integration](mcp.md) for the exact limitations.

The Codex plugin's MCP configuration starts the `hpc-mcp` command. Therefore,
installing the plugin without installing the Python package and MCP extra can
leave the skills available while the MCP server cannot start.

## Do not confuse the two plugin systems

The term *plugin* has two meanings in this repository:

- the **Codex plugin** distributes skills and MCP configuration;
- the **Python entry-point plugins** add commands such as `hpc python`,
  `hpc r`, `hpc cxx`, and `hpc benchmark` to the CLI.

The bundled Python plugins are installed with the Python package. See
[CLI plugin system](plugins.md) only if you are developing or packaging a new
CLI extension.

## A practical default

For most users:

1. install and verify the CLI;
2. create and test one profile;
3. install the Codex plugin if guided workflows would help;
4. add MCP only if a structured agent interface is actually needed.

This order makes failures easier to diagnose. It establishes whether SSH,
configuration, and Slurm work before adding another integration layer.
