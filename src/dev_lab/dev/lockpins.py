"""LOCK PINS: an environment whose git-installed packages differ from the checkout's ``uv.lock`` is STALE.

THE RULE (PIN + FRESHNESS, user ruling 2026-10-17). Every install is ``uv sync --frozen`` from the
commit's own lock, so a commit's code and its exact dependencies are tested together; freshness of the
lock itself is the forge's (:mod:`dev_lab.dev.relock`, :mod:`dev_lab.dev.forgeheadgate`), its PIN
:mod:`dev_lab.dev.famtests.lockpin`'s. A run asks one question: does this interpreter hold what the
checkout's ``uv.lock`` pins? Never where a dependency's
branch tip has moved since -- a commit locked before its dependency moved is still its own exact pair.

THE CHECK, local by construction. Every installed distribution with a git origin carries its commit in
``direct_url.json`` (PEP 610); the lock carries the commit after ``#`` in its ``source = { git = ... }``.
A distribution the lock does not pin by git is not judged here. No network, so no third answer.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    'DEFAULT_DOOR',
    'Installed',
    'installed_git',
    'lock_freshness',
    'locked_git',
    'mismatches',
    'refusal',
    'sync_door',
]

#: The sync door when a repo declares none in ``[tool.lab_commons.doors]``.
DEFAULT_DOOR: Final = '<venv python> -m dev_lab.dev.dep --bootstrap'

_DOOR_KEY: Final = 'ENV-MUTATION-THROUGH-THE-DOOR'


@dataclass(frozen=True, slots=True)
class Installed:
    """One distribution installed from git: its canonical name and the commit that landed."""

    name: str
    commit: str


def _canonical(name: str) -> str:
    return name.lower().replace('_', '-')


def installed_git(
    distributions: Callable[[], Iterable[metadata.Distribution]] = metadata.distributions,
) -> tuple[Installed, ...]:
    """Every distribution in THIS interpreter installed from a git URL (PEP 610)."""
    found: dict[str, Installed] = {}
    for distribution in distributions():
        name = _canonical(distribution.metadata['Name'] or '')
        try:
            origin = json.loads(distribution.read_text('direct_url.json') or '{}')
        except ValueError:
            continue
        vcs = origin.get('vcs_info', {})
        if vcs.get('vcs') == 'git' and vcs.get('commit_id'):
            found[name] = Installed(name, vcs['commit_id'])
    return tuple(found[name] for name in sorted(found))


def locked_git(lock: Path) -> dict[str, str]:
    """Package name -> the commit *lock* pins it at, for every package the lock sources from git."""
    if not lock.is_file():
        return {}
    pins: dict[str, str] = {}
    for package in tomllib.loads(lock.read_text(encoding='utf-8')).get('package', []):
        git = package.get('source', {}).get('git')
        if isinstance(git, str) and '#' in git:
            pins[_canonical(package['name'])] = git.rpartition('#')[2]
    return pins


def mismatches(installed: Iterable[Installed], pins: Mapping[str, str]) -> tuple[tuple[Installed, str], ...]:
    """Each installed git distribution whose commit is not the one the lock pins, with the pinned commit."""
    return tuple((one, pins[one.name]) for one in installed if one.name in pins and pins[one.name] != one.commit)


def sync_door(root: Path) -> str:
    """The command *root* offers for a dependency change, from ``[tool.lab_commons.doors]``, else the shared one."""
    manifest = root / 'pyproject.toml'
    if manifest.is_file():
        doors = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('lab_commons', {})
        door = doors.get('doors', {}).get(_DOOR_KEY)
        if isinstance(door, str) and door:
            return door
    return DEFAULT_DOOR


def refusal(stale: Iterable[tuple[Installed, str]], *, door: str) -> str | None:
    """The refusal naming every package that differs from the lock and the remedy; ``None`` when none does."""
    rows = tuple(stale)
    if not rows:
        return None
    lagging = '; '.join(f'{one.name} installed {one.commit[:12]}, uv.lock pins {pin[:12]}' for one, pin in rows)
    return (
        f'the environment is STALE -- {lagging}. A run here would judge this commit against dependencies its '
        f"lock does not pin. Remedy: {door} (a frozen sync from the checkout's uv.lock), then re-run."
    )


def lock_freshness(root: Path) -> str | None:
    """The refusal for THIS interpreter against ``root/uv.lock``; ``None`` when it holds what the lock pins."""
    return refusal(mismatches(installed_git(), locked_git(root / 'uv.lock')), door=sync_door(root))
