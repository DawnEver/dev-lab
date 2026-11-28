"""A USABLE cargo, as the Rust-building tests need one: on PATH AND able to run.

A rustup shim with no default toolchain is on PATH and runs nothing (``rustup could not choose a version of cargo
to run ... no default is configured``), so ``shutil.which('cargo')`` alone sent the build into an assertion rather
than the tests' own "no cargo" xfail. Both shapes are one fact -- this host cannot build the Rust half -- and the
reason says which.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Callable

#: Seconds ``cargo --version`` may take: a shim answers at once, or a rustup self-update is not this probe's to wait.
_PROBE_WALL_S = 60


def usable_cargo(
    *, which: Callable[[str], str | None] = shutil.which, run: Callable[..., Any] = _door.run
) -> tuple[str | None, str]:
    """``(cargo, '')`` when the cargo on PATH runs; ``(None, why)`` naming whether it is absent or cannot run."""
    cargo = which('cargo')
    if cargo is None:
        return None, 'no cargo on PATH'
    try:
        done = run(
            [cargo, '--version'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=_PROBE_WALL_S,
        )
    except (subprocess.SubprocessError, OSError) as error:
        return None, f'{cargo} cannot start: {error}'
    if done.returncode != 0:
        said = next((line.strip() for line in (done.stderr or done.stdout or '').splitlines() if line.strip()), '')
        return None, f'{cargo} cannot run: {said or f"exit {done.returncode}"}'
    return cargo, ''
