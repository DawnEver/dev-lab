"""How the dependency door SPELLS an install: its two declared axes and the one argv, by what the target can run.

A uv-created venv has no pip (uv seeds none), so the door's install goes through ``uv pip install --python`` there;
this module answers which of the two spellings a given interpreter can take, and builds it (moved here from
:mod:`dev_lab.dev.dep`, 2026-11-25, MODULE-SIZE-ALARM).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from enum import Enum
from typing import TYPE_CHECKING

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['Mode', 'Version', 'has_pip', 'pip_argv']


class Mode(Enum):
    """How the change is allowed to reach the index.

    ``RESOLVE`` is the default because a dependency change that cannot resolve is not a dependency
    change. ``PINNED`` is the narrow mode whose subject is a LOCAL artifact -- there ``--no-index``
    makes "no network, no version resolution" a mechanical fact rather than a promise in a docstring.
    """

    RESOLVE = 'resolve'
    PINNED = 'pinned'


class Version(Enum):
    """Whether the artifact's VERSION is an IDENTITY for the bytes being installed.

    THIS IS A SECOND AXIS AND NOT A SHADE OF :class:`Mode`, and conflating the two is what hid the
    defect. ``Mode`` says how the change may reach an index; this says whether pip's
    already-satisfied shortcut is a correct answer for this artifact. They are independent: a pinned
    install of a third party's wheel is genuinely already satisfied, and a resolving install of a
    package whose version repeats would be just as blind.

    ``IDENTIFIES`` is the default and describes every published distribution: two builds carrying one
    version are the same bytes by the publisher's promise, so skipping is right and forcing would
    reinstall for nothing on every call.

    ``REPEATS`` is the case where that promise does not exist -- a package with
    ``dynamic = ["version"]`` reading its number out of a ``Cargo.toml``, rebuilt from a checkout
    whose SOURCE moved while the number did not. MEASURED against the pip this family ships against
    (26.2.1, ``_internal/resolution/resolvelib/resolver.py``): for a LOCAL WHEEL already installed at
    the same version pip logs "is already installed with the same version as the provided wheel. Use
    --force-reinstall to force an installation of the wheel" and ``continue``s -- and then EXITS
    ZERO. So the caller is told the install succeeded, the environment did not move, and ``env_key``
    truthfully agrees that it did not: a no-op that every instrument here reports as a success. Note
    the narrowness pip's own code shows -- a local sdist or directory DOES reinstall -- so this is a
    wheel-shaped hazard specifically, which is exactly what a self-build installs.
    """

    IDENTIFIES = 'identifies'
    REPEATS = 'repeats'


def has_pip(python: str) -> bool:
    """Whether *python* can run ``-m pip``. A uv-created venv cannot: uv seeds no pip into it.

    The invoking interpreter is answered in-process; any other is asked, because a venv's packages
    are a fact about THAT interpreter and not about this one.
    """
    if python == sys.executable:
        return importlib.util.find_spec('pip') is not None
    try:
        done = _door.run([python, '-c', 'import pip'], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def pip_argv(
    requirements: Sequence[str],
    *,
    mode: Mode = Mode.RESOLVE,
    version: Version = Version.IDENTIFIES,
    python: str | None = None,
    pip: Callable[[str], bool] = has_pip,
    uv: str | None = None,
) -> tuple[str, ...]:
    """The command that performs the change, into the explicit TARGET interpreter's environment.

    ``sys.executable -m pip`` rather than a bare ``pip`` on ``PATH``: the door's whole claim is about
    the environment it measured, and a ``pip`` resolved from ``PATH`` can belong to a different one.
    WHEN THAT INTERPRETER HAS NO PIP -- every uv-created venv -- the same install goes through
    ``uv pip install --python <that interpreter>``, which targets the same environment by name; *uv*
    is the uv binary (default: found on ``PATH``). With neither, the pip spelling is returned and
    fails loudly, which is the honest report of an environment nothing here can install into.

    THIS IS THE ONE PLACE THE ARGV IS DECIDED, and every flag is derived from a DECLARED enum member
    rather than from a caller's opinion -- which is what makes :attr:`Report.argv` able to be the
    whole truth. A caller that wants a flag declares the FACT that implies it; there is no free-text
    extras parameter, because an argv assembled in two places cannot be reported from one.
    """
    target = python or sys.executable
    flags = ('--no-index', '--no-deps') if mode is Mode.PINNED else ()
    uv_binary = None if pip(target) else uv or shutil.which('uv')
    if uv_binary is not None:
        forced = ('--reinstall',) if version is Version.REPEATS else ()
        return (uv_binary, 'pip', 'install', '--python', target, *flags, *forced, *requirements)
    forced = ('--force-reinstall',) if version is Version.REPEATS else ()
    return (target, '-m', 'pip', 'install', *flags, *forced, *requirements)
