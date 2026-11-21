"""Where each declared vendor is installed on THIS machine: the newest directory its family patterns match.

Split from :mod:`dev_lab.dev.devhost`, whose ``detect`` verb is :func:`report`: the host-file lines to paste.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev import familyrepos
from dev_lab.dev._machinefile import render_value

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['detect', 'report']


def _matches(pattern: str) -> list[Path]:
    anchored = Path(pattern)
    return list(Path(anchored.anchor).glob(str(anchored.relative_to(anchored.anchor))))


def detect(patterns: Mapping[str, list[str]]) -> dict[str, str]:
    """Each vendor's install home on THIS machine: the last (newest-named) directory its patterns match."""
    found = {}
    for name, globs in patterns.items():
        hits = sorted({hit for pattern in globs for hit in _matches(pattern) if hit.is_dir()})
        if hits:
            found[name] = hits[-1].as_posix()
    return found


def report(source: Path | None) -> int:
    """Print the ``[dev.vendors.<name>] home`` lines for *source*'s ``family.toml`` patterns; 2 with no source."""
    if source is None:
        emit(
            "refused: detect needs --from <the config source's checkout> (no [devhost] in the machine file): "
            'clone the config source as a family repo and set its path -- ' + familyrepos.SET_DOOR,
            err=True,
        )
        return 2
    family = tomllib.loads((source / 'family.toml').read_text(encoding='utf-8'))
    homes = detect(family.get('dev', {}).get('detect', {}))
    for name, home in homes.items():
        emit(f'[dev.vendors.{name}]\nhome = {render_value(home)}\n')
    if not homes:
        emit('no declared vendor pattern matched on this machine')
    return 0
