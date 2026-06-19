from __future__ import annotations

from hpc_tools.plugins.cxx import commands, dependencies

for _module in (commands, dependencies):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )
