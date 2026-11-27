"""How a relock reads ``uv.lock`` and a resolution's change lines: which siblings FLOAT, and what a change moves.

:mod:`dev_lab.dev.relock` carries the rolling relock; this is its lock reading, shared with
:mod:`dev_lab.dev.locklag`. A git source FOLLOWS a line unless it names a tag, a full commit sha, or an
abbreviation of the commit the lock resolved (:func:`line_of`); :func:`floated` lists the followers.
"""

from __future__ import annotations

import re
import tomllib
from typing import Final, NamedTuple
from urllib.parse import parse_qs

from dev_lab.dev.lockcheck import TOOLCHAIN, UV_PIN

__all__ = ['DEFAULT_LINE', 'Floated', 'canon', 'dist_of', 'floated', 'in_house', 'line_of']

#: The line a floated sibling follows when its git source names no ``branch``.
DEFAULT_LINE: Final = 'integrate/main'
#: The verbs a resolution's change line opens with, and where the distribution sits after one.
_VERBS: Final = frozenset({'Update', 'Add', 'Remove'})
_NAME_INDEX: Final = 2
#: A full commit sha: the one ``rev`` that names a commit rather than a line.
_FULL_SHA: Final = re.compile(r'[0-9a-f]{40}')
#: An abbreviated commit sha: git's shortest unambiguous form is four hex digits.
_HEX: Final = re.compile(r'[0-9a-f]{4,40}')


def dist_of(change: str) -> str:
    """The distribution a :func:`~dev_lab.dev.lockcheck.stale` sentence names.

    The sentence is ``uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2``; the word after
    the verb is the distribution, a toolchain sentence answers ``'rust'``, a uv pin sentence ``'uv'``,
    and a sentence of another shape answers ``'lock'`` rather than guessing.
    """
    if change.startswith(f'{TOOLCHAIN} '):
        return 'rust'
    if change.startswith(f'{UV_PIN} '):
        return 'uv'
    _, _, rest = change.partition('resolution: ')
    words = rest.split()
    name = words[1] if len(words) >= _NAME_INDEX and words[0] in _VERBS else ''
    return name or 'lock'


def canon(name: str) -> str:
    """PEP 503's normal form: the lock's and a change line's spellings meet here."""
    return re.sub(r'[-_.]+', '-', name).lower()


class Floated(NamedTuple):
    """One sibling the lock sources from git FOLLOWING a line: its name, repository, line and locked commit."""

    name: str
    url: str
    branch: str
    sha: str


def line_of(query: str, locked: str = '') -> str | None:
    """The line a git source query *query* FOLLOWS; ``None`` when it HOLDS -- the one held-or-floated predicate.

    Judged by what the ref IS, URL-decoded: a ``tag`` holds (a tag is declared a fixed point), a ``rev`` holds as a
    full 40-hex commit sha, or as an abbreviation of the commit the lock resolved it to (*locked*, the locator's
    ``#<sha>``: ``rev = "595b43eb"`` pins that commit and is never a branch to fetch) -- any other ``rev`` names a
    branch and follows it, as ``branch`` does. No ref follows :data:`DEFAULT_LINE`.
    """
    refs = parse_qs(query)
    if 'tag' in refs:
        return None
    rev = refs.get('rev', [''])[0]
    if _FULL_SHA.fullmatch(rev.lower()) or (_HEX.fullmatch(rev.lower()) and locked.lower().startswith(rev.lower())):
        return None
    return refs.get('branch', [rev or DEFAULT_LINE])[0]


def floated(lock: str) -> tuple[Floated, ...]:
    """The packages lock text *lock* sources from git FOLLOWING a line (:func:`line_of`), in lock order.

    An unreadable lock follows nothing.
    """
    try:
        packages = tomllib.loads(lock).get('package', [])
    except tomllib.TOMLDecodeError:
        return ()
    found = []
    for entry in packages:
        source = entry.get('source', {}) if isinstance(entry, dict) else {}
        locator = source.get('git') if isinstance(source, dict) else None
        if not isinstance(locator, str) or not isinstance(entry.get('name'), str):
            continue
        address, _, sha = locator.partition('#')
        url, _, query = address.partition('?')
        if (line := line_of(query, sha)) is not None:
            found.append(Floated(canon(entry['name']), url, line, sha))
    return tuple(found)


def in_house(lock: str) -> frozenset[str]:
    """The names of :func:`floated`: the siblings an in-house relock moves off-cadence."""
    return frozenset(one.name for one in floated(lock))
