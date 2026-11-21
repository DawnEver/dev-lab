"""The config source's forge URL: the ``origin`` of the clone this machine file's ``[devhost]`` names.

Split from :mod:`dev_lab.dev.devhost` (which renders FROM that clone): this reads where the clone's forge is, for the
doors that fetch the config source elsewhere (``deploy-fleet``, ``plan run``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lab_commons import config as machineconfig

from dev_lab.dev.checkout import git_out
from dev_lab.dev.devdeclared import OWN_TABLE

__all__ = ['config_source']


def config_source(live: Mapping[str, Any] | None = None) -> str:
    """The config source's forge URL: the ``origin`` of the clone the machine file's ``[devhost]`` names.

    Raises:
        ValueError: the machine file is not a render (no ``[devhost] source``), the source is relative (it would
            follow the CWD to another clone, #556), or that clone has no ``origin``.

    """
    own = (machineconfig.machine() if live is None else live).get(OWN_TABLE, {})
    if not own.get('source'):
        msg = f'the machine file has no [{OWN_TABLE}] source: render it (devhost render --host NAME --from CLONE)'
        raise ValueError(msg)
    if not Path(own['source']).is_absolute():
        msg = (f"the machine file's [{OWN_TABLE}] source {own['source']!r} is relative, so it would resolve against "
               f"the current directory and read another clone's origin: re-render it with an absolute clone -- "
               f"devhost render --host {own.get('host') or 'NAME'} --from <absolute clone> --write")  # fmt: skip
        raise ValueError(msg)
    url = git_out(Path(own['source']), 'remote', 'get-url', 'origin')
    if not url:
        msg = f'{own["source"]} has no origin remote: the config source is unknown here'
        raise ValueError(msg)
    return url.strip()
