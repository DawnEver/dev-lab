"""Every temp dir a TEST creates lives in the repo's dated tree -- ``<output>/<yy>/<mm>/<dd>/pytest/``.

User ruling D27 (2026-11-17): the dated log tree is the ONE managed output tree and is cleaned
periodically; there is no ``output/tmp`` and no system ``%TEMP%``. So pytest's base temp is a fresh
per-session directory under :func:`dev_lab.dev.datedlog.output_dir` ``(root, 'pytest')`` -- the ONE
function that computes the path -- and ``tmp_path`` / ``tmp_path_factory`` hand out pytest's own
numbered subdirectories beneath it. A test that wants a temp dir asks those fixtures, never
:mod:`tempfile`.

Loaded in every family repo by the ``pytest11`` shim :mod:`dev_lab.pytest_family`. There is NO
fallback to system temp (D27, no backward compatibility): a root that declares no output refuses
with the key it must declare, and an explicit ``--basetemp`` under the system temp dir is refused.
An xdist worker needs no branch: xdist always hands it a ``--basetemp`` below its controller's, and an
environment marker would mislead -- ``PYTEST_XDIST_WORKER`` is inherited by a pytest a worker's test spawns.

A SANDBOX INSIDE A CHECKOUT FINDS THAT CHECKOUT: a ``pytester`` tree under system temp had no
enclosing git repo, and under ``output/`` it would find the repo itself. So the output root is put in
``GIT_CEILING_DIRECTORIES`` for the session and its children: git run from a sandbox stops there, and
the test process itself, which runs from the checkout above it, is unaffected. pytest walks up the
same way for its rootdir and config, so :func:`bound_sandbox` gives every ``pytester`` sandbox an
empty ``.pytest.ini``: an inner run roots at its sandbox with no config, as it did under system temp.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path
from typing import Protocol

import pytest

from dev_lab.dev.datedlog import TEST_TEMP_KIND, UndeclaredOutput, declared_output, output_dir

__all__ = ['HOME_ENV', 'KIND', 'bound_sandbox', 'configure', 'session_basetemp']

#: The kind directory under the date that holds every test-created temp dir.
KIND = TEST_TEMP_KIND

_CEILING = 'GIT_CEILING_DIRECTORIES'

#: The dated test-temp dir the outermost session chose, exported so a nested pytest inherits it.
HOME_ENV = 'DEV_LAB_TEST_TEMP'


class _Option(Protocol):
    basetemp: str | os.PathLike[str] | None


class _Config(Protocol):
    option: _Option
    rootpath: Path


def session_basetemp(root: Path) -> Path:
    """A fresh ``<output>/<yy>/<mm>/<dd>/pytest/<HH-MM-SS>-<pid>/`` for one pytest session, created.

    The pid keeps two sessions started in the same second apart: pytest empties a given basetemp
    at start, so a shared one would wipe a concurrent run's files.

    A root declaring no output -- a test's sandbox, a pytest run spawned inside another session --
    takes the dated dir its enclosing session exported (:data:`HOME_ENV`): still the managed tree,
    never system temp. With neither, :class:`~dev_lab.dev.datedlog.UndeclaredOutput` is raised.
    """
    try:
        dated = output_dir(root, KIND)
    except UndeclaredOutput:
        inherited = os.environ.get(HOME_ENV)
        if not inherited:
            raise
        dated = Path(inherited)
    os.environ.setdefault(HOME_ENV, str(dated))
    stamp = dt.datetime.now().astimezone().strftime('%H-%M-%S')
    fresh = dated / f'{stamp}-{os.getpid()}'
    fresh.mkdir(parents=True)
    return fresh


def _under_system_temp(path: Path) -> bool:
    return Path(path).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())


def configure(config: _Config) -> None:
    """Point pytest's base temp at :func:`session_basetemp`, or refuse a system-temp one.

    Raises:
        pytest.UsageError: ``--basetemp`` lies under the system temp dir, or the root declares no
            output (the message names the key).

    """
    given = config.option.basetemp
    if given is not None:
        if _under_system_temp(Path(given)):
            msg = (
                f'--basetemp {given} is under the system temp dir; D27 puts every test-created temp '
                f"dir under the repo's <output>/<yy>/<mm>/<dd>/{KIND}/ -- drop --basetemp and "
                f'dev_lab.dev.testtemp chooses it.'
            )
            raise pytest.UsageError(msg)
        return
    root = Path(config.rootpath)
    try:
        config.option.basetemp = str(session_basetemp(root))
    except UndeclaredOutput as exc:
        msg = f"{exc}: pytest's base temp lives under it (dev_lab.dev.testtemp, D27)."
        raise pytest.UsageError(msg) from exc
    try:
        _cap_git_at(root / declared_output(root))
    except UndeclaredOutput:
        return  # an inheriting sandbox: the enclosing session already set its ceiling


def _cap_git_at(ceiling: Path) -> None:
    """Add *ceiling* to ``GIT_CEILING_DIRECTORIES`` so a sandbox below it never finds the checkout."""
    held = [entry for entry in os.environ.get(_CEILING, '').split(os.pathsep) if entry]
    if str(ceiling) not in held:
        os.environ[_CEILING] = os.pathsep.join([*held, str(ceiling)])


class _Sandbox(Protocol):
    path: Path


def bound_sandbox(pytester: _Sandbox) -> None:
    """Write an empty ``.pytest.ini`` into *pytester*'s sandbox so an inner run stops its upward search there."""
    (pytester.path / '.pytest.ini').write_text('', encoding='utf-8')
