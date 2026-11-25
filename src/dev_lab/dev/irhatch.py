"""THE IR BUILD HOOK: hatchling runs ``irschema generate`` at package build, so a wheel carries its generated IR.

dev-lab ships it (the ``hatch`` entry point ``ir-schema``); a consumer declares it::

    [build-system]
    requires = ["hatchling", "dev-lab"]

    [tool.hatch.build.hooks.ir-schema]

The generated files are git-ignored, so the hook also names them as build ARTIFACTS, which hatchling includes despite
the ignore. A version bump below the change's class refuses the build exactly as ``generate`` refuses it.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.plugin import hookimpl

from dev_lab.dev import irpython
from dev_lab.dev.ircheck import load
from dev_lab.dev.irversion import at_revision, bump_refusal

__all__ = ['IrSchemaBuildHook', 'hatch_register_build_hook']


class IrSchemaBuildHook(BuildHookInterface):
    """Generate the repo's IR Python before hatchling collects the package."""

    PLUGIN_NAME = 'ir-schema'

    def initialize(self, version: str, build_data: dict) -> None:  # noqa: ARG002 -- hatchling's signature
        """Write the generated modules and add them to the build's artifacts."""
        root = Path(self.root)
        ir = load(root)
        if ir is None:
            return
        refused = bump_refusal(at_revision(root, 'HEAD'), ir)
        if refused:
            raise ValueError(refused)
        irpython.write(ir)
        artifacts = build_data.setdefault('artifacts', [])
        artifacts.extend(path.relative_to(root).as_posix() for path in irpython.expected_files(ir))


@hookimpl
def hatch_register_build_hook() -> type[IrSchemaBuildHook]:
    """Hatchling's plugin registration."""
    return IrSchemaBuildHook
