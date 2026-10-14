from __future__ import annotations

import argparse
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_cli_fixtures import make_profile

from hpc_tools.authorization import CapabilityAuthorizationError
from hpc_tools.capabilities import CapabilityLevel
from hpc_tools.cli import build_parser
from hpc_tools.commands.core import cmd_plugins_info
from hpc_tools.operation_registry import OperationDescriptor
from hpc_tools import plugin_system
from hpc_tools.plugins import python_support, r_support


class _Distribution:
    name = "fake-distribution"
    version = "1.0"


class _EntryPoint:
    name = "demo"
    dist = _Distribution()

    def __init__(self, plugin: object) -> None:
        self._plugin = plugin

    def load(self) -> object:
        return self._plugin


def _operation(
    operation_id: str = "demo.inspect",
    binding: str = "demo inspect",
    *,
    level: CapabilityLevel = CapabilityLevel.CLUSTER_DISCOVERY,
    effects: tuple[str, ...] = ("remote-read",),
    profile_required: bool = True,
) -> OperationDescriptor:
    return OperationDescriptor(
        id=operation_id,
        minimum_level=level,
        scopes=(),
        effects=effects,
        cli=(binding,),
        profile_required=profile_required,
    )


def _root_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return action.choices


class _Plugin:
    name = "demo"
    description = "Test plugin"
    contract_version = plugin_system.PLUGIN_CONTRACT_VERSION
    operations = (_operation(),)

    def __init__(self) -> None:
        self.handler = mock.Mock(return_value=0)

    def register(self, subparsers: object, profile: object | None) -> None:
        del profile
        parser = subparsers.add_parser("demo", help="Test plugin")
        children = parser.add_subparsers(dest="demo_command", required=True)
        inspect = children.add_parser("inspect", help="Inspect remotely")
        inspect.set_defaults(handler=self.handler, operation_id="demo.inspect")

    def requires_profile(self, argv: list[str]) -> bool:
        del argv
        return True


class PluginContractTests(unittest.TestCase):
    def setUp(self) -> None:
        plugin_system._REGISTRATION_ERRORS.clear()

    def tearDown(self) -> None:
        plugin_system._REGISTRATION_ERRORS.clear()

    def test_declared_external_operation_registers_and_is_authorized(self) -> None:
        plugin = _Plugin()
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ):
            parser = build_parser(make_profile())
            args = parser.parse_args(["demo", "inspect"])
            plugin_system.authorize_plugin_command(args, make_profile())
            self.assertEqual(args.handler(args, make_profile()), 0)

        plugin.handler.assert_called_once()

    def test_declared_external_operation_denied_before_handler(self) -> None:
        plugin = _Plugin()
        profile = replace(
            make_profile(),
            capabilities=replace(
                make_profile().capabilities,
                max_level=CapabilityLevel.PROFILE_CONTEXT,
            ),
        )
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ):
            args = build_parser(profile).parse_args(["demo", "inspect"])
            with self.assertRaises(CapabilityAuthorizationError):
                plugin_system.authorize_plugin_command(args, profile)

        plugin.handler.assert_not_called()

    def test_profile_free_declared_local_operation_remains_usable(self) -> None:
        plugin = _Plugin()
        plugin.operations = (
            _operation(
                level=CapabilityLevel.PROFILE_CONTEXT,
                effects=("local-read",),
                profile_required=False,
            ),
        )
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ):
            args = build_parser().parse_args(["demo", "inspect"])
            plugin_system.authorize_plugin_command(args, None)

    def test_unknown_contract_version_is_rejected_and_omitted(self) -> None:
        plugin = _Plugin()
        plugin.contract_version = 99
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ):
            loaded = plugin_system.get_plugin("demo")
            parser = build_parser()

        self.assertIsNotNone(loaded)
        self.assertFalse(loaded.available)
        self.assertIn("expected 1", loaded.contract_error)
        self.assertNotIn("demo", _root_choices(parser))

    def test_undeclared_registered_leaf_is_rejected_and_omitted(self) -> None:
        class UndeclaredPlugin(_Plugin):
            def register(self, subparsers: object, profile: object | None) -> None:
                del profile
                parser = subparsers.add_parser("demo", help="Test plugin")
                children = parser.add_subparsers(dest="demo_command", required=True)
                rogue = children.add_parser("rogue", help="Undeclared operation")
                rogue.set_defaults(handler=self.handler, operation_id="demo.rogue")

        plugin = UndeclaredPlugin()
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ):
            parser = build_parser()
            loaded = plugin_system.get_plugin("demo")

        self.assertNotIn("demo", _root_choices(parser))
        self.assertFalse(loaded.available)
        self.assertIn("undeclared bindings", loaded.contract_error)

    def test_plugin_information_explains_rejected_contract(self) -> None:
        plugin = _Plugin()
        plugin.contract_version = 99
        with mock.patch.object(
            plugin_system,
            "_iter_plugin_entry_points",
            return_value=[_EntryPoint(plugin)],
        ), contextlib.redirect_stdout(io.StringIO()) as stdout:
            rendered = plugin_system.format_plugins(plugin_system.load_plugins())
            self.assertEqual(
                cmd_plugins_info(argparse.Namespace(name="demo"), None),
                0,
            )

        self.assertIn("CONTRACT", rendered)
        self.assertIn("rejected", rendered)
        self.assertIn("contract_error:", stdout.getvalue())
        self.assertIn("expected 1", stdout.getvalue())

    def test_denied_install_submissions_have_no_effects(self) -> None:
        profile = replace(
            make_profile(),
            capabilities=replace(
                make_profile().capabilities,
                max_level=CapabilityLevel.JOB_INSPECTION,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "install.slurm"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            args = argparse.Namespace(
                jobscript=script,
                directory="$VSC_DATA/Projects/demo",
                account="proj123",
                remote_name=None,
                cluster="wice",
                partition="batch_icelake",
                reservation=None,
                time="00:30:00",
                cpus_per_task="2",
                nodes="1",
                skip_quote=False,
                no_validate_first=False,
                dry_run=False,
                force=False,
            )
            for module, handler in (
                ("python", python_support.cmd_python_submit_install),
                ("r", r_support.cmd_r_submit_install),
            ):
                with self.subTest(module=module), mock.patch(
                    f"hpc_tools.plugins.{module}.commands.install_remote_assets"
                ) as stage, mock.patch(
                    f"hpc_tools.plugins.{module}.commands.run_command_capture"
                ) as remote, mock.patch(
                    f"hpc_tools.plugins.{module}.install_plan.submissions.append_event"
                ) as append:
                    with self.assertRaises(CapabilityAuthorizationError):
                        handler(args, profile)
                    stage.assert_not_called()
                    remote.assert_not_called()
                    append.assert_not_called()

    def test_install_submission_dry_run_does_not_stage_or_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "install.slurm"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            args = argparse.Namespace(
                jobscript=script,
                directory="$VSC_DATA/Projects/demo",
                account="proj123",
                remote_name=None,
                cluster="wice",
                partition="batch_icelake",
                reservation=None,
                time="00:30:00",
                cpus_per_task="2",
                nodes="1",
                skip_quote=False,
                no_validate_first=False,
                dry_run=True,
                force=False,
            )
            with mock.patch(
                "hpc_tools.plugins.python.commands.install_remote_assets"
            ) as stage, mock.patch(
                "hpc_tools.plugins.python.install_plan.submissions.append_event"
            ) as append, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    python_support.cmd_python_submit_install(args, make_profile()),
                    0,
                )

        stage.assert_not_called()
        append.assert_not_called()

    def test_install_plan_dry_run_does_not_write_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "analysis.py"
            target.write_text("import mmh3\n", encoding="utf-8")
            output = root / "install.slurm"
            args = argparse.Namespace(
                target=target,
                packages=["mmh3"],
                modules=["Python/3.13"],
                output=output,
                venv="$VSC_DATA/Projects/demo/.venv",
                cluster="wice",
                partition="batch",
                job_name="python-package-install",
                time="00:30:00",
                cpus_per_task="2",
                arch_guard=None,
                no_system_site_packages=False,
                upgrade_pip=False,
                force=False,
                dry_run=True,
            )
            check = SimpleNamespace(
                returncode=1,
                available=[],
                missing=["mmh3"],
                stderr="",
                modules=args.modules,
            )
            with mock.patch(
                "hpc_tools.plugins.python.commands.check_packages",
                return_value=check,
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    python_support.cmd_python_plan_install(args, make_profile()),
                    0,
                )

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
