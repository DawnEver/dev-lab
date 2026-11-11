"""ONLY OUR OWN IS SWEPT, as the assertion every consumer runs: each shared-temp entry carries the family prefix.

A temp root is shared with every program on the machine, so :mod:`dev_lab.dev.tmpsweep` removes only the
entries :func:`dev_lab.dev.writeroots.owned_globs` names -- :data:`lab_commons.temp.TEMP_PREFIX` first (user
ruling 2026-11-11). An entry a repo creates WITHOUT it is never swept and piles up forever, so every
``tempfile`` call that lands in the shared temp dir passes ``prefix=TEMP_PREFIX`` or an f-string led by it.

WHAT LANDS IN THE SHARED TEMP DIR: a call to one of :data:`TEMP_CALLS` (as ``tempfile.X(...)`` or a bare
imported ``X(...)``) with no ``dir=``, ``dir=None``, or ``dir=`` read from the environment
(``os.environ.get('TMPDIR')`` is the shared dir whenever the variable is unset). A ``dir=`` naming any other
path is beside a declared target and needs no prefix.

THE REPO-SHAPED FACTS ARRIVE AS ARGUMENTS WITH NO DEFAULT: the trees to read and the measured floor of files
read. ``.claude/`` trees and archived code (:func:`dev_lab.dev.codeplace.is_archived`) are skipped.

WHAT THIS DOES NOT PROVE: a ``gettempdir()`` path a caller joins by hand is invisible to a call scan, and a
prefix held in a differently named variable reads as unowned -- the scan keys on the NAME ``TEMP_PREFIX``.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from dev_lab.dev import floors
from dev_lab.dev.codeplace import is_archived

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    'TEMP_CALLS',
    'assert_every_temp_entry_carries_the_prefix',
    'assert_the_scan_finds_a_planted_call',
    'unowned_temp_calls',
]

#: The ``tempfile`` constructors that create a named entry in a directory.
TEMP_CALLS: Final = frozenset({'mkdtemp', 'mkstemp', 'TemporaryDirectory', 'NamedTemporaryFile', 'TemporaryFile'})

_PREFIX_NAME: Final = 'TEMP_PREFIX'

#: The planted control: lines 2, 3, 4 and 7 are unowned; 5, 6 and 8 are not.
_PLANTED_SOURCE: Final = (
    'import tempfile, os\n'
    'tempfile.TemporaryDirectory()\n'
    "tempfile.mkdtemp(prefix='x-')\n"
    "NamedTemporaryFile(dir=os.environ.get('TMPDIR'))\n"
    'tempfile.mkdtemp(prefix=TEMP_PREFIX)\n'
    "TemporaryDirectory(prefix=f'{TEMP_PREFIX}y-', dir=None)\n"
    'tempfile.mkstemp(dir=None)\n'
    'tempfile.mkstemp(dir=here)\n'
)
_PLANTED_FOUND: Final = ['a.py:2', 'a.py:3', 'a.py:4', 'a.py:7']


def _called(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _shared_dir(where: ast.expr | None) -> bool:
    """Whether a ``dir=`` value leaves the entry in the shared temp dir: absent, ``None``, or an env read."""
    if where is None or (isinstance(where, ast.Constant) and where.value is None):
        return True
    if not isinstance(where, ast.Call):
        return False
    text = ast.unparse(where.func)
    return text.endswith(('environ.get', 'getenv'))


def _owned(prefix: ast.expr | None) -> bool:
    head = prefix.values[0] if isinstance(prefix, ast.JoinedStr) and prefix.values else prefix
    if isinstance(head, ast.FormattedValue):
        head = head.value
    return isinstance(head, ast.Name) and head.id == _PREFIX_NAME


def unowned_temp_calls(roots: Sequence[Path], *, base: Path) -> tuple[int, list[str]]:
    """The ``.py`` files read under *roots*, and each unowned shared-temp call as ``<rel-to-base>:<line>``."""
    files, found = 0, []
    for root in roots:
        for path in sorted(root.rglob('*.py')):
            rel = path.relative_to(base).as_posix()
            if '.claude' in path.relative_to(root).parts or is_archived(rel):
                continue
            files += 1
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not (isinstance(node, ast.Call) and _called(node) in TEMP_CALLS):
                    continue
                words = {kw.arg: kw.value for kw in node.keywords}
                if _shared_dir(words.get('dir')) and not _owned(words.get('prefix')):
                    found.append(f'{rel}:{node.lineno}')
    return files, found


def assert_every_temp_entry_carries_the_prefix(*, base: Path, roots: Sequence[Path], floor: int) -> None:
    """No call under *roots* creates an unprefixed shared-temp entry; at least *floor* files were read."""
    files, found = unowned_temp_calls(roots, base=base)
    floors.assert_floor(files, floor=floor, what='shared-temp prefix')
    if found:
        sites = '\n'.join(f'  {site}' for site in found)
        msg = (
            f'{len(found)} tempfile call(s) create a shared-temp entry WITHOUT the family prefix, so the sweep '
            f'never removes it. Pass prefix=TEMP_PREFIX (from lab_commons.temp), or an f-string led by it:\n{sites}'
        )
        raise AssertionError(msg)


def assert_the_scan_finds_a_planted_call(*, tmp_path: Path) -> None:
    """The planted control: the scan names exactly the unowned calls of :data:`_PLANTED_SOURCE`."""
    (tmp_path / 'a.py').write_text(_PLANTED_SOURCE, encoding='utf-8')
    files, found = unowned_temp_calls([tmp_path], base=tmp_path)
    if (files, found) != (1, _PLANTED_FOUND):
        msg = f'the planted control read {files} file(s) and named {found}; it must name exactly {_PLANTED_FOUND}'
        raise AssertionError(msg)
