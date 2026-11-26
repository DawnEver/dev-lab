"""A repo's DELTAS module, loaded from its file: the declared deltas its family files render over their bases.

A repo names the module in ``[tool.dev_lab.render] deltas`` (:mod:`dev_lab.dev.famfiles`); it is a file of the
repo, not an importable package, so it is loaded from its path.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from dev_lab.dev.famconfig import Delta

__all__ = ['load_deltas']


def load_deltas(path: Path) -> Mapping[str, Delta]:
    """The ``DELTAS`` mapping a repo declares, read from the module file at *path* (its own convention)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        msg = f'cannot load a module from {path}'
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(path.stem, module)
    spec.loader.exec_module(module)
    return module.DELTAS
