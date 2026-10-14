from __future__ import annotations

from pathlib import Path
from typing import Any

from hpc_tools import references
from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.config import ConfigError, Profile, default_config_path


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
    references_list_parser.set_defaults(
        handler=handlers.cmd_references_list,
        operation_id="references.list",
    )

    references_show_parser = references_subparsers.add_parser(
        "show",
        help="Show one shared reference set",
    )
    references_show_parser.add_argument("name", help="Reference set name")
    references_show_parser.set_defaults(
        handler=handlers.cmd_references_show,
        operation_id="references.show",
    )

    references_validate_parser = references_subparsers.add_parser(
        "validate",
        help="Validate one shared reference set",
    )
    references_validate_parser.add_argument("name", help="Reference set name")
    references_validate_parser.set_defaults(
        handler=handlers.cmd_references_validate,
        operation_id="references.validate",
    )

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
    references_create_parser.set_defaults(
        handler=handlers.cmd_references_create,
        operation_id="references.create",
    )

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
    references_export_parser.set_defaults(
        handler=handlers.cmd_references_export,
        operation_id="references.export",
    )

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
    references_import_parser.set_defaults(
        handler=handlers.cmd_references_import,
        operation_id="references.import",
    )

    references_attach_parser = references_subparsers.add_parser(
        "attach",
        help="Attach a shared reference set to the selected profile",
    )
    references_attach_parser.add_argument("name", help="Reference set name")
    references_attach_parser.set_defaults(
        handler=handlers.cmd_references_attach,
        operation_id="references.attach",
    )

    references_detach_parser = references_subparsers.add_parser(
        "detach",
        help="Detach any shared reference set from the selected profile",
    )
    references_detach_parser.set_defaults(
        handler=handlers.cmd_references_detach,
        operation_id="references.detach",
    )

def cmd_references_list(args: argparse.Namespace, profile: Profile | None) -> int:
    del args, profile
    print(references.format_reference_set_list(references.list_reference_sets()))
    return 0

def cmd_references_show(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    print(references.format_reference_set(references.load_reference_set(args.name)))
    return 0

def cmd_references_validate(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    reference_set = references.validate_reference_set(args.name)
    print(f"Reference set '{reference_set.name}' is valid: {reference_set.path}")
    return 0

def cmd_references_create(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("references.create", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; reference set '{args.name}' not created.")
        return 0
    reference_set = references.create_reference_set(args.name, profile, force=args.force)
    print(f"Reference set created: {reference_set.path}")
    return 0

def cmd_references_export(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("exporting a reference set requires a selected capability profile")
    require_authorized("references.export", profile, namespace_arguments(args))
    if args.dry_run:
        output = args.output or Path.cwd() / f"{args.name}-reference-set.tar.gz"
        print(f"Dry run; reference set archive not written: {output}")
        return 0
    archive_path = references.export_reference_set(
        args.name,
        output=args.output,
        force=args.force,
    )
    print(f"Reference set archive written: {archive_path}")
    return 0

def cmd_references_import(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("importing a reference set requires a selected capability profile")
    require_authorized("references.import", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; reference set archive not imported: {args.archive}")
        return 0
    reference_set = references.import_reference_set(args.archive, force=args.force)
    print(f"Reference set imported: {reference_set.path}")
    return 0

def cmd_references_attach(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("references.attach", profile, namespace_arguments(args))
    references.load_reference_set(args.name)
    if args.dry_run:
        print(
            f"Dry run; reference set '{args.name}' not attached to profile "
            f"'{profile.name}'."
        )
        return 0
    references.set_profile_reference_set(
        Path(args.config).expanduser() if args.config else default_config_path(),
        profile.name,
        args.name,
    )
    print(f"Attached reference set '{args.name}' to profile '{profile.name}'.")
    return 0

def cmd_references_detach(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("references.detach", profile, namespace_arguments(args))
    if args.dry_run:
        print(f"Dry run; reference set not detached from profile '{profile.name}'.")
        return 0
    references.set_profile_reference_set(
        Path(args.config).expanduser() if args.config else default_config_path(),
        profile.name,
        None,
    )
    print(f"Detached any reference set from profile '{profile.name}'.")
    return 0

