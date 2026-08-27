from __future__ import annotations

import argparse
import shlex
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from hpc_tools import slurm
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import run_command


def register(subparsers: Any, handlers: Any) -> None:
    register_probes(subparsers, handlers)
    register_containers(subparsers, handlers)


def register_probes(subparsers: Any, handlers: Any) -> None:
    generic_probe_parser = subparsers.add_parser(
        "write-probe",
        help="Write a packaged probe script or probe asset bundle",
    )
    generic_probe_parser.add_argument(
        "--kind",
        choices=sorted(handlers.PROBE_KINDS),
        default="hardware",
        help="Packaged probe kind to write",
    )
    generic_probe_parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help="Output file for hardware, output directory for bundle probes, or '-' for hardware stdout.",
    )
    generic_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    handlers.add_probe_directive_options(generic_probe_parser)
    generic_probe_parser.set_defaults(handler=handlers.cmd_write_probe)

    probe_parser = subparsers.add_parser(
        "write-hardware-probe",
        help="Write the packaged Slurm hardware probe script",
    )
    probe_parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help="Output path, or '-' for stdout. Defaults to stdout.",
    )
    probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    handlers.add_probe_directive_options(probe_parser)
    probe_parser.set_defaults(handler=handlers.cmd_write_hardware_probe)

    generic_install_probe_parser = subparsers.add_parser(
        "install-probe",
        help="Install a packaged probe script or probe asset bundle on the remote host",
    )
    generic_install_probe_parser.add_argument(
        "--kind",
        choices=sorted(handlers.PROBE_KINDS),
        default="hardware",
        help="Packaged probe kind to install",
    )
    generic_install_probe_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory where the probe assets should be written",
    )
    generic_install_probe_parser.add_argument(
        "--name",
        help="Remote script filename; defaults depend on --kind",
    )
    generic_install_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote files if they already exist",
    )
    handlers.add_probe_directive_options(generic_install_probe_parser)
    generic_install_probe_parser.set_defaults(handler=handlers.cmd_install_probe)

    install_probe_parser = subparsers.add_parser(
        "install-hardware-probe",
        help="Install the packaged Slurm hardware probe script on the remote host",
    )
    install_probe_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory where the probe script should be written",
    )
    install_probe_parser.add_argument(
        "--name",
        default="hardware-probe.slurm",
        help="Remote script filename",
    )
    install_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote script if it already exists",
    )
    handlers.add_probe_directive_options(install_probe_parser)
    install_probe_parser.set_defaults(handler=handlers.cmd_install_hardware_probe)


def register_containers(subparsers: Any, handlers: Any) -> None:
    container_parser = subparsers.add_parser(
        "write-container",
        help="Write a packaged Apptainer container build bundle",
    )
    container_parser.add_argument(
        "--kind",
        choices=sorted(handlers.CONTAINER_KINDS),
        required=True,
        help="Packaged container bundle to write",
    )
    container_parser.add_argument(
        "output",
        help="Output directory for the container bundle",
    )
    container_parser.add_argument(
        "--name",
        help="Primary Slurm script filename; defaults depend on --kind",
    )
    container_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    container_parser.set_defaults(handler=handlers.cmd_write_container)

    install_container_parser = subparsers.add_parser(
        "install-container",
        help="Install a packaged Apptainer container build bundle on the remote host",
    )
    install_container_parser.add_argument(
        "--kind",
        choices=sorted(handlers.CONTAINER_KINDS),
        required=True,
        help="Packaged container bundle to install",
    )
    install_container_parser.add_argument(
        "--directory",
        "-C",
        required=True,
        help="Remote directory where the bundle should be written",
    )
    install_container_parser.add_argument(
        "--name",
        help="Primary Slurm script filename; defaults depend on --kind",
    )
    install_container_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote files if they already exist",
    )
    install_container_parser.set_defaults(handler=handlers.cmd_install_container)

def _add_probe_directive_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="Add #SBATCH --account=<account>")
    parser.add_argument("--cluster", "--clusters", dest="cluster", help="Add #SBATCH --clusters=<cluster>")
    parser.add_argument("--partition", help="Add #SBATCH --partition=<partition>")
    parser.add_argument("--qos", help="Add #SBATCH --qos=<qos>")
    parser.add_argument("--time", help="Replace the template #SBATCH --time value")
    parser.add_argument("--cpus-per-task", help="Add #SBATCH --cpus-per-task=<count>")
    parser.add_argument(
        "--mail-notifications",
        action="store_true",
        help="Add END,FAIL Slurm email notifications using the selected profile email",
    )
    parser.add_argument(
        "--mail-user",
        help="Add END,FAIL Slurm email notifications for this address",
    )

def cmd_write_hardware_probe(args: argparse.Namespace, profile: Profile | None) -> int:
    args.kind = "hardware"
    return cmd_write_probe(args, profile)

def cmd_install_hardware_probe(args: argparse.Namespace, profile: Profile) -> int:
    args.kind = "hardware"
    if not getattr(args, "name", None):
        args.name = "hardware-probe.slurm"
    return cmd_install_probe(args, profile)

def cmd_write_probe(args: argparse.Namespace, profile: Profile | None) -> int:
    if args.kind == "hardware":
        template = _hardware_probe_template(args, profile)
        if args.output == "-":
            sys.stdout.write(template)
            return 0

        output_path = Path(args.output).expanduser()
        if output_path.exists() and not args.force:
            raise ConfigError(f"output file already exists: {output_path}; use --force to overwrite")
        output_path.write_text(template, encoding="utf-8")
        return 0

    if args.kind == "cuda-device-properties":
        if args.output == "-":
            raise ConfigError("write-probe --kind cuda-device-properties requires an output directory")
        _write_cuda_device_properties_bundle(Path(args.output).expanduser(), force=args.force)
        return 0

    raise ConfigError(f"unsupported probe kind: {args.kind}")

def cmd_install_probe(args: argparse.Namespace, profile: Profile) -> int:
    if args.kind == "hardware":
        command = _install_hardware_probe_command(
            args.directory,
            args.name or "hardware-probe.slurm",
            _hardware_probe_template(args, profile),
            force=args.force,
        )
    elif args.kind == "cuda-device-properties":
        command = _install_cuda_device_properties_command(
            args.directory,
            args.name or "cuda-device-properties.slurm",
            force=args.force,
        )
    else:
        raise ConfigError(f"unsupported probe kind: {args.kind}")
    return run_command(profile, command, dry_run=args.dry_run)

def cmd_write_container(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    bundle = _container_bundle(args.kind)
    output_dir = Path(args.output).expanduser()
    _write_bundle_assets(output_dir, bundle, force=args.force)
    print(f"Container bundle written to {output_dir}")
    return 0

def cmd_install_container(args: argparse.Namespace, profile: Profile) -> int:
    bundle = _container_bundle(args.kind)
    command = _install_bundle_command(
        directory=args.directory,
        bundle=bundle,
        force=args.force,
    )
    return run_command(profile, command, dry_run=args.dry_run)

def _hardware_probe_template(args: argparse.Namespace | None = None, profile: Profile | None = None) -> str:
    template = resources.files("hpc_tools.data").joinpath("hardware-probe.slurm").read_text(
        encoding="utf-8"
    )
    if args is None:
        return template

    insertions = []
    mail_user = _resolve_mail_user(args, profile)
    for option_name, directive_name in [
        ("account", "account"),
        ("cluster", "clusters"),
        ("partition", "partition"),
        ("qos", "qos"),
        ("cpus_per_task", "cpus-per-task"),
    ]:
        value = getattr(args, option_name, None)
        if value:
            insertions.append(f"#SBATCH --{directive_name}={value}")
    if mail_user:
        insertions.append(f"#SBATCH --mail-user={mail_user}")
        insertions.append("#SBATCH --mail-type=END,FAIL")

    rendered = []
    inserted = False
    for line in template.splitlines():
        if line.startswith("#SBATCH --time=") and getattr(args, "time", None):
            rendered.append(f"#SBATCH --time={args.time}")
            continue
        rendered.append(line)
        if line.startswith("#SBATCH --output=") and not inserted:
            rendered.extend(insertions)
            inserted = True
    return "\n".join(rendered) + "\n"

def _resolve_mail_user(args: argparse.Namespace, profile: Profile | None) -> str | None:
    mail_user = getattr(args, "mail_user", None)
    if mail_user:
        return mail_user
    if not getattr(args, "mail_notifications", False):
        return None
    if profile is None or profile.email is None:
        raise ConfigError("--mail-notifications requires a selected profile with an email field")
    return profile.email

def _install_hardware_probe_command(
    directory: str,
    name: str,
    contents: str,
    *,
    force: bool = False,
) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    remote_name = shlex.quote(name)
    overwrite_check = ""
    if not force:
        overwrite_check = (
            f"if [ -e {remote_name} ]; then "
            f"echo 'output file already exists: {name}; use --force to overwrite' >&2; "
            "exit 1; "
            "fi\n"
        )
    delimiter = "HPC_TOOLS_HARDWARE_PROBE_TEMPLATE"
    return (
        f"mkdir -p {remote_dir} && cd {remote_dir} && "
        f"{overwrite_check}"
        f"cat > {remote_name} <<'{delimiter}'\n"
        f"{contents}"
        f"{delimiter}\n"
        f"chmod +x {remote_name}"
    )

def _cuda_device_properties_bundle() -> dict[str, str]:
    data = resources.files("hpc_tools.data")
    return {
        "cuda-device-properties.slurm": data.joinpath("cuda-device-properties.slurm").read_text(
            encoding="utf-8"
        ),
        "cuda/CMakeLists.txt": data.joinpath("cuda", "CMakeLists.txt").read_text(
            encoding="utf-8"
        ),
        "cuda/device_properties.cu": data.joinpath("cuda", "device_properties.cu").read_text(
            encoding="utf-8"
        ),
    }

def _container_bundle(kind: str) -> dict[str, str]:
    data = resources.files("hpc_tools.data").joinpath("containers", "apptainer" if kind == "generic" else kind)
    if kind == "agent":
        return {
            "Apptainer.def": data.joinpath("Apptainer.def").read_text(encoding="utf-8"),
            "hpc-mcp-relay": resources.files("hpc_tools").joinpath("mcp_bridge.py").read_text(
                encoding="utf-8"
            ),
            "codex-agent": data.joinpath("codex-agent").read_text(encoding="utf-8"),
            "config.toml": data.joinpath("codex-config.toml").read_text(encoding="utf-8"),
            "restricted-agent.slurm": data.joinpath("restricted-agent.slurm").read_text(
                encoding="utf-8"
            ),
        }
    if kind == "generic":
        return {
            "create_apptainer_container.slurm": data.joinpath("create_apptainer_container.slurm").read_text(
                encoding="utf-8"
            ),
        }
    if kind == "r":
        return {
            "create_r_container.slurm": data.joinpath("create_r_container.slurm").read_text(
                encoding="utf-8"
            ),
            "apt_packages.txt": data.joinpath("apt_packages.txt").read_text(encoding="utf-8"),
            "install_packages.R": data.joinpath("install_packages.R").read_text(encoding="utf-8"),
            "labels.txt": data.joinpath("labels.txt").read_text(encoding="utf-8"),
        }
    if kind == "conda":
        return {
            "create_conda_container.slurm": data.joinpath("create_conda_container.slurm").read_text(
                encoding="utf-8"
            ),
            "environment.yml": data.joinpath("environment.yml").read_text(encoding="utf-8"),
            "labels.txt": data.joinpath("labels.txt").read_text(encoding="utf-8"),
        }
    raise ConfigError(f"unsupported container kind: {kind}")

def _write_bundle_assets(output_dir: Path, bundle: dict[str, str], *, force: bool = False) -> None:
    for relative_path in bundle:
        destination = output_dir / relative_path
        if destination.exists() and not force:
            raise ConfigError(f"output file already exists: {destination}; use --force to overwrite")

    for relative_path, contents in bundle.items():
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    for relative_path in bundle:
        if relative_path.endswith(".slurm"):
            (output_dir / relative_path).chmod(0o755)

def _install_bundle_command(*, directory: str, bundle: dict[str, str], force: bool = False) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    commands = [f"mkdir -p {remote_dir} && cd {remote_dir}"]
    if not force:
        for relative_path in bundle:
            quoted_path = shlex.quote(relative_path)
            commands.append(
                f"if [ -e {quoted_path} ]; then "
                f"echo 'output file already exists: {relative_path}; use --force to overwrite' >&2; "
                "exit 1; "
                "fi"
            )
    for index, (relative_path, contents) in enumerate(bundle.items()):
        quoted_path = shlex.quote(relative_path)
        delimiter = f"HPC_TOOLS_CONTAINER_BUNDLE_{index}"
        commands.append(
            f"cat > {quoted_path} <<'{delimiter}'\n"
            f"{contents}"
            f"{delimiter}\n"
        )
    for relative_path in bundle:
        if relative_path.endswith(".slurm"):
            commands.append(f"chmod +x {shlex.quote(relative_path)}")
    return "\n".join(commands)

def _write_cuda_device_properties_bundle(output_dir: Path, *, force: bool = False) -> None:
    bundle = _cuda_device_properties_bundle()
    for relative_path in bundle:
        destination = output_dir / relative_path
        if destination.exists() and not force:
            raise ConfigError(f"output file already exists: {destination}; use --force to overwrite")

    for relative_path, contents in bundle.items():
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    (output_dir / "cuda-device-properties.slurm").chmod(0o755)

def _install_cuda_device_properties_command(
    directory: str,
    script_name: str,
    *,
    force: bool = False,
) -> str:
    bundle = _cuda_device_properties_bundle()
    remote_dir = slurm._quote_remote_path_expression(directory)
    script_path = shlex.quote(script_name)
    file_map = {
        script_name: bundle["cuda-device-properties.slurm"],
        "cuda/CMakeLists.txt": bundle["cuda/CMakeLists.txt"],
        "cuda/device_properties.cu": bundle["cuda/device_properties.cu"],
    }

    overwrite_checks = []
    if not force:
        for relative_path in file_map:
            quoted_path = shlex.quote(relative_path)
            overwrite_checks.append(
                f"if [ -e {quoted_path} ]; then "
                f"echo 'output file already exists: {relative_path}; use --force to overwrite' >&2; "
                "exit 1; "
                "fi"
            )

    commands = [f"mkdir -p {remote_dir} && cd {remote_dir} && mkdir -p cuda"]
    commands.extend(overwrite_checks)
    for index, (relative_path, contents) in enumerate(file_map.items()):
        quoted_path = shlex.quote(relative_path)
        delimiter = f"HPC_TOOLS_CUDA_DEVICE_PROPERTIES_{index}"
        commands.append(
            f"cat > {quoted_path} <<'{delimiter}'\n"
            f"{contents}"
            f"{delimiter}\n"
        )
    commands.append(f"chmod +x {script_path}")
    return "\n".join(commands)
