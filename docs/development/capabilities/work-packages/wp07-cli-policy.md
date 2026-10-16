# WP7 CLI policy and visibility

Status: implemented and accepted locally on 2026-10-14.

## Profile-aware discovery

CLI help now resolves an explicitly selected profile, or the default/sole
profile when a configuration is available, before presenting profile-aware
commands. With no configuration file, root help and genuinely standalone
local reads retain a deliberately small bootstrap surface. Explicit
`--profile`, `--config`, and `HPC_TOOLS_CONFIG` selections never fall back to
unconfigured execution.

The help parser evaluates every registered leaf against the selected profile's
level, scopes, site features, and existence of the necessary root-grant kind.
Denied leaves and empty command groups are hidden by default.
`--show-disallowed` retains them with safe denial annotations, while
`--capability LEVEL` narrows discovery to a lower ceiling. Both options are
display-only and are excluded from the authority decision used for execution.

## Complete execution grammar

Help/discovery uses a filtered parser copy. Ordinary invocation uses the full
registered grammar and then authorizes the parsed operation at dispatch and at
the existing handler boundary. A user can therefore invoke a hidden command
and receive its precise structured denial without the default help surface
advertising it. Unknown-choice parser messages are sanitized so they do not
print the unfiltered command list.

Site-conditional commands are now always registered in the internal grammar.
Their availability is represented by registry site features and filtered by
the same visibility evaluator, so `--show-disallowed` can explain a missing
site helper and direct invocation can fail through authorization. External CLI
plugins use the same metadata path after their WP6 contract is validated.

## Mixed modes and policy summary

Visibility handles argument-dependent `probe.write` and `job.submit` modes.
A C2 profile with `job.validate` sees the explicit
`submit JOBSCRIPT --test-only` form while actual submission remains hidden and
denied. Standard-output probe generation remains available where a local file
write is not. Parsed arguments are still re-resolved at invocation.

The new `hpc capabilities` command provides human and native JSON summaries of
the selected profile, policy source, configured execution grants, and any
narrower display grants. Its output labels the display restriction as
display-only to avoid implying that it changes execution permission. JSON
policy denials now contain `code = "capability.denied"`, operation, profile,
and structured denial details.

## Verification boundary

Focused tests cover filtered root and nested-plugin help, the expanded display,
explicit and default profile resolution, standalone help, mixed-mode
submission, policy summaries, sanitized parser errors, structured JSON denial,
and proof that a display ceiling does not reduce execution authority.

The supported `.venv` suite ran 417 tests: all passed, with one skip. Plugin and
skill validation and the required compilation check passed. Repository hygiene
still reports the checkout's existing `.ruff_cache`, build output, egg-info,
and bytecode caches; they were left untouched. The literal system-`python3`
suite remains unusable because that interpreter lacks `tomlkit`; 143 tests ran
and 27 test modules failed to import. No live cluster, SSH connection, scheduler
action, or user configuration/state was used.

WP8 must still bind MCP startup to one profile snapshot and filter tool and
resource discovery. CLI filtering is a discoverability control backed by
authorization, not an operating-system sandbox and not a substitute for the
remote filesystem and Slurm safety boundaries.
