#!/usr/bin/env python3
"""Validate wheel/sdist capability behavior in isolated pipx installations."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import zipfile
from pathlib import Path

MCP_PROTOCOL_PROBE = r"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def inspect_server(server: str, config: str, profile: str) -> dict[str, object]:
    environment = dict(os.environ)
    environment["HPC_TOOLS_CONFIG"] = config
    parameters = StdioServerParameters(
        command=server,
        args=["--config", config, "--profile", profile, "--preset", "full"],
        env=environment,
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            resources = (await session.list_resources()).resources
            names = {tool.name for tool in tools}
            uris = {str(resource.uri) for resource in resources}
            for tool in tools:
                properties = tool.inputSchema.get("properties", {})
                forbidden = {"profile", "config", "database"}.intersection(properties)
                if forbidden:
                    raise AssertionError(
                        f"{tool.name} exposes trusted selectors: {sorted(forbidden)}"
                    )

            listed = await session.call_tool("hpc_profiles_list", {})
            if listed.isError or profile not in "".join(
                getattr(block, "text", "") for block in listed.content
            ):
                raise AssertionError(f"profile-bound tool call failed for {profile}")

            runtime = await session.read_resource("hpc://runtime")
            if profile not in "".join(
                getattr(block, "text", "") for block in runtime.contents
            ):
                raise AssertionError(f"runtime resource is not bound to {profile}")

            try:
                escaped = await session.call_tool(
                    "hpc_profiles_list", {"config": str(Path(config).with_suffix(".other"))}
                )
            except Exception:
                pass
            else:
                escaped_text = "".join(
                    getattr(block, "text", "") for block in escaped.content
                )
                if escaped.isError:
                    pass
                elif (
                    profile not in escaped_text
                    or str(Path(config).with_suffix(".other")) in escaped_text
                ):
                    raise AssertionError("alternate config argument escaped the bound context")

            try:
                await session.read_resource("hpc://profiles/other")
            except Exception:
                pass
            else:
                raise AssertionError("guessed cross-profile URI unexpectedly resolved")

            return {"profile": profile, "tools": sorted(names), "resources": sorted(uris)}


async def main() -> None:
    server, config = sys.argv[1:3]
    context = await inspect_server(server, config, "context")
    inspect = await inspect_server(server, config, "inspect")
    if "hpc_jobs" in context["tools"]:
        raise AssertionError("C0 context server exposed hpc_jobs")
    if "hpc_jobs" not in inspect["tools"]:
        raise AssertionError("C2 inspection server omitted hpc_jobs")
    for surface in (context, inspect):
        if "hpc_submit_job" in surface["tools"]:
            raise AssertionError("non-C3 server exposed hpc_submit_job")
    print(json.dumps({"context": context, "inspect": inspect}, sort_keys=True))


asyncio.run(main())
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Keep isolated pipx homes below this directory instead of a temporary one",
    )
    return parser


def _run(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    capture: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    print("$ " + shlex.join(argv), flush=True)
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if completed.returncode:
        if capture:
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
        raise RuntimeError(
            f"command failed with exit status {completed.returncode}: {shlex.join(argv)}"
        )
    return completed


def _validate_artifacts(wheel: Path, sdist: Path) -> tuple[Path, Path]:
    wheel = wheel.expanduser().resolve()
    sdist = sdist.expanduser().resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError(f"wheel artifact not found or invalid: {wheel}")
    if not sdist.is_file() or not sdist.name.endswith(".tar.gz"):
        raise ValueError(f"source archive not found or invalid: {sdist}")
    _check_archive_contract(wheel, sdist)
    return wheel, sdist


def _check_archive_contract(wheel: Path, sdist: Path) -> None:
    image_skill = "hpc_tools/data/containers/agent/skills/hpc-delegated-slurm/SKILL.md"
    image_reference = (
        "hpc_tools/data/containers/agent/skills/"
        "hpc-delegated-slurm/references/job-design.md"
    )
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    image_runtime_assets = (
        "hpc_tools/data/containers/agent/Apptainer.def",
        "hpc_tools/data/containers/agent/codex-agent",
        "hpc_tools/data/containers/agent/codex-config-model-only.toml",
        "hpc_tools/data/containers/agent/codex-config-model-indexed-search.toml",
        "hpc_tools/data/containers/agent/codex-config-model-live-search.toml",
    )
    for required in (image_skill, image_reference, *image_runtime_assets):
        if required not in wheel_names:
            raise AssertionError(f"wheel omitted restricted-agent asset: {required}")
    if "skills/hpc-slurm-jobs/SKILL.md" in wheel_names:
        raise AssertionError("wheel combined the Codex plugin skill surface")

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = {
            "/".join(Path(member.name).parts[1:])
            for member in archive.getmembers()
            if len(Path(member.name).parts) > 1
        }
    required_source_assets = {
        image_skill,
        image_reference,
        ".codex-plugin/plugin.json",
        "skills/hpc-slurm-jobs/SKILL.md",
        "examples/delegations/delegation-manifest-v4.schema.json",
        "examples/delegations/restricted-agent-credit-minimal.toml",
        "examples/delegations/restricted-agent-credit-full.toml",
    }
    missing = sorted(required_source_assets - sdist_names)
    if missing:
        raise AssertionError(f"source archive omitted synchronized assets: {missing}")


def _pipx_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PIPX_HOME": str(root / "home"),
            "PIPX_BIN_DIR": str(root / "bin"),
            "PIPX_MAN_DIR": str(root / "man"),
            "PIPX_DEFAULT_PYTHON": sys.executable,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    return environment


def _write_config(root: Path) -> Path:
    config = root / "config.toml"
    config.write_text(
        textwrap.dedent(
            """
            default_profile = "context"

            [profiles.context]

            [profiles.context.capabilities]
            version = 1
            max_level = "profile-context"
            scopes = []

            [profiles.inspect]
            ssh_target = "not-contacted.example.invalid"
            default_cluster = "example"

            [profiles.inspect.capabilities]
            version = 1
            max_level = "job-inspection"
            scopes = []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def _environment_python(root: Path) -> Path:
    executable = root / "home" / "venvs" / "hpc-tools" / "bin" / "python"
    if not executable.is_file():
        raise RuntimeError(f"pipx environment Python was not created: {executable}")
    return executable


def _check_packaged_helper(
    python: Path,
    *,
    expect_mcp: bool,
    cwd: Path,
) -> None:
    source = textwrap.dedent(
        f"""
        from importlib import resources, util
        from pathlib import Path
        import hpc_tools
        import sys
        package = Path(hpc_tools.__file__).resolve()
        assert package.is_relative_to(Path(sys.prefix).resolve()), (package, sys.prefix)
        helper = resources.files("hpc_tools.data").joinpath("filesystem_helper.py")
        assert helper.is_file(), helper
        skill = resources.files("hpc_tools.data").joinpath(
            "containers", "agent", "skills", "hpc-delegated-slurm", "SKILL.md"
        )
        skill_text = skill.read_text(encoding="utf-8")
        assert "credit_budget.maximum_total" in skill_text
        assert "quote.expired" in skill_text
        assert (util.find_spec("mcp") is not None) is {expect_mcp!r}
        print(helper, skill)
        """
    )
    _run([str(python), "-c", source], cwd=cwd)


def _install_with_pipx(
    pipx: str,
    spec: str,
    root: Path,
) -> tuple[dict[str, str], Path, Path]:
    root.mkdir(parents=True)
    environment = _pipx_environment(root)
    _run([pipx, "install", "--force", spec], env=environment, cwd=root)
    python = _environment_python(root)
    bin_dir = Path(environment["PIPX_BIN_DIR"])
    return environment, python, bin_dir


def _accept(wheel: Path, sdist: Path, root: Path) -> None:
    pipx = shutil.which("pipx")
    if pipx is None:
        raise RuntimeError("pipx is required for installed-distribution acceptance")
    config = _write_config(root)

    wheel_root = root / "wheel-cli"
    wheel_env, wheel_python, wheel_bin = _install_with_pipx(
        pipx, str(wheel), wheel_root
    )
    _check_packaged_helper(wheel_python, expect_mcp=False, cwd=wheel_root)
    capabilities = _run(
        [
            str(wheel_bin / "hpc"),
            "--config",
            str(config),
            "--profile",
            "context",
            "capabilities",
        ],
        env=wheel_env,
        capture=True,
        cwd=wheel_root,
    )
    if "execution max level: profile-context" not in capabilities.stdout:
        raise AssertionError("wheel CLI did not load the C0 capability profile")

    sdist_root = root / "sdist-mcp"
    sdist_spec = f"{sdist}[mcp]"
    sdist_env, sdist_python, sdist_bin = _install_with_pipx(
        pipx, sdist_spec, sdist_root
    )
    _check_packaged_helper(sdist_python, expect_mcp=True, cwd=sdist_root)
    _run(
        [
            str(sdist_bin / "hpc"),
            "--config",
            str(config),
            "--profile",
            "inspect",
            "capabilities",
        ],
        env=sdist_env,
        cwd=sdist_root,
    )
    probe = root / "mcp_protocol_probe.py"
    probe.write_text(MCP_PROTOCOL_PROBE, encoding="utf-8")
    _run(
        [
            str(sdist_python),
            str(probe),
            str(sdist_bin / "hpc-mcp"),
            str(config),
        ],
        env=sdist_env,
        cwd=sdist_root,
    )

    print(
        json.dumps(
            {
                "wheel": str(wheel),
                "sdist": str(sdist),
                "wheel_cli_only": "passed",
                "sdist_optional_mcp_protocol": "passed",
                "packaged_filesystem_helper": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wheel, sdist = _validate_artifacts(args.wheel, args.sdist)
        if args.work_dir:
            root = args.work_dir.expanduser().resolve()
            root.mkdir(parents=True, exist_ok=False)
            _accept(wheel, sdist, root)
        else:
            with tempfile.TemporaryDirectory(prefix="hpc-tools-wp12-") as directory:
                _accept(wheel, sdist, Path(directory))
    except (AssertionError, OSError, RuntimeError, ValueError) as error:
        print(f"distribution acceptance failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
