"""Where another account's machine home and machine file sit, as lab-commons lays them out with no override set.

One reading for every caller that names a path on ANOTHER account (a cluster account a deploy reaches, the judge's
HOME a host install renders into): the layout is lab-commons' (:func:`lab_commons.home.home`,
:func:`lab_commons.home.config_path`), read once with the machine-home and config overrides unset, so this
process's own overrides never leak into a path on someone else's account.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from lab_commons import home as _home
from lab_commons.config import CONFIG_ENV

__all__ = ['default_layout']


def default_layout() -> tuple[str, str]:
    """``(machine home under $HOME, machine file under the machine home)``, POSIX-spelled, overrides unset."""
    saved = {name: os.environ.pop(name) for name in (_home.HOME_ENV, CONFIG_ENV) if name in os.environ}
    try:
        machine_home = _home.home().relative_to(Path.home())
        under = _home.config_path().relative_to(_home.home())
    finally:
        os.environ.update(saved)
    return PurePosixPath(*machine_home.parts).as_posix(), PurePosixPath(*under.parts).as_posix()
