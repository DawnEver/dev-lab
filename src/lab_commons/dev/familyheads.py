"""FAMILY HEADS: an environment whose floating family packages lag their forge heads is STALE.

THE HAZARD. A family package installed from git without a pin (``lab-commons @ git+https://...``,
floating, often through a ``[tool.uv] override-dependencies`` entry) is resolved ONCE, when the venv is
synced; afterwards the venv keeps that commit while the forge moves on. A run in it then judges code
against a dependency nobody else has, and hides a break that a fresh sync would show.

THE CHECK, cheap by construction. Every installed family distribution with a VCS origin carries its
URL, its requested ref and its commit in ``direct_url.json`` (PEP 610). One ``git ls-remote <url>
<ref>`` per distribution reads the forge head -- no clone, no fetch -- and the answer is cached for
:data:`CACHE_TTL_S` beside the machine's other run records, so a burst of runs asks the forge once.

THREE ANSWERS, NEVER TWO. Fresh (every installed commit is its head), STALE (named, with the remedy:
the repo's own sync door), or UNKNOWN (the forge did not answer -- offline is SAID, never read as
fresh). A distribution installed from a pinned commit (the requested ref is the commit itself) is
not floating and is never stale.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.resources import Broker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    'CACHE_TTL_S',
    'DEFAULT_DOOR',
    'Freshness',
    'Installed',
    'check',
    'family_freshness',
    'installed_family',
    'offline_line',
    'refusal',
    'sync_door',
]

#: How long a forge head is believed, in seconds. Short: the point is to see a push within minutes.
CACHE_TTL_S: Final = 300.0

#: The sync door when a repo declares none in ``[tool.lab_commons.doors]``.
DEFAULT_DOOR: Final = '<venv python> -m lab_commons.dev.dep --sync --upgrade-package <dist>'

_DOOR_KEY: Final = 'ENV-MUTATION-THROUGH-THE-DOOR'
_LS_REMOTE_TIMEOUT_S: Final = 20
_SHA_LEN: Final = 40


@dataclass(frozen=True, slots=True)
class Installed:
    """One family distribution installed from git: where from, which ref was asked for, which commit landed."""

    name: str
    url: str
    ref: str
    commit: str

    @property
    def pinned(self) -> bool:
        """Whether the ref asked for IS a commit -- then it does not float and cannot fall behind."""
        return len(self.ref) == _SHA_LEN and self.ref == self.commit


@dataclass(frozen=True, slots=True)
class Freshness:
    """The three answers: distributions behind their head (with it), and those the forge did not answer for."""

    stale: tuple[tuple[Installed, str], ...]
    unknown: tuple[Installed, ...]


def _canonical(name: str) -> str:
    return name.lower().replace('_', '-')


def installed_family(
    distributions: Callable[[], Iterable[metadata.Distribution]] = metadata.distributions,
) -> tuple[Installed, ...]:
    """Every distribution in THIS interpreter installed from a git URL (PEP 610): the floating family."""
    found: dict[str, Installed] = {}
    for distribution in distributions():
        name = _canonical(distribution.metadata['Name'] or '')
        try:
            origin = json.loads(distribution.read_text('direct_url.json') or '{}')
        except ValueError:
            continue
        vcs = origin.get('vcs_info', {})
        if vcs.get('vcs') != 'git' or not vcs.get('commit_id'):
            continue
        found[name] = Installed(
            name, str(origin['url']), str(vcs.get('requested_revision') or 'HEAD'), vcs['commit_id']
        )
    return tuple(found[name] for name in sorted(found))


def _ls_remote(url: str, ref: str) -> str | None:
    """The forge's sha for *ref* at *url*, or ``None`` when the forge did not answer."""
    try:
        done = _door.run(
            [shutil.which('git') or 'git', 'ls-remote', url, ref],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=_LS_REMOTE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    for line in done.stdout.splitlines():
        sha, _, name = line.partition('\t')
        if name in {ref, f'refs/heads/{ref}', f'refs/tags/{ref}'} or ref == 'HEAD':
            return sha.strip()
    return None


def _cached_head(
    cache: Path, url: str, ref: str, *, now: float, ls_remote: Callable[[str, str], str | None]
) -> str | None:
    try:
        heads = json.loads(cache.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        heads = {}
    key = f'{url} {ref}'
    hit = heads.get(key)
    if isinstance(hit, dict) and now - float(hit.get('at', 0)) < CACHE_TTL_S:
        return str(hit['sha'])
    sha = ls_remote(url, ref)
    if sha is not None:
        heads[key] = {'sha': sha, 'at': now}
        cache.parent.mkdir(parents=True, exist_ok=True)
        pending = cache.with_suffix('.tmp')
        pending.write_text(json.dumps(heads, sort_keys=True), encoding='utf-8')
        pending.replace(cache)
    return sha


def check(
    installed: Iterable[Installed],
    *,
    cache: Path,
    now: float | None = None,
    ls_remote: Callable[[str, str], str | None] | None = None,
) -> Freshness:
    """Compare each floating installed commit to its forge head (cached for :data:`CACHE_TTL_S`)."""
    moment = time.time() if now is None else now
    ask = _ls_remote if ls_remote is None else ls_remote
    stale: list[tuple[Installed, str]] = []
    unknown: list[Installed] = []
    for one in installed:
        if one.pinned:
            continue
        head = _cached_head(cache, one.url, one.ref, now=moment, ls_remote=ask)
        if head is None:
            unknown.append(one)
        elif head != one.commit:
            stale.append((one, head))
    return Freshness(tuple(stale), tuple(unknown))


def sync_door(root: Path) -> str:
    """The command *root* offers for a dependency change, from ``[tool.lab_commons.doors]``, else the shared one."""
    manifest = root / 'pyproject.toml'
    if manifest.is_file():
        doors = tomllib.loads(manifest.read_text(encoding='utf-8')).get('tool', {}).get('lab_commons', {})
        door = doors.get('doors', {}).get(_DOOR_KEY)
        if isinstance(door, str) and door:
            return door
    return DEFAULT_DOOR


def refusal(freshness: Freshness, *, door: str) -> str | None:
    """The refusal for a stale environment, naming every lagging package and the remedy; ``None`` when fresh."""
    if not freshness.stale:
        return None
    lagging = '; '.join(
        f'{one.name} installed {one.commit[:12]}, {one.ref} is {head[:12]}' for one, head in freshness.stale
    )
    names = ' '.join(f'--upgrade-package {one.name}' for one, _ in freshness.stale)
    return (
        f'the environment is STALE -- {lagging}. A run here would judge code against dependencies the forge '
        f'no longer serves. Remedy: {door} ({names}), then re-run.'
    )


def offline_line(freshness: Freshness) -> str | None:
    """One line naming the packages whose head could not be read; ``None`` when every head answered."""
    if not freshness.unknown:
        return None
    names = ', '.join(f'{one.name} ({one.url})' for one in freshness.unknown)
    return f'family heads UNKNOWN -- the forge did not answer for {names}; freshness is unchecked, not fresh.'


def family_freshness(root: Path) -> tuple[str | None, str | None]:
    """``(refusal, offline line)`` for THIS interpreter's floating packages, cached beside the machine's records."""
    freshness = check(installed_family(), cache=Broker().resource_dir() / 'family-heads.json')
    return refusal(freshness, door=sync_door(root)), offline_line(freshness)
