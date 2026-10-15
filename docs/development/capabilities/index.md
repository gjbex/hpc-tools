# Capability design and implementation

This section preserves the technical design, dependency-ordered implementation
plan, and dated acceptance records for the hpc-tools capability model. It is
maintainer-facing development documentation rather than configuration guidance
for ordinary users.

For current usage and policy configuration, read the
[Capability policy](../../capabilities.md) guide.

## Current design and plan

- [Capability model](design.md) is the technical design authority for the
  C0--C3 hierarchy, independent scopes, filesystem roots, CLI visibility, MCP
  discovery, plugins, and restricted-agent intersection.
- [Capability implementation plan](implementation-plan.md) records the ordered
  work packages, their dependencies, and their completion status.
- [MCP server roadmap](../mcp-roadmap.md) tracks the broader structured-agent
  interface that the capability implementation constrains.

## Completed work packages

The records below are retained as dated implementation and acceptance evidence.
They describe what was verified at each stage; the current user-facing guide
and source code remain authoritative for present behavior.

1. [WP1: capability surface inventory](work-packages/wp01-surface-inventory.md)
2. [WP2: mandatory per-profile policy](work-packages/wp02-profile-policy.md)
3. [WP3: shared operation registry and evaluator](work-packages/wp03-operation-registry.md)
4. [WP4: bounded filesystem foundation](work-packages/wp04-filesystem-foundation.md)
5. [WP5: built-in authorization and effect boundaries](work-packages/wp05-built-in-authorization.md)
6. [WP6: Python CLI plugin authorization](work-packages/wp06-plugin-authorization.md)
7. [WP7: CLI policy and visibility](work-packages/wp07-cli-policy.md)
8. [WP8: MCP profile policy and discovery](work-packages/wp08-mcp-policy.md)
9. [WP9: bounded file operations](work-packages/wp09-file-operations.md)
10. [WP10: restricted-agent integration](work-packages/wp10-restricted-agent.md)
11. [WP11: documentation, examples, and packaging](work-packages/wp11-documentation-packaging.md)
12. [WP12: acceptance and handoff](work-packages/wp12-acceptance.md)
