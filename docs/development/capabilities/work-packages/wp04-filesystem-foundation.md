# WP4 bounded filesystem foundation

Status: implemented on 2026-10-13. WP4 supplies reusable filesystem primitives.
WP5 integrates the existing built-in CLI and MCP operations; WP6 subsequently
integrates Python/R install staging and verification.

## Protocol and packaging

`hpc_tools.filesystem.FilesystemService` sends a versioned JSON request through
the selected executor. The request and the packaged helper source share one
length-framed binary stdin stream. The target invokes a configured executable
name (currently `python3` by default), so it needs neither the repository nor a
remote hpc-tools installation.

The helper at `hpc_tools/data/filesystem_helper.py` uses only the Python
standard library. Missing helper data, interpreter, descriptor primitives,
transport, protocol data, or environment variables returns a structured
failure. There is no fallback to an unrestricted shell filesystem command.

The same request/result types and helper run through `LocalExecutor` and
`SshExecutor`. Binary file content is base64-framed inside the helper protocol
and returned as exact bytes. `read_text` decodes UTF-8 strictly by default and
reports encoding errors explicitly; callers may deliberately select another
codec or error policy.

## Root and traversal boundary

Requests carry one or more already-authorized root declarations. Absolute,
`~`, `$NAME`, and `${NAME}` forms are expanded on the selected executor.
Relative paths require a unique or explicitly selected root. Empty segments,
`.`/`..`, trailing separators, globs, command substitution, extra expansion,
sibling-prefix paths, and the filesystem root are rejected.

The helper resolves the declared root on the target and opens it as a directory
descriptor. Every component below it is opened relative to the preceding
descriptor with `O_NOFOLLOW`. Reads require a regular file. Writes validate an
existing parent and stage data into a private same-directory temporary file.
Directory listing reports regular files, directories, links, and special
entries without following them. Links and special files are not readable,
writable, or removable through these primitives.

This is the filesystem implementation boundary, not general process
confinement. Arbitrary site commands, package initialization, external
executables, and submitted jobs can access anything permitted by their own
credentials and runtime environment.

## Bounds and publication

Every request carries positive finite limits for returned bytes, directory
entries, uploaded bytes, and elapsed time. Reads and listings return explicit
`truncated` state. Oversized writes and helper responses fail. Operations are
non-recursive.

New files are published without replacement by linking a fully written and
synced same-directory temporary file. Explicit overwrite uses atomic replace.
An error or interruption before publication removes the temporary file when
the helper remains alive and never exposes partial content at the destination;
a killed helper may leave only a private temporary file. The bounded cleanup
primitive removes only regular files with the helper's temporary-name pattern.

Directory creation requires an existing parent. Removal handles one regular
file or empty directory, rejects roots, links, special files, and non-empty
directories, and never recurses.

## Verification

Real temporary-filesystem tests cover binary and text reads, listings,
absolute/relative/home/environment paths, sibling-prefix and traversal escapes,
symlinks, a link swap after parent-descriptor opening, FIFOs, missing parents,
read/list/upload limits, overwrite conflicts, atomic replacement, simulated
publication interruption, cleanup, root deletion, unavailable helper/runtime
primitives, timeout, malformed/oversized protocol responses, and identical
local/loopback behavior. A mocked SSH execution verifies that the same framed
payload is sent through the SSH executor. A local wheel build verifies helper
inclusion. No live cluster is used.
