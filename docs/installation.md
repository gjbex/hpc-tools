# Installation and maintenance

`hpc-tools` is distributed through separate surfaces. Install only the parts
needed for the intended workflow.

| Component | Provides | Does not provide |
| --- | --- | --- |
| Python package | `hpc`, packaged templates, bundled CLI plugins, and `hpc-mcp` entry point | Codex skills or SSH configuration |
| Codex plugin | HPC skills and MCP startup configuration | the Python package, profiles, or submission authority |
| MCP extra | the FastMCP runtime required by `hpc-mcp` | a configured MCP client or permission to act remotely |
| Documentation dependencies | local MkDocs preview and strict documentation builds | any runtime HPC functionality |

## Install the released CLI

The supported normal installation uses `pipx`, which places the application in
an isolated Python environment while exposing its commands on the user's
`PATH`.

Requirements:

- Python 3.10 or newer;
- `pipx`;
- an SSH client for remote commands.

Install and verify:

```bash
pipx install hpc-tools
pipx ensurepath
hpc --help
hpc paths
```

Start a new shell if `pipx ensurepath` changed the shell configuration. Use
`command -v hpc` and `pipx list` when diagnosing which installation supplies
the executable.

The CLI installation does not create `config.toml`. Continue with the
[Quick start](getting-started.md) to create a profile.

## Test a local checkout as a release

From the repository root, use pipx when testing how the checkout behaves as an
installed application:

```bash
pipx install .
```

This is a release-style test: pipx installs a snapshot into its managed
environment. Subsequent source edits are not automatically reflected there.

Do not use `pipx install .` as an editable development environment. During
development, follow the repository convention:

```bash
python3 -m pip install --user -e .
```

An editable installation and a pipx installation can both place an `hpc`
executable on the `PATH`. Check `command -v hpc` before assuming which source
is running.

## Install the MCP extra

For a fresh released installation that should include the experimental MCP
server, install the package with its extra:

```bash
pipx install 'hpc-tools[mcp]'
hpc-mcp
```

The package declares the MCP dependency separately so ordinary CLI users do not
need the agent-server stack.

From a development checkout, install the project and extra into the active
environment:

```bash
uv pip install -e '.[mcp]'
hpc-mcp
```

The `hpc-mcp` command starts a server; it is not an interactive CLI. Normally an
MCP client, such as the Codex plugin configuration, starts and communicates
with it.

## Install the Codex plugin

The following is the repository's local-checkout installation workflow. It
registers hpc-tools in a personal marketplace and installs it from that
marketplace. The official OpenAI documentation describes the general plugin
model and Codex marketplace behavior; see
[Plugins](https://learn.chatgpt.com/docs/plugins).

Clone into the standard local plugin directory:

```bash
mkdir -p ~/plugins
git clone https://github.com/gjbex/hpc-tools.git ~/plugins/hpc-tools
```

If that path already exists, inspect it. A valid checkout contains `.git`,
`.codex-plugin/plugin.json`, `skills/`, and `hpc_tools/`. Update an existing Git
checkout instead of cloning over it:

```bash
git -C ~/plugins/hpc-tools pull --ff-only
```

Register the checkout in the personal marketplace and install it:

```bash
python3 ~/plugins/hpc-tools/tools/register_personal_marketplace.py \
  ~/plugins/hpc-tools

codex plugin add hpc-tools@personal
codex plugin list
```

Start a new Codex task after installation. Codex loads the plugin's skills and
tools into new sessions.

The registration helper updates
`~/.agents/plugins/marketplace.json`. It does not modify the hpc-tools checkout
or install the Python package. Install the CLI separately if `hpc` is not
already available. Install the MCP extra if the plugin's `hpc-mcp` server
should start successfully.

Do not run a plugin-scaffolding command with a force or overwrite option
against the hpc-tools checkout. Scaffolding is for a new plugin and can replace
the real manifest or skills with an empty structure.

## Verify the installed surfaces

Use checks that correspond to the component:

```bash
# Python package and CLI
command -v hpc
hpc --help
hpc paths
hpc plugins list

# Optional MCP command
command -v hpc-mcp

# Codex plugin
codex plugin list
test -f ~/plugins/hpc-tools/skills/hpc-slurm-jobs/SKILL.md
```

These checks establish installation, not remote access. Use
`hpc --profile <profile> --dry-run doctor` and then
`hpc --profile <profile> doctor` to verify the cluster path.

## Upgrade the CLI

Upgrade a released pipx installation with:

```bash
pipx upgrade hpc-tools
hpc --help
hpc paths
```

Review release notes before upgrading when a workflow depends on command output
or an on-disk format. Profiles, references, and submission logs are durable
user state and are not part of the pipx environment, but compatibility still
matters when their schemas evolve.

For a local release-style installation, update the checkout and reinstall the
local project through pipx according to the intended test. Do not assume that a
plain source edit changes the existing pipx snapshot.

## Update the Codex plugin

The local-checkout plugin has its own update path:

```bash
git -C ~/plugins/hpc-tools pull --ff-only

python3 ~/plugins/hpc-tools/tools/register_personal_marketplace.py \
  ~/plugins/hpc-tools

python3 ~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py \
  ~/plugins/hpc-tools

codex plugin add hpc-tools@personal
```

Start a new Codex task after reinstalling. Updating the plugin checkout does not
upgrade the separately installed Python package; update both when a change
spans skills and CLI commands.

## Uninstall the CLI

Before uninstalling, inspect all relevant locations:

```bash
hpc paths
pipx uninstall hpc-tools
```

Removing the pipx environment removes the `hpc` and `hpc-mcp` executables it
provided. It does not remove user-managed configuration, profile references,
reference sets, submission logs, copied skills, remote job scripts, probe
results, or benchmark artifacts.

The durable local state normally remains under:

```text
$XDG_CONFIG_HOME/hpc-tools/
```

or, when `XDG_CONFIG_HOME` is unset:

```text
~/.config/hpc-tools/
```

Inspect that state before deciding whether it should be retained, archived, or
removed. In particular, `submissions.jsonl` may be the only local index of
unfinished remote work.

## Remove the Codex plugin

Remove the installed plugin entry and cache with:

```bash
codex plugin remove hpc-tools@personal
```

This does not delete the source checkout in `~/plugins/hpc-tools`, remove the
personal marketplace entry, uninstall the Python package, or delete hpc-tools
user state. Those are independent decisions.

## Troubleshoot installation

### `hpc` is not found

Run:

```bash
pipx list
pipx ensurepath
command -v hpc
```

Then start a new shell. If multiple installations exist, inspect the resolved
path before reinstalling anything.

### The CLI reports that configuration is missing

Installation succeeded; most remote commands require a profile. `hpc paths`
and `hpc --help` work without one. Continue with the [Quick start](getting-started.md).

### The Codex plugin is installed but `hpc` is missing

This is expected when only the plugin was installed. Install the Python package
with pipx.

### The Codex plugin is visible but its MCP server does not start

The plugin configuration invokes `hpc-mcp`. Verify that the command is on the
environment inherited by Codex and that the MCP extra is installed. The skills
can still be present even when the optional server cannot start.

### A command documented for another profile is absent

Some commands are capability-driven. For example, site-specific quota, queue,
balance, statement, quote, hardware, or status commands depend on corresponding
profile fields. This is a configuration issue, not necessarily an installation
failure.
