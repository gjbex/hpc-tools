from __future__ import annotations

from hpc_tools.plugins.python import commands, dependencies, install_plan, remote_verify

for _module in (commands, dependencies, install_plan, remote_verify):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )

