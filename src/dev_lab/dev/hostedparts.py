"""``[tool.dev_lab.parts] hosted``: the parts run in a hosted job of their own, read and refused here.

Split from :mod:`dev_lab.dev.jobparts` (2026-11-17, its size band), which renders each declared part's job
(:func:`dev_lab.dev.hostedjobs.hosted_jobs`). A declared part is a PRODUCED resource naming a ``setup`` command, the
ai-lab ``tasks`` whose key bundles it loads, or both -- and optionally a ``cache`` of what its setup downloads, kept
across runs under a key hashed from the file pinning it (dev-lab#998); anything else is refused naming the shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast

from lab_commons.hpc.needsets import read_vocabulary

from dev_lab.dev.family import declared_in
from dev_lab.dev.platformparts import UndeclaredPart
from dev_lab.dev.taskkeys import secret_name

__all__ = ['Cache', 'Hosted', 'hosted_parts', 'pull_request_parts']


@dataclass(frozen=True)
class Cache:
    """A hosted part's download cache: the *path* its setup fills, restored while the file *key* hashes the same."""

    path: str
    key: str


@dataclass(frozen=True)
class Hosted:
    """A part run in its own hosted job: the ai-lab tasks whose key bundles it loads, and its ``setup`` command."""

    tasks: tuple[str, ...] = ()
    setup: str = ''
    #: Runs only on a manual dispatch (``workflow_dispatch``): never nightly, never on the gate (user ruling D66).
    manual: bool = False
    #: What its setup downloads, kept across runs (dev-lab#998); ``None``: nothing cached.
    cache: Cache | None = None

    @property
    def secrets(self) -> tuple[str, ...]:
        """The secret holding each task's bundle, in task order."""
        return tuple(secret_name(task) for task in self.tasks)


_ENTRY_KEYS: Final = frozenset({'tasks', 'setup', 'manual', 'cache'})

#: The keys of a ``cache`` table, each a non-empty string.
_CACHE_KEYS: Final = frozenset({'path', 'key'})

#: The keys of which an entry must name at least one.
_WORK_KEYS: Final = frozenset({'tasks', 'setup'})


def _cache_of(value: object) -> Cache | None:
    """*value* as a declared :class:`Cache`; ``None``: not a table of a non-empty path and a quote-free key."""
    if not isinstance(value, dict):
        return None
    table = cast('dict[str, object]', value)
    if frozenset(table) != _CACHE_KEYS:
        return None
    path, key = table['path'], table['key']
    if not isinstance(path, str) or not isinstance(key, str) or not path.strip() or not key.strip() or "'" in key:
        return None
    return Cache(path, key)


def _malformed(name: str, entry: object, produced: set[str]) -> str:
    """Why hosted *entry* of part *name* is refused; ``''``: a produced resource naming a setup, tasks or both."""
    if name not in produced:
        return 'not a produced resource'
    if not isinstance(entry, dict) or not set(entry) & _WORK_KEYS or not set(entry) <= _ENTRY_KEYS:
        return f'not a table of {sorted(_ENTRY_KEYS)} naming at least one of {sorted(_WORK_KEYS)}'
    setup, tasks, manual = entry.get('setup', 'x'), entry.get('tasks', ['x']), entry.get('manual', False)
    wrong = {
        'cache is not a table of a non-empty path and key (no quote in the key)': (
            'cache' in entry and _cache_of(cast('dict[str, object]', entry)['cache']) is None
        ),
        'cache has no setup to fill it': 'cache' in entry and 'setup' not in entry,
        'manual is not a boolean': not isinstance(manual, bool),
        'setup is not a non-empty string': not isinstance(setup, str) or not setup.strip(),
        'tasks is not a non-empty list of strings': (
            not isinstance(tasks, list) or not tasks or not all(isinstance(one, str) for one in tasks)
        ),
    }
    if why := next((why for why, bad in wrong.items() if bad), ''):
        return why
    try:
        [secret_name(task) for task in entry.get('tasks', [])]
    except ValueError as error:
        return str(error)
    return ''


def hosted_parts(text: str) -> dict[str, Hosted]:
    """``[tool.dev_lab.parts] hosted`` of pyproject *text*, by part; a malformed or unproduced one is refused."""
    parts = declared_in(text, 'parts')
    value = parts.get('hosted', {})
    resources = set(read_vocabulary(text).resources)
    produced = resources - set(parts.get('unproduced', []))
    shape = (
        f'each key a produced resource of {sorted(produced)} = '
        '{ setup = "<shell command>", tasks = ["<ai-lab task>", ...], manual = true|false, '
        'cache = { path = "<dir setup fills>", key = "<file whose hash keys it>" } }, '
        'at least one of setup and tasks, a cache only with a setup'
    )
    if not isinstance(value, dict):
        msg = f'[tool.dev_lab.parts] hosted = {value!r} is not a table: write {shape}'
        raise UndeclaredPart(msg)
    for name, entry in value.items():
        if why := _malformed(name, entry, produced):
            msg = f'[tool.dev_lab.parts] hosted part {name!r} = {entry!r}: {why}; write {shape}'
            raise UndeclaredPart(msg)
    return {
        name: Hosted(
            tuple(entry.get('tasks', ())),
            entry.get('setup', ''),
            entry.get('manual', False),
            _cache_of(cast('dict[str, object]', entry).get('cache')),
        )
        for name, entry in value.items()
    }


def pull_request_parts(text: str) -> frozenset[str]:
    """The hosted parts of pyproject *text* a pull request's own job produces: neither ``manual`` nor secret-bound.

    Such a part is required by merge-ready like ``tests/base`` (dev-lab#1024): its job runs for every pull request,
    so it is never a hand part, whatever part ``hands=`` it ids.
    """
    return frozenset(name for name, hosted in hosted_parts(text).items() if not hosted.manual and not hosted.tasks)
