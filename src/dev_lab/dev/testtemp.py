"""Every temp dir a TEST creates is an OWNED entry of the system temp dir -- ``<temp>/<TEMP_PREFIX><kind>-<random>/``.

User ruling D104 (2026-11-20) supersedes D27: a test's temp dir holds planted code, configs and checkouts, and
OUTPUT-HOLDS-NO-CODE has no exception, so it never lives under ``output/``. Its one declared place is the system
temp dir, as a direct entry named :data:`lab_commons.temp.TEMP_PREFIX` + kind: :mod:`dev_lab.dev.tmpsweep` owns
that prefix and ages such an entry out once every file in it is older than its age, and a live run (fresh files) is
never touched. THE SWEEP IS THE BACKSTOP, NEVER THE PLAN: a host that never runs it kept 149 pytest entries
(6.6 GB) and 85 script entries (user report 2026-11-24), so every entry made here is reclaimed by the run that
made it (:func:`release`, :func:`script_temp_env`), and only a failed run's evidence is left for the sweep.
``mkdtemp`` makes each one unique, so two sessions never share one. Being outside every checkout, a sandbox there
finds no enclosing repo.

* pytest: :func:`configure` points ``--basetemp`` at a fresh entry of kind :data:`KIND`; ``tmp_path`` and
  ``tmp_path_factory`` hand out pytest's own numbered subdirectories beneath it. :func:`release` removes that
  entry when the session ends: always after a pass, and after a failure too when ``tmp_path_retention_policy``
  is ``none`` (pytest's own ini key; ``all`` and ``failed`` keep a FAILED run's dirs as evidence). An explicit
  ``--basetemp`` under an output tree is refused naming OUTPUT-HOLDS-NO-CODE; any other is kept. An xdist worker
  needs no branch: xdist always hands it a ``--basetemp`` below its controller's.
* a script suite (``node --test``, ``npm test``): :func:`script_temp_env` points TMPDIR, TEMP and TMP at a fresh
  entry of kind :data:`SCRIPT_KIND` for the length of its ``with`` block, and removes it after.

:func:`bound_sandbox` gives every ``pytester`` sandbox an empty ``.pytest.ini``, so an inner run roots at its
sandbox and never reads a config some ancestor of the temp dir happens to hold.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.datedlog import UndeclaredOutput, declared_output

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

__all__ = ['KIND', 'SCRIPT_KIND', 'bound_sandbox', 'configure', 'fresh_temp', 'reclaim', 'release', 'script_temp_env']

#: The kind in a pytest session's base temp entry name.
KIND: Final = 'pytest'
#: The kind in a script suite's temp entry name.
SCRIPT_KIND: Final = 'scripttest'

_OUTPUT_SEGMENT: Final = 'output'
#: The ``tmp_path_retention_policy`` value under which even a failed run's entry is removed.
_KEEP_NOTHING: Final = 'none'


class _Option(Protocol):
    basetemp: str | os.PathLike[str] | None


class _Config(Protocol):
    option: _Option
    rootpath: Path


def fresh_temp(kind: str) -> Path:
    """A fresh, empty, swept-by-prefix directory directly under the system temp dir, for one run of *kind*."""
    return Path(tempfile.mkdtemp(prefix=f'{TEMP_PREFIX}{kind}-'))


def _writable(function: Callable[[str], object], path: str, _error: BaseException) -> None:
    """``rmtree``'s retry for a read-only file (a git object on Windows): clear the bit, run the removal again."""
    Path(path).chmod(stat.S_IWRITE)
    function(path)


def reclaim(path: Path) -> None:
    """Remove *path*'s tree, links and junctions unlinked rather than followed; what a live handle holds stays.

    A held leftover is the age sweep's (:mod:`dev_lab.dev.tmpsweep`): a removal never fails the run it ends.
    """
    try:
        shutil.rmtree(path, onexc=_writable)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)


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


def configure(config: _Config) -> Path | None:
    """Point pytest's base temp at a :func:`fresh_temp` entry, or refuse a ``--basetemp`` under an output tree.

    Returns:
        The entry made here, for :func:`release` to reclaim; ``None`` when the run was handed its ``--basetemp``
        (an xdist worker, a ``pytester`` run, a caller's choice), which is never ours to remove.

    Raises:
        pytest.UsageError: ``--basetemp`` lies under an output tree (OUTPUT-HOLDS-NO-CODE).

    """
    given = config.option.basetemp
    if given is None:
        made = fresh_temp(KIND)
        config.option.basetemp = str(made)
        return made
    if _under_output(Path(config.rootpath), Path(given)):
        import pytest  # noqa: PLC0415 -- a script suite imports this module without pytest installed

        msg = (
            f'--basetemp {given} is under an output tree: OUTPUT-HOLDS-NO-CODE (D104) -- a test temp dir holds '
            f'planted code. Drop --basetemp and dev_lab.dev.testtemp chooses a swept system-temp entry.'
        )
        raise pytest.UsageError(msg)
    return None


def release(made: Path | None, *, passed: bool, policy: str) -> None:
    """Reclaim the entry :func:`configure` *made*: after a pass always, after a failure when *policy* is ``none``."""
    if made is not None and (passed or policy == _KEEP_NOTHING):
        reclaim(made)


@contextmanager
def script_temp_env(environ: Mapping[str, str]) -> Iterator[dict[str, str]]:
    """*environ* with TMPDIR, TEMP and TMP all naming one :func:`fresh_temp` entry of kind :data:`SCRIPT_KIND`.

    ``os.tmpdir()`` reads TMPDIR on POSIX and TEMP/TMP on Windows, so every ``mkdtemp`` a JS test makes lands in
    the entry, and the entry is reclaimed when the block ends, however it ends.
    """
    temp = fresh_temp(SCRIPT_KIND)
    try:
        yield dict(environ) | dict.fromkeys(('TMPDIR', 'TEMP', 'TMP'), str(temp))
    finally:
        reclaim(temp)


class _Sandbox(Protocol):
    path: Path


def bound_sandbox(pytester: _Sandbox) -> None:
    """Write an empty ``.pytest.ini`` into *pytester*'s sandbox so an inner run stops its upward search there."""
    (pytester.path / '.pytest.ini').write_text('', encoding='utf-8')
