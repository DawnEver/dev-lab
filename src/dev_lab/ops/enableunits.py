"""``install`` enables the units it rendered (issue #557); every other live step stays the operator's.

``install`` runs as root through the ops account's one fixed sudo line, and the units it renders come from a
config that only a consented ``config apply`` changes -- so enabling exactly those units grants nothing the consent
did not. A rendered timer left disabled is a lie the next reboot exposes (the follow timer, 2026-11-14). Creating
accounts, installing packages and reloading sshd change WHO may log in and WHAT runs as whom, so they stay printed
steps an operator runs on purpose.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Final

__all__ = ['enable', 'split']

_ENABLE: Final = 'systemctl enable --now '
_RELOAD: Final = 'systemctl daemon-reload'

Runner = Callable[[list[str]], int]


def split(steps: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The units *steps* enable, and the steps left for the operator (a bare daemon-reload is install's own)."""
    units = tuple(step.removeprefix(_ENABLE) for step in steps if step.startswith(_ENABLE))
    rest = tuple(step for step in steps if not step.startswith(_ENABLE) and step != _RELOAD)
    return units, rest


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def enable(units: Sequence[str], *, run: Runner = _run) -> tuple[str, ...]:
    """Reload systemd once, then ``enable --now`` each unit (idempotent); the units that did not enable."""
    if not units:
        return ()
    run(['systemctl', 'daemon-reload'])
    return tuple(unit for unit in units if run(['systemctl', 'enable', '--now', unit]) != 0)
