# WP9 bounded file operations

Status: complete on 2026-10-14.

WP9 exposes the descriptor-relative filesystem foundation from WP4 as focused
human and agent operations. It does not add arbitrary remote shell execution,
recursive transfer, recursive deletion, or implicit execution of uploaded
content.

## Public surface

| CLI | MCP | Authority |
| --- | --- | --- |
| `hpc files list` | `hpc_files_list` | C1, `remote-filesystem.list`, list root |
| `hpc files read` | `hpc_files_read` | C1, `remote-filesystem.read`, read root |
| `hpc files download` | `hpc_files_download` | C1, remote read and `local-state.write` |
| `hpc files upload` | `hpc_files_upload` | C1, `remote-workspace.write`, write root |
| `hpc files copy` | `hpc_files_copy` | C1, remote read plus workspace write and both roots |
| `hpc files mkdir` | `hpc_files_mkdir` | C1, `remote-workspace.write`, write root |
| `hpc files remove` | `hpc_files_remove` | C1, `remote-workspace.delete`, delete root |
| Existing `hpc clone` | `hpc_repo_clone` | C1, `remote-workspace.write`, write root |

MCP mutations default to `dry_run=true` and execute only when the caller also
sets `confirm=true`. Preview and confirmation never expand profile authority.
CLI mutations execute directly unless the global `--dry-run` option is used.
The MCP server registers only operations allowed by its immutable startup
policy snapshot.

## Bounds and publication

- Directory listing is non-recursive and accepts a caller-selected ceiling up
  to 1000 entries.
- Content reads accept a ceiling up to 1 MiB. UTF-8 and base64 representations
  are explicit.
- Upload, download, and copy are single-file operations with a ceiling up to
  4 MiB. Source and destination grants are checked independently before a
  remote copy.
- Local sources and destinations must be regular files. Direct symlink and
  special-file targets are rejected. Both local and remote destinations use a
  temporary regular file followed by atomic publication; replacement is
  explicit through `force`.
- Directory creation creates exactly one leaf below an existing parent.
  Removal accepts one regular file or empty directory, never follows a symlink,
  refuses configured roots, and is not recursive.
- Clone accepts network sources only, invokes a fixed quoted Git command,
  disables hooks and recursive submodules, and proves the destination absent
  through the bounded helper before execution.

The helper source is streamed from the installed Python package, so the target
host needs a suitable Python interpreter but neither an hpc-tools installation
nor this repository checkout.

## Acceptance evidence

Focused tests exercise binary upload, remote copy, download, list, read,
one-level mkdir/removal, preview behavior, overwrite conflicts, symlink denial,
non-empty and root deletion denial, local atomic replacement, and authorization
without a read root. Registry, CLI, and MCP snapshot tests cover every new
binding. Final repository-wide validation is recorded in the implementation
handoff for this work package.

The supported `.venv` suite passed 427 tests with one skip, including 61
focused file-operation, registry, discovery, snapshot, and clone tests. Plugin,
skill, compilation, and diff checks passed. The literal system-Python suite
remains unavailable because that interpreter lacks the declared `tomlkit`
dependency; repository hygiene remains blocked by pre-existing build, cache,
egg-info, and bytecode artifacts.
