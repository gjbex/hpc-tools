# WP2 mandatory per-profile policy

Status: implemented on 2026-10-13. WP2 validates, stores, narrows, intersects,
and summarizes capability policy. It does not authorize operations; registry
and evaluator enforcement starts in WP3.

## Implemented model

`hpc_tools.capabilities` defines policy schema version 1 with four ordered
levels:

1. `profile-context`
2. `cluster-discovery`
3. `job-inspection`
4. `job-lifecycle`

It also defines the recognized independent scopes and immutable remote-root
grants for `list`, `read`, `write`, `delete`, and `install`. Scope and root
collections default to empty. `Profile.capabilities` is required; no implicit,
legacy, or unrestricted policy exists.

The parser rejects missing/empty policy, unsupported versions, unknown policy
or root keys, unknown or duplicate scopes, malformed lists, duplicate roots,
relative roots, the filesystem root `/`, traversal, glob syntax, command
substitution, shell syntax, extra expansion, and ambiguous separators.
Accepted roots are absolute paths, `~` paths, or paths beginning with one
environment variable such as `$VSC_DATA`.

Requested-level narrowing takes the lower level. Policy intersection takes the
lowest level, common scopes, and exactly common root declarations; it never
unions grants. Semantic ancestor/descendant and remote-realpath intersection is
deferred to WP4 because it requires target-host resolution.

`profile_capability_summary` exposes only the profile name and plain policy
data. It does not expose SSH identity, site commands, paths outside declared
root grants, email, or other raw profile fields.

## Configuration and documentation synchronization

Every complete checked-in profile example now contains:

```toml
[profiles.example.capabilities]
version = 1
max_level = "cluster-discovery"
```

The two installable TOML examples are loaded by tests. A documentation test
extracts every TOML code block containing a profile from the README, capability
proposal, and user documentation and loads it through the real configuration
parser. This prevents documented policy syntax from drifting away from the
implementation.

## Verification

Focused tests cover all levels, absent/empty/invalid blocks, unsupported
versions, unknown scopes and keys, malformed and unsafe roots, immutable
defaults, multiple profiles, XDG and explicit config selection, narrowing,
intersection, safe summaries, checked-in examples, and absence of external
queries or configuration writes. The complete supported-environment result is
recorded in the [capability implementation plan](../implementation-plan.md).
