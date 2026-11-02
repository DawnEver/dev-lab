"""A LOCK CHANGE REACHES ONLY ITS IMPORTERS (user ruling D48-2, 2026-11-01).

:data:`~dev_lab.dev.footprint.LOCK` used to sit in :data:`~dev_lab.dev.footprint.ALWAYS`,
so a relock that only moved the ``dev-lab`` git pin re-ran a consumer's whole suite
(``scope=full ran=5471`` on the cluster, measured 2026-11-01; consumer #5397 relocked ~7 times that day).
Now :func:`resolve_lock` replaces a changed :data:`LOCK` by ``import:<name>`` for the import names of the
packages whose locked entry changed, closed over the lock's dependency graph IN REVERSE (a numpy bump
reaches scipy's importers). Doubt reaches everything by leaving :data:`LOCK` itself in the diff: a change
outside ``[[package]]`` (header, resolution markers, ``requires-python``), an unparseable lock, a package
:func:`import_names` cannot map, or one the RUNNER loads whatever a test imports (``pytest``, a ``pytest11``
plugin, a ``.pth`` installer). ``pyproject.toml`` stays in :data:`ALWAYS`: it carries pytest's and this
module's configuration, and splitting it by table is a second TOML differ no measured waste asks for yet.

The footprint side -- which test imports which top-level name -- is :mod:`dev_lab.dev.footprint`; this
module reads only the two locks and the running environment's distribution metadata.
"""

from __future__ import annotations

import functools
import importlib.metadata
import re
import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.footprint import IMPORT, LOCK
from dev_lab.dev.forge import _GIT

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['import_names', 'lock_reach', 'resolve_lock']

_GIT_TIMEOUT_S: Final = 120


def _show(root: Path, spec: str) -> str:
    """``git show <spec>`` in *root*: one side of the lock."""
    return _door.run(
        [_GIT, '-C', str(root), 'show', spec],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=True,
    ).stdout


def _canon(name: str) -> str:
    """PEP 503's normal form of a distribution name: the lock's and the metadata's spellings meet here."""
    return re.sub(r'[-_.]+', '-', name).lower()


@functools.cache
def _installed() -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    """``({distribution: import names}, runner distributions)`` of the running environment, read once."""
    names: dict[str, set[str]] = {}
    for top, dists in importlib.metadata.packages_distributions().items():
        if top.isidentifier() and not top.startswith('__editable__'):
            for dist in dists:
                names.setdefault(_canon(dist), set()).add(top)
    plugins = importlib.metadata.entry_points(group='pytest11')
    runner = {'pytest'} | {_canon(ep.dist.name) for ep in plugins if ep.dist is not None}
    for dist in importlib.metadata.distributions():
        if any(len(f.parts) == 1 and f.name.endswith('.pth') for f in dist.files or ()):
            runner.add(_canon(dist.metadata['Name'] or ''))
    return {dist: frozenset(tops) for dist, tops in names.items()}, frozenset(runner)


def import_names(dist: str) -> frozenset[str] | None:
    """The top-level import names distribution *dist* installs; ``None`` when it reaches EVERY test.

    Read from the running environment's metadata (``packages_distributions``: ``top_level.txt``, else
    RECORD). ``None`` for a distribution that environment does not know -- doubt carries nothing -- and for
    one the RUNNER loads whatever a test imports: ``pytest``, a ``pytest11`` plugin, a top-level ``.pth``.
    """
    known, runner = _installed()
    dist = _canon(dist)
    return None if dist in runner else known.get(dist)


def _packages(lock: Mapping[str, Any]) -> dict[str, list[Any]] | None:
    """``{canonical name: [its locked entries]}``; ``None`` when an entry is not a named table."""
    found: dict[str, list[Any]] = {}
    for entry in lock.get('package', []):
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            return None
        found.setdefault(_canon(entry['name']), []).append(entry)
    return found


def _depends(entries: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every package the *entries* depend on: runtime, optional and dev dependency lists alike."""
    found = set()
    for entry in entries:
        groups = [entry.get('dependencies', [])]
        for key in ('optional-dependencies', 'dev-dependencies'):
            groups += list(entry.get(key, {}).values())
        found |= {_canon(dep['name']) for group in groups for dep in group}
    return found


def _graphs(old: str, new: str) -> tuple[set[str], dict[str, set[str]]] | None:
    """``(changed packages, {package: its dependents})`` of two locks; ``None`` on any doubt (:func:`lock_reach`)."""
    try:
        before, after = tomllib.loads(old), tomllib.loads(new)
        if {k: v for k, v in before.items() if k != 'package'} != {k: v for k, v in after.items() if k != 'package'}:
            return None
        was, now = _packages(before), _packages(after)
        if was is None or now is None:
            return None
        local = {package for graph in (was, now) for package, entries in graph.items() if _in_repo(entries)}
        dependents: dict[str, set[str]] = {}
        for graph in (was, now):
            for package, entries in graph.items():
                for dep in _depends(entries) if package not in local else ():
                    dependents.setdefault(dep, set()).add(package)
    except (tomllib.TOMLDecodeError, AttributeError, TypeError, KeyError):
        return None
    changed = {package for package in was.keys() | now.keys() if was.get(package) != now.get(package)}
    return changed - local, dependents


def _in_repo(entries: Iterable[Mapping[str, Any]]) -> bool:
    """Whether a package is the repo's OWN code: an editable or virtual source at a relative path inside it.

    Its importers reach their third-party imports through their own ``import:<name>`` paths, and its change
    is a change to tracked files, so it is no door (F-759cb56e8a22: the root's entry depends on everything,
    and walking through it made a dev-lab pin move reach every test again). A path outside the repo is
    third-party code the footprint cannot read, so it stays a package like any other.
    """
    for entry in entries:
        source = entry.get('source', {})
        path = source.get('editable', source.get('virtual'))
        if not isinstance(path, str) or ':' in path or path.startswith(('/', '\\')):
            return False
        if '..' in PurePosixPath(path.replace('\\', '/')).parts:
            return False
    return True


def lock_reach(
    old: str, new: str, names: Callable[[str], frozenset[str] | None] | None = None
) -> frozenset[str] | None:
    """The import names a lock change from *old* to *new* reaches; ``None`` when it reaches everything.

    A package is CHANGED when its locked entries differ (version, source or git sha, dependency list --
    any byte of an entry), and REACHED when changed or depending on a reached package, over the union of
    both locks' graphs (a dropped edge still reaches). A difference outside ``[[package]]``, an unreadable
    lock, or a reached package *names* maps to ``None``, reaches everything (module docstring).
    """
    graphs = _graphs(old, new)
    if graphs is None:
        return None
    reached, dependents = graphs
    todo = list(reached)
    while todo:
        for dependent in dependents.get(todo.pop(), ()):
            if dependent not in reached:
                reached.add(dependent)
                todo.append(dependent)
    found: set[str] = set()
    for package in sorted(reached):
        tops = (names or import_names)(package)
        if tops is None:
            return None
        found |= tops
    return frozenset(found)


def resolve_lock(
    root: Path, a: str, b: str, changed: Iterable[str], names: Callable[[str], frozenset[str] | None] | None = None
) -> tuple[str, ...]:
    """*changed* with :data:`LOCK` replaced by the ``import:<name>`` paths it reaches; kept on any doubt."""
    changed = tuple(changed)
    if LOCK not in changed:
        return changed
    try:
        reach = lock_reach(_show(root, f'{a}:{LOCK}'), _show(root, f'{b}:{LOCK}'), names)
    except subprocess.SubprocessError:  # added or deleted: no two sides to compare
        return changed
    if reach is None:
        return changed
    return tuple(sorted({*changed, *(IMPORT + top for top in reach)} - {LOCK}))
