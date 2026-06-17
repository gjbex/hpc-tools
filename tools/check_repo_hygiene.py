#!/usr/bin/env python3
"""Check for generated artifacts and local state that should not be published."""

from __future__ import annotations

import sys
from pathlib import Path


GENERATED_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}

GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

GENERATED_DIR_SUFFIXES = {
    ".egg-info",
}

LOCAL_STATE_NAMES = {
    "submissions.jsonl",
    "config.toml",
}


def fail(message: str) -> None:
    print(f"check_repo_hygiene.py: {message}", file=sys.stderr)
    raise SystemExit(1)


def should_skip(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    parts = relative.parts
    return ".git" in parts or ".venv" in parts or "venv" in parts


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    root = root.resolve()
    if not root.is_dir():
        fail(f"not a directory: {root}")

    problems: list[str] = []
    for path in root.rglob("*"):
        if should_skip(path, root):
            continue
        relative = path.relative_to(root)
        if path.name in GENERATED_NAMES:
            problems.append(str(relative))
        elif path.is_dir() and any(path.name.endswith(suffix) for suffix in GENERATED_DIR_SUFFIXES):
            problems.append(str(relative))
        elif path.is_file() and path.suffix in GENERATED_SUFFIXES:
            problems.append(str(relative))
        elif path.is_file() and path.name in LOCAL_STATE_NAMES and "examples" not in relative.parts:
            problems.append(str(relative))

    if problems:
        formatted = "\n  ".join(sorted(problems))
        fail(f"remove generated or local-state artifacts before publishing:\n  {formatted}")

    print(f"repository hygiene check passed for {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
