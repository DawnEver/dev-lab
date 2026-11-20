"""Every temp dir a TEST creates is an OWNED entry of the system temp dir -- ``<temp>/<TEMP_PREFIX><kind>-<random>/``.

User ruling D104 (2026-11-20) supersedes D27: a test's temp dir holds planted code, configs and checkouts, and
OUTPUT-HOLDS-NO-CODE has no exception, so it never lives under ``output/``. Its one declared place is the system
temp dir, as a direct entry named :data:`lab_commons.temp.TEMP_PREFIX` + kind: :mod:`dev_lab.dev.tmpsweep` owns
that prefix and ages such an entry out once every file in it is older than its age, so the place is cleaned and
bounded by the existing sweep, and a live run (fresh files) is never touched. ``mkdtemp`` makes each one unique,
so two sessions never share one. Being outside every checkout, a sandbox there finds no enclosing repo.

* pytest: :func:`configure` points ``--basetemp`` at a fresh entry of kind :data:`KIND`; ``tmp_path`` and
  ``tmp_path_factory`` hand out pytest's own numbered subdirectories beneath it. An explicit ``--basetemp``
  under an output tree is refused naming OUTPUT-HOLDS-NO-CODE; any other is kept. An xdist worker needs no
  branch: xdist always hands it a ``--basetemp`` below its controller's.
* a script suite (``node --test``, ``npm test``): :func:`script_temp_env` points TMPDIR, TEMP and TMP at a fresh
  entry of kind :data:`SCRIPT_KIND`.

:func:`bound_sandbox` gives every ``pytester`` sandbox an empty ``.pytest.ini``, so an inner run roots at its
sandbox and never reads a config some ancestor of the temp dir happens to hold.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.datedlog import UndeclaredOutput, declared_output

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['KIND', 'SCRIPT_KIND', 'bound_sandbox', 'configure', 'fresh_temp', 'script_temp_env']

#: The kind in a pytest session's base temp entry name.
KIND: Final = 'pytest'
#: The kind in a script suite's temp entry name.
SCRIPT_KIND: Final = 'scripttest'

_OUTPUT_SEGMENT: Final = 'output'


class _Option(Protocol):
    basetemp: str | os.PathLike[str] | None


class _Config(Protocol):
    option: _Option
    rootpath: Path


def fresh_temp(kind: str) -> Path:
    """A fresh, empty, swept-by-prefix directory directly under the system temp dir, for one run of *kind*."""
    return Path(tempfile.mkdtemp(prefix=f'{TEMP_PREFIX}{kind}-'))


def _under_output(root: Path, path: Path) -> bool:
    """Whether *path* lies in an output tree: any ``output`` segment, or below *root*'s declared output."""
    resolved = path.resolve()
    if _OUTPUT_SEGMENT in resolved.parts:
        return True
    try:
        declared = (root / declared_output(root)).resolve()
    except UndeclaredOutput:
        return False
    return resolved.is_relative_to(declared)


def configure(config: _Config) -> None:
    """Point pytest's base temp at a :func:`fresh_temp` entry, or refuse a ``--basetemp`` under an output tree.

    Raises:
        pytest.UsageError: ``--basetemp`` lies under an output tree (OUTPUT-HOLDS-NO-CODE).

    """
    given = config.option.basetemp
    if given is None:
        config.option.basetemp = str(fresh_temp(KIND))
        return
    if _under_output(Path(config.rootpath), Path(given)):
        import pytest  # noqa: PLC0415 -- a script suite imports this module without pytest installed

        msg = (
            f'--basetemp {given} is under an output tree: OUTPUT-HOLDS-NO-CODE (D104) -- a test temp dir holds '
            f'planted code. Drop --basetemp and dev_lab.dev.testtemp chooses a swept system-temp entry.'
        )
        raise pytest.UsageError(msg)


def script_temp_env(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* with TMPDIR, TEMP and TMP all naming one :func:`fresh_temp` entry of kind :data:`SCRIPT_KIND`.

    ``os.tmpdir()`` reads TMPDIR on POSIX and TEMP/TMP on Windows, so every ``mkdtemp`` a JS test makes lands in
    the swept entry.
    """
    return dict(environ) | dict.fromkeys(('TMPDIR', 'TEMP', 'TMP'), str(fresh_temp(SCRIPT_KIND)))


class _Sandbox(Protocol):
    path: Path


def bound_sandbox(pytester: _Sandbox) -> None:
    """Write an empty ``.pytest.ini`` into *pytester*'s sandbox so an inner run stops its upward search there."""
    (pytester.path / '.pytest.ini').write_text('', encoding='utf-8')
