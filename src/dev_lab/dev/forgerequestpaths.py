"""A TESTS request's named files read at its sha: the test roots, the blobs, each path's refusal, its placement.

Split from :mod:`dev_lab.dev.forgerequest` (the module-size band): the reading :func:`~dev_lab.dev.forgerequest.
declared_request` does for its built-in ``tests`` producer (D5). It knows nothing of a request; a refusal is a
string or a :class:`ValueError` the caller turns into one.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev._testfacts_readers import mark_names
from dev_lab.dev.forge import _GIT

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ['JMAG', 'LINUX', 'NOT_A_PATH', 'WINDOWS', 'blobs', 'path_refusal', 'placement', 'test_roots']

#: The OS every test Linux can run is placed on, and the one tool a Windows host serves a selection for.
LINUX: Final = 'linux'
WINDOWS: Final = 'windows'
JMAG: Final = 'jmag'

#: Characters a test path never carries: a glob, or a quote/space that would make it more than one path.
NOT_A_PATH: Final = frozenset('*?[]{}"\' \t\r\n')


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
    """
    if not paths:
        return {}
    asked = ''.join(f'{sha}:{path}\n' for path in paths).encode()
    done = _door.run([_GIT, '-C', str(root), 'cat-file', '--batch'], input=asked, capture_output=True,
                     check=False, timeout=60)  # fmt: skip
    found: dict[str, bytes] = {}
    out, at = done.stdout, 0
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
    return found


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
