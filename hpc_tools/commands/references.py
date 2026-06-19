from __future__ import annotations

from pathlib import Path
from typing import Any


def register(subparsers: Any, handlers: Any) -> None:
    references_parser = subparsers.add_parser(
        "references",
        help="Manage shared cluster reference sets",
    )
    references_subparsers = references_parser.add_subparsers(
        dest="references_command",
        metavar="<subcommand>",
        required=True,
    )

    references_list_parser = references_subparsers.add_parser(
        "list",
        help="List installed shared reference sets",
    )
    references_list_parser.set_defaults(handler=handlers.cmd_references_list)

    references_show_parser = references_subparsers.add_parser(
        "show",
        help="Show one shared reference set",
    )
    references_show_parser.add_argument("name", help="Reference set name")
    references_show_parser.set_defaults(handler=handlers.cmd_references_show)

    references_validate_parser = references_subparsers.add_parser(
        "validate",
        help="Validate one shared reference set",
    )
    references_validate_parser.add_argument("name", help="Reference set name")
    references_validate_parser.set_defaults(handler=handlers.cmd_references_validate)

    references_create_parser = references_subparsers.add_parser(
        "create",
        help="Create a shared reference set from the selected profile",
    )
    references_create_parser.add_argument("name", help="Reference set name")
    references_create_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination reference set if it already exists",
    )
    references_create_parser.set_defaults(handler=handlers.cmd_references_create)

    references_export_parser = references_subparsers.add_parser(
        "export",
        help="Export one shared reference set as a tar.gz archive",
    )
    references_export_parser.add_argument("name", help="Reference set name")
    references_export_parser.add_argument(
        "--output",
        type=Path,
        help="Archive output path; defaults to ./<name>-reference-set.tar.gz",
    )
    references_export_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the archive if it already exists",
    )
    references_export_parser.set_defaults(handler=handlers.cmd_references_export)

    references_import_parser = references_subparsers.add_parser(
        "import",
        help="Import a shared reference set archive",
    )
    references_import_parser.add_argument("archive", type=Path, help="Reference set archive path")
    references_import_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing installed reference set",
    )
    references_import_parser.set_defaults(handler=handlers.cmd_references_import)

    references_attach_parser = references_subparsers.add_parser(
        "attach",
        help="Attach a shared reference set to the selected profile",
    )
    references_attach_parser.add_argument("name", help="Reference set name")
    references_attach_parser.set_defaults(handler=handlers.cmd_references_attach)

    references_detach_parser = references_subparsers.add_parser(
        "detach",
        help="Detach any shared reference set from the selected profile",
    )
    references_detach_parser.set_defaults(handler=handlers.cmd_references_detach)
