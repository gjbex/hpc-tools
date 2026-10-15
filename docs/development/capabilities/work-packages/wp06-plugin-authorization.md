# WP6 Python CLI plugin authorization

Status: implemented and accepted locally on 2026-10-14.

## Versioned plugin contract

The `hpc_tools.plugins` entry-point protocol now requires
`contract_version = 1` and a non-empty tuple of `OperationDescriptor` values.
Each registered leaf command must expose an `operation_id`, and its full CLI
binding must exactly match the declared metadata. Bundled benchmark, C/C++,
Python, and R plugins declare every leaf operation through the canonical shared
registry.

Missing or unsupported contract versions, core operation-ID collisions,
unsupported custom resolvers, and undeclared or mismatched command bindings
reject the plugin. Rejected commands are omitted from the parser. Plugin list
and detail output expose contract status, declared operations, and the rejection
reason. The contract applies to trusted installed Python code; importing a
plugin still executes Python and is not an operating-system sandbox.

## Authorization boundary

CLI dispatch authorizes a plugin's declared operation before calling its
handler. Profile-free execution is limited to C0 local analysis with no scopes,
site features, path grants, or non-local effects. External operations use their
validated descriptors with the default resolver; bundled operations use the
canonical registry, including argument-dependent submission requirements.

Python and R remote check, plan, verify, and submit handlers also authorize at
their direct function boundary. Package checks remain classified as
`remote-execute`: module loading, Python package discovery, and R
`requireNamespace` are not represented as passive filesystem reads.

## Install workflow effects

Python/R `submit-install` resolves and authorizes the complete C3 requirement,
including the destination write grant and any enabled quote or validation
scopes, before reading or staging the script. Staging uses the WP4 bounded
filesystem service under `remote_roots.write`. Existing scripts are preserved
unless `--force` is explicit. Quote, Slurm validation, submission, and local
submission logging retain their existing ordering after a successful stage.

Python/R `verify-install` reads job output through the same service under
`remote_roots.read`; unrestricted remote `cat` is removed. Dry runs validate
paths and plan later commands without staging, submitting, logging, reading a
remote output, or writing a generated local plan.

## Verification boundary

Focused tests cover accepted, unknown-version, undeclared, and profile-free
fake plugins; denial before Python/R staging, quote, validation, submission, and
record append; dry-run non-mutation; bounded staging and output reads; bundled
operation registration; and parser synchronization.

The supported `.venv` ran 408 tests: all passed, with one skip. Plugin and skill
validation and the required compilation checks passed. No live cluster, SSH
connection, scheduler action, or user configuration/state was used. The literal
system-`python3` suite remains unusable because that interpreter lacks
`tomlkit`; it produced 27 import errors. Repository hygiene still reports the
checkout's existing caches, build output, and egg-info artifacts, which were
left untouched.

WP7 must still implement profile-aware CLI hiding and display modes. WP8 must
filter MCP discovery and bind one profile. The plugin metadata contract is an
authorization declaration for trusted extensions, not confinement for
malicious imports or arbitrary code inside an allowed handler.
