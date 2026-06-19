from __future__ import annotations

import shlex


def _tool_check_loop(tools: list[str]) -> str:
    quoted_tools = " ".join(shlex.quote(tool) for tool in tools)
    return (
        f"for tool in {quoted_tools}; do "
        "printf '%s: ' \"$tool\"; command -v \"$tool\" || true; "
        "done"
    )


def _section_command(title: str, command: str) -> str:
    return f"printf '\\n## {title}\\n'; {command}"


def _quote_remote_path_expression(path: str) -> str:
    if path.startswith("$") or path.startswith("~"):
        return path
    return shlex.quote(path)
