from __future__ import annotations

from typing import Any


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
