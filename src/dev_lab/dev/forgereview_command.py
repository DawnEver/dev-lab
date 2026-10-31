"""The host side of the declared review command: whether this host can start it, and running it.

:mod:`dev_lab.dev.forgereview` reads the outcome: a host that cannot (:class:`ReviewUnsupported`) posts
``HOST_UNABLE`` and leaves the head claimable; a refusal (:class:`ReviewRefused`) is the head's own ``error``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = ['REFUSED_EXIT', 'ReviewRefused', 'ReviewUnsupported', 'Runner', 'can_start', 'run_command']

#: The exit a review command REFUSES with (a bad method, version or range): empty stdout, the reason on stderr.
REFUSED_EXIT: Final = 2

_PROBE: Final = 'import importlib.util, sys; sys.exit(importlib.util.find_spec(sys.argv[1]) is None)'
_MISSING_MODULE: Final = 'No module named'  # what `python -m <absent>` says
_USAGE_ERROR: Final = 'error: unrecognized arguments'  # argparse's exit 2: the command does not speak this interface
_COMMAND_TIMEOUT_S: Final = 1800


class ReviewRefused(OSError):
    """The review command refused the request (exit :data:`REFUSED_EXIT`), naming why on stderr."""


class ReviewUnsupported(OSError):
    """The host cannot run the declared command at all (absent, a module missing, a capability undeclared).

    Like every failure it posts ``error`` naming why.
    """


def can_start(argv: Sequence[str], root: Path) -> str | None:
    """Why this host cannot start *argv* (its executable absent, or its ``-m`` module unimportable); ``None`` if it can.

    Checked BEFORE a claim is posted; the reason becomes the ``error`` status.
    """
    found = shutil.which(argv[0]) or (argv[0] if Path(argv[0]).is_file() else None)
    if found is None:
        return f'unsupported: the review command {argv[0]!r} is not installed on this host'
    match argv:
        case [_, '-m', module, *_]:
            probe = _door.run([found, '-c', _PROBE, module], cwd=root, capture_output=True, timeout=120, check=False)
            if probe.returncode != 0:
                return f'unsupported: the review command cannot import {module!r} on this host'
    return None


def run_command(argv: Sequence[str], root: Path) -> str:
    """The stdout of the declared command run in *root*; :class:`ReviewRefused` or :class:`OSError` on a failure."""
    try:
        done = _door.run(
            list(argv), cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=_COMMAND_TIMEOUT_S, check=False,
        )  # fmt: skip
    except FileNotFoundError:
        msg = f'unsupported: the review command {argv[0]!r} is not installed on this host'
        raise ReviewUnsupported(msg) from None
    why = done.stderr.strip()[-300:]
    if done.returncode != 0 and _MISSING_MODULE in done.stderr:
        msg = f'unsupported: the review command cannot import its module on this host ({why})'
        raise ReviewUnsupported(msg)
    if done.returncode == REFUSED_EXIT and _USAGE_ERROR in done.stderr:  # an older command on THIS host, not the head
        msg = f'unsupported: the review command on this host does not take these arguments ({why})'
        raise ReviewUnsupported(msg)
    if done.returncode == REFUSED_EXIT:
        msg = f'the review command refused: {why}'
        raise ReviewRefused(msg)
    if done.returncode != 0:
        msg = f'the review command exited {done.returncode}: {why}'
        raise OSError(msg)
    return done.stdout


@dataclass(frozen=True)
class Runner:
    """How one host runs the review command: its name, its ``[runtimes]``, the run and start probes, its clock."""

    host: str
    runtimes: Mapping[str, Mapping[str, Any]] = MappingProxyType({})  # this host's: none by default
    run: Callable[[Sequence[str], Path], str] = run_command
    ready: Callable[[Sequence[str], Path], str | None] = can_start
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    #: Whether the review command's secret is present; absent (a fork PR's job) holds the head for a maintainer.
    secret: bool = True
    #: Whether this is the ``forge serve`` process: its rounds are the forge's ruling (:func:`identity`).
    serving: bool = False
