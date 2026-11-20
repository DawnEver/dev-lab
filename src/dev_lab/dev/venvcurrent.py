"""AN ENVIRONMENT IS PUBLISHED, NEVER UPGRADED IN PLACE (dev-lab #632, user ruling 2026-11-16).

Windows cannot overwrite an in-use ``python.exe`` or DLL, so an in-place venv upgrade waits for a free moment
that a live session, a watch or an MCP server may never leave. So no environment is ever changed under a
process: :mod:`dev_lab.dev.dep` builds each new one beside the live one at ``ROOT/.venvs/<name>/`` and
:func:`publish` makes it current by atomically replacing ONE pointer file, ``ROOT/.venv-current`` (write a
temp file, ``os.replace``). A running process keeps the environment it started from; every new launch reads
the pointer -- this module, ``agent_launcher.js`` and the githooks' ``with-venv.sh`` -- and takes the new one.

THE POINTER IS THE ONLY STATEMENT OF THE CURRENT ENVIRONMENT (user ruling 2026-11-20). No alias stands beside it:
an external tool is handed the environment explicitly (``UV_PROJECT_ENVIRONMENT``, the rendered editor settings).
The retired spelling (:data:`~dev_lab.dev.venvpointer.RETIRED_ALIAS`) goes ONCE (:func:`retire_alias`): a link
is removed; a legacy plain directory moves into ``.venvs/`` the first time nothing executes from it, and becomes
current when no pointer names one. It is retried by every reclaim and every follow (:mod:`dev_lab.dev.venvfollow`)
until it lands.

An old environment is reclaimed (:func:`reclaim`) only when no process executes from it -- the holder census
of :func:`dev_lab.dev.liverun.removal_holders` -- and never while it is being built (its :data:`BUILDING`
marker). ``dep`` runs the reclaim after each publish; :mod:`dev_lab.dev.reclaimrun` runs it with its worktree
pass.

ONE PUBLISHER PER WORKTREE. Two ``dep`` runs on one worktree each build and publish, and the later publish
re-points the pointer at an environment the other run's reclaim already removed. So a run that builds holds
:func:`exclusive_build` -- the OS lock of :func:`dev_lab.dev.servelock.held` on ``.venvs/build.lock``, dropped by the
OS however its holder dies, so a dead holder's lock is simply taken -- and a second run refuses at once naming the
holder. The holder writes its pid and start time into the lock file past the locked byte; the per-environment
:data:`BUILDING` marker stays a different fact (which environment reclaim must spare), so neither replaces the other.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lab_commons.census import processes

from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.liverun import Census, label, removal_holders
from dev_lab.dev.servelock import held
from dev_lab.dev.venvpointer import HOME, POINTER, RETIRED_ALIAS, named

__all__ = [
    'BUILDING',
    'BUILD_LOCK',
    'BUILD_WALL_S',
    'RECLAIMING',
    'BuildBusy',
    'abandon',
    'building',
    'exclusive_build',
    'fresh',
    'holds_alias',
    'publish',
    'reclaim',
    'reclaimed',
    'retire_alias',
    'target',
]

#: Suffix of the marker BESIDE an environment being built (``.venvs/<name>.building``): never reclaimed. Beside,
#: not inside: uv refuses to sync into a non-empty directory that is not yet a venv.
BUILDING: Final = '.building'
#: A build marker older than this is a dead builder's: its environment is reclaimable.
BUILD_WALL_S: Final = 6 * 3600.0
#: The per-worktree lock file in :data:`HOME` a building ``dep`` run holds (:func:`exclusive_build`).
BUILD_LOCK: Final = 'build.lock'
#: Byte 0 is the locked region; the holder's ``<pid> <start>`` line follows it, readable while it is held.
_HOLDER_AT: Final = 1
#: Suffix of an environment moved aside for removal: never resolvable; a removal that failed is retried next time.
RECLAIMING: Final = '.reclaiming'


def fresh(root: Path) -> Path:
    """A new environment path for *root*, not yet created (uv builds it), marked :data:`BUILDING`.

    Named ``<lock digest>-<utc stamp>``.

    The name is fixed BEFORE the build (a venv's entry-point shims embed its absolute path, so it cannot be renamed
    after). The lock digest says which resolution it holds; the stamp keeps two builds of one lock apart.
    """
    digest = hashlib.sha256()
    for name in ('uv.lock', 'pyproject.toml'):
        path = Path(root) / name
        digest.update(path.read_bytes() if path.is_file() else b'')
    stem = f'{digest.hexdigest()[:12]}-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}'
    home, n = Path(root) / HOME, 0
    env = home / stem
    while env.exists() or _marker(env).exists():
        n += 1
        env = home / f'{stem}-{n}'
    home.mkdir(parents=True, exist_ok=True)
    _marker(env).write_text(str(os.getpid()), encoding='utf-8')
    return env


def target(root: Path, base: str, live: Path, *, side_by_side: bool) -> tuple[Path, str]:
    """The environment a ``dep`` run changes and its interpreter: a sync builds a :func:`fresh` one beside *live*."""
    prefix = fresh(root) if side_by_side else live
    return prefix, str(prefix.joinpath(*Path(base).relative_to(live).parts))


def _marker(env: Path) -> Path:
    return env.with_name(env.name + BUILDING)


def abandon(env: Path) -> None:
    """Remove a build that failed, and its marker: it was never published, so nothing runs from it."""
    remove_tree(env)
    _marker(env).unlink(missing_ok=True)


def publish(root: Path, env: Path) -> str:
    """Make *env* current: atomically replace :data:`POINTER`; one line saying so.

    A reader sees the old name or the new one, never a partial file: the content is written whole to a temp file
    beside the pointer and ``os.replace``-d over it.
    """
    root, env = Path(root), Path(env)
    temporary = root / f'{POINTER}.{os.getpid()}.tmp'
    temporary.write_text(env.name + '\n', encoding='utf-8')
    _replace(temporary, root / POINTER)
    _marker(env).unlink(missing_ok=True)
    return f'{root / POINTER} -> {env.name}'


def _replace(source: Path, target: Path, *, tries: int = 200) -> None:
    """``os.replace``, retried while a Windows reader holds *target* open without delete sharing (Python's own)."""
    for _ in range(tries - 1):
        try:
            source.replace(target)
        except PermissionError:
            time.sleep(0.01)
        else:
            return
    source.replace(target)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def holds_alias(root: Path) -> bool:
    """Whether *root* still holds the retired :data:`RETIRED_ALIAS`, as a link or a directory."""
    alias = Path(root) / RETIRED_ALIAS
    return alias.exists() or _is_link(alias)


def retire_alias(root: Path, *, census: Census = processes) -> str:
    """THE ONE-TIME MIGRATION to the pointer alone; ``''`` once *root* holds no :data:`RETIRED_ALIAS`.

    A link is removed. A plain directory (the legacy layout) moves into :data:`HOME` once nothing executes from it,
    and is published when no pointer names an environment yet.
    """
    root = Path(root)
    alias = root / RETIRED_ALIAS
    if _is_link(alias):
        try:
            alias.unlink() if alias.is_symlink() else alias.rmdir()
        except OSError as exc:
            return f'{alias} kept: {exc}'
        return f'{alias} removed: {POINTER} alone names the environment'
    if not alias.is_dir():
        return ''
    if users := removal_holders(alias, census=census):
        return f'legacy {alias} kept: {len(users)} process(es) run from it ({label(users[0])})'
    aside = root / HOME / f'legacy-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}'
    try:
        aside.parent.mkdir(parents=True, exist_ok=True)
        alias.replace(aside)
    except OSError as exc:
        return f'legacy {alias} kept: {exc}'
    moved = f'legacy {alias} moved to {aside}'
    return moved if named(root) is not None else f'{moved}; {publish(root, aside)}'


def building(env: Path) -> bool:
    """Whether *env* carries a live :data:`BUILDING` marker (younger than :data:`BUILD_WALL_S`)."""
    try:
        return time.time() - _marker(env).stat().st_mtime < BUILD_WALL_S
    except OSError:
        return False


def reclaimed(env: Path) -> str:
    """Remove *env*, MOVED ASIDE first.

    Windows refuses to rename a directory a process runs from, so a holder the census missed keeps its environment
    whole instead of losing half its files to a removal that stopped at its interpreter.
    """
    aside = env if env.name.endswith(RECLAIMING) else env.with_name(env.name + RECLAIMING)
    try:
        if aside != env:
            env.replace(aside)
        abandon(aside)
    except OSError as exc:
        return f'kept     {env}  ({exc})'
    return f'reclaimed {env}'


def reclaim(root: Path, *, census: Census = processes, building_here: bool = False) -> tuple[str, ...]:
    """Remove every environment of *root* that is not current, not being built, and that nothing executes from.

    It reads the live pointer and then walks :data:`HOME`, so a build publishing between the two would lose its new
    environment as "not current": a reclaim runs under :func:`exclusive_build` and skips while a build holds it.
    *building_here* is the build's own reclaim, already inside that lock.
    """
    if building_here:
        return _reclaim(Path(root), census=census)
    try:
        with exclusive_build(root):
            return _reclaim(Path(root), census=census)
    except BuildBusy as exc:
        return (f'kept     every environment of {root}: {exc}',)


def _reclaim(root: Path, *, census: Census) -> tuple[str, ...]:
    lines = [line] if (line := retire_alias(root, census=census)) else []
    home, live = root / HOME, named(root)
    if not home.is_dir() or live is None:
        return tuple(lines)
    table = tuple(census())
    for env in sorted(home.iterdir()):
        if not env.is_dir() or env.name == live.name or building(env):
            continue
        if users := removal_holders(env, census=lambda: table):
            lines.append(f'kept     {env}  ({len(users)} holder(s): {label(users[0])})')
            continue
        lines.append(reclaimed(env))
    return tuple(lines)


class BuildBusy(RuntimeError):
    """Another live run (a ``dep`` build or a reclaim) holds this worktree's :data:`BUILD_LOCK`."""


def _holder(lock: Path) -> str:
    try:
        with lock.open('rb') as handle:
            handle.seek(_HOLDER_AT)
            pid, _, start = handle.read().decode('utf-8').strip().partition(' ')
    except (OSError, UnicodeDecodeError):
        pid, start = '', ''
    if not pid.isdigit():
        return f'another run holds {lock} (its pid is not yet written); wait for it'
    return (
        f'another run (pid {pid}, started {start}) is building or reclaiming this worktree and holds {lock}; '
        f'wait for it, or stop it with dev_lab.dev.stoprun --pid {pid}'
    )


@contextlib.contextmanager
def exclusive_build(root: Path) -> Iterator[None]:
    """Hold *root*'s :data:`BUILD_LOCK` for the block; raise :class:`BuildBusy` naming the holder when it is held."""
    lock = Path(root) / HOME / BUILD_LOCK
    with held(lock) as mine:
        if not mine:
            raise BuildBusy(_holder(lock))
        with lock.open('r+b') as handle:
            handle.seek(_HOLDER_AT)
            handle.write(f'{os.getpid()} {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}\n'.encode())
            handle.truncate()
        yield
