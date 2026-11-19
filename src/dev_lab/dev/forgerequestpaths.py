"""A TESTS request's named files read at its sha: the test roots, the blobs, each path's refusal, its placement.

Split from :mod:`dev_lab.dev.forgerequest` (the module-size band): the reading :func:`~dev_lab.dev.forgerequest.
declared_request` does for its built-in ``tests`` producer (D5). It knows nothing of a request; a refusal is a
string or a :class:`ValueError` the caller turns into one.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev._testfacts_readers import mark_names
from dev_lab.dev.forge import _GIT

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ['JMAG', 'LINUX', 'NOT_A_PATH', 'WINDOWS', 'blobs', 'path_refusal', 'placement', 'prefetch', 'test_roots']

#: The OS every test Linux can run is placed on, and the one tool a Windows host serves a selection for.
LINUX: Final = 'linux'
WINDOWS: Final = 'windows'
JMAG: Final = 'jmag'

#: Characters a test path never carries: a glob, or a quote/space that would make it more than one path.
NOT_A_PATH: Final = frozenset('*?[]{}"\' \t\r\n')

#: A FULL commit id (sha-1 or sha-256): what it names never changes, so :func:`blobs` holds its reads.
_COMMIT_ID: Final = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')
_HELD: dict[tuple[str, str, tuple[str, ...]], dict[str, bytes]] = {}


def placement(sources: Mapping[str, bytes], sha: str, resources: Sequence[str]) -> frozenset[str]:
    """The need-set a selection's *sources* at *sha* run under: ``{linux}``, or its markers plus ``windows``.

    Each file's ``pytest.mark.<name>`` spellings among the declared *resources* are read from its source at
    *sha*, as :func:`blobs` read it (a mark a conftest applies by directory is not seen). A selection holding
    a ``jmag`` test runs on Windows with every resource its files name; one naming no resource but ``linux``
    runs on Linux; any other resource is refused (Linux cannot run it, and Windows serves a selection only
    for ``jmag``).

    Raises:
        ValueError: a file is unreadable at *sha*, or the selection names a resource no placement serves.

    """
    marks: set[str] = set()
    for path, source in sources.items():
        try:
            marks |= set(mark_names(ast.parse(source))) & set(resources)
        except (SyntaxError, ValueError) as why:
            msg = f'{path!r} at {sha[:12]} is unreadable as Python: {why}'
            raise ValueError(msg) from why
    if JMAG in marks:
        return frozenset(marks | {WINDOWS})
    if beyond := sorted(marks - {LINUX}):
        msg = (
            f'the selection needs {beyond}: Linux cannot run it and a Windows host serves a selection only for '
            f'{JMAG!r} tests -- run it where that resource is'
        )
        raise ValueError(msg)
    return frozenset({LINUX})


def test_roots(text: str) -> tuple[str, ...]:
    """The ``[tool.pytest.ini_options] testpaths`` *text* declares, slash-trimmed; ``()`` for none."""
    roots = tomllib.loads(text).get('tool', {}).get('pytest', {}).get('ini_options', {}).get('testpaths')
    return tuple(str(one).strip('/') for one in roots) if isinstance(roots, list) and roots else ()


def blobs(root: Path, sha: str, paths: Sequence[str]) -> dict[str, bytes]:
    """The contents of each of *paths* that is a file at *sha*, read by ONE ``git cat-file --batch``.

    One child for the whole selection, never one per file: per-file reads cost ``forge queue`` ~0.1 s each on
    Windows, 1,033 children and ~120 s of a 170 s read (measured 2026-11-13). A path that is absent or names
    a tree is left out. *paths* never hold a line break (:data:`NOT_A_PATH` refuses one first).

    A FULL commit id names content that never changes, so its answer is held for the process (a ref name can move
    and is never held); :func:`prefetch` fills it for many selections in one child.
    """
    if not paths:
        return {}
    key = (str(root), sha, tuple(paths))
    if key in _HELD:
        return dict(_HELD[key])
    return dict(_read(root, [(sha, tuple(paths))])[key])


def prefetch(root: Path, asks: Sequence[tuple[str, Sequence[str]]]) -> None:
    """Read every (sha, paths) of *asks* by ONE ``git cat-file --batch`` and hold each answer for :func:`blobs`.

    ``forge queue`` declares every request issue: one child per request was 59 children of a 218-child read
    (2026-11-18); one child serves them all.
    """
    _read(root, [(sha, tuple(paths)) for sha, paths in asks if paths and (str(root), sha, tuple(paths)) not in _HELD])


def _read(root: Path, wanted: Sequence[tuple[str, tuple[str, ...]]]) -> dict[tuple[str, str, tuple[str, ...]], dict]:
    """Each (sha, paths) of *wanted*, read by one child; a clean read of a full commit id is held.

    A child that exits non-zero (a path git refuses, e.g. one leaving the repository) is still parsed as far as
    it answered, as one read always was, but holds nothing.
    """
    read: dict[tuple[str, str, tuple[str, ...]], dict] = {(str(root), sha, paths): {} for sha, paths in wanted}
    if not wanted:
        return read
    asked = ''.join(f'{sha}:{path}\n' for sha, paths in wanted for path in paths).encode()
    done = _door.run([_GIT, '-C', str(root), 'cat-file', '--batch'], input=asked, capture_output=True,
                     check=False, timeout=60 * len(wanted))  # fmt: skip
    out, at = done.stdout, 0
    for sha, paths in wanted:
        found: dict[str, bytes] = {}
        for path in paths:  # each answer: ``<oid> <type> <size>\n<content>\n``, or ``<object> missing\n``
            end = out.find(b'\n', at)
            if end < 0:
                break
            header, at = out[at:end].split(), end + 1
            if header[-1:] == [b'missing']:
                continue
            size = int(header[-1])
            if header[1] == b'blob':
                found[path] = out[at : at + size]
            at += size + 1
        read[(str(root), sha, paths)] = found
        if done.returncode == 0 and _COMMIT_ID.fullmatch(sha):
            _HELD[(str(root), sha, paths)] = found
    return read


def path_refusal(path: str, roots: Sequence[str], files: Mapping[str, bytes], sha: str) -> str:
    """Why *path* is not a test file at *sha* under *roots*; ``''`` when it is. *files*: :func:`blobs` at *sha*."""
    pure = PurePosixPath(path)
    if not path or path.startswith('-'):
        return f'{path!r} looks like an option, not a test file'
    if NOT_A_PATH & set(path):
        return f'{path!r} is a glob or more than one path: name each test file'
    if pure.is_absolute() or '..' in pure.parts or '\\' in path:
        return f'{path!r} leaves the repository'
    if not any(pure.parts[: len(PurePosixPath(r).parts)] == PurePosixPath(r).parts for r in roots):
        return f'{path!r} is outside the declared test roots {list(roots)}'
    if pure.suffix != '.py':
        return f'{path!r} is not a test file (.py)'
    return '' if path in files else f'{path!r} does not exist at {sha[:12]}'
