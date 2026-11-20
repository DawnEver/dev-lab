"""AN ENVIRONMENT IS PUBLISHED, NEVER UPGRADED IN PLACE (dev-lab #632, user ruling 2026-11-16).

Windows cannot overwrite an in-use ``python.exe`` or DLL, so an in-place venv upgrade waits for a free moment
that a live session, a watch or an MCP server may never leave. So no environment is ever changed under a
process: :mod:`dev_lab.dev.dep` builds each new one beside the live one at ``ROOT/.venvs/<name>/`` and
:func:`publish` makes it current by swapping ONE link, ``ROOT/.venv`` (user ruling 2026-11-20: ``.venv`` is the
name every tool expects): a symlink on POSIX, replaced atomically (a temp link ``os.replace``-d over it); a junction on
Windows, where no directory replace is atomic, so a temp junction is made first and the swap is a removal and a
rename -- measured 2026-11-20 at a 5-8 ms gap for a remove-and-create, with processes running from the old target
and through the link itself; a reader in that gap finds no ``.venv`` and names the bootstrap door. A running process
keeps the environment it started from (every resolver answers ``.venv`` RESOLVED); every new launch takes the new one.

A plain ``.venv`` directory (a checkout never published) is its own environment until a publish: it moves into
``.venvs/`` first, once nothing executes from it, else the publish is refused by name. The retired pointer file
``.venv-current`` is migrated ONCE (:func:`migrate`, FORMATS-MIGRATE-ONCE): ``.venv`` is linked to the environment
it names, and the file is removed. Every reclaim and every follow (:mod:`dev_lab.dev.venvfollow`) retries it.

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
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from lab_commons.census import processes

from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.liverun import Census, label, removal_holders
from dev_lab.dev.servelock import held
from dev_lab.dev.venvpointer import HOME, POINTER, RETIRED_POINTER, is_link, named

if sys.platform == 'win32':
    import _winapi

__all__ = [
    'BUILDING',
    'BUILD_LOCK',
    'BUILD_WALL_S',
    'RECLAIMING',
    'BuildBusy',
    'PublishRefused',
    'abandon',
    'building',
    'exclusive_build',
    'fresh',
    'migrate',
    'pending_migration',
    'publish',
    'reclaim',
    'reclaimed',
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


class PublishRefused(OSError):
    """A publish that could not make its environment current; the message names why and the door."""


def publish(root: Path, env: Path, *, census: Census = processes) -> str:
    """Make *env* current: swap :data:`POINTER` to link to it; one line saying so.

    A plain ``.venv`` directory moves into :data:`HOME` first (:func:`_set_aside`); held, the publish is refused
    by name and *env* stays built, unpublished.
    """
    root, env = Path(root), Path(env)
    link = root / POINTER
    if link.is_dir() and not is_link(link) and (why := _set_aside(root, census=census)):
        msg = f'{env} built but not published: {why}'
        raise PublishRefused(msg)
    _swap(link, env)
    _marker(env).unlink(missing_ok=True)
    (root / RETIRED_POINTER).unlink(missing_ok=True)
    return f'{link} -> {env}'


def _link(link: Path, env: Path) -> None:
    if sys.platform == 'win32':
        _winapi.CreateJunction(str(env), str(link))
    else:
        link.symlink_to(env, target_is_directory=True)


def _swap(link: Path, env: Path, *, tries: int = 200) -> None:
    """Point *link* at *env*: a temp link first, then the one short step that replaces *link* (module docstring)."""
    temporary = link.with_name(f'{link.name}.{os.getpid()}.tmp')
    if is_link(temporary):
        _unlink(temporary)
    _link(temporary, env)
    for attempt in range(tries):
        try:
            if sys.platform == 'win32' and is_link(link):
                _unlink(link)  # Windows replaces no directory atomically: removal and rename, the gap measured
            temporary.replace(link)
        except PermissionError:
            if attempt == tries - 1:
                _unlink(temporary)
                raise
            time.sleep(0.01)
        else:
            return


def _unlink(link: Path) -> None:
    link.unlink() if link.is_symlink() else link.rmdir()


def _set_aside(root: Path, *, census: Census) -> str:
    """Move a plain ``.venv`` directory into :data:`HOME` once nothing executes from it; why not, else ``''``."""
    plain = root / POINTER
    if users := removal_holders(plain, census=census):
        held = f'{len(users)} process(es) run from it ({label(users[0])})'
        return f'{plain} is a plain environment {held}; stop them and re-run'
    aside = root / HOME / f'legacy-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}'
    try:
        aside.parent.mkdir(parents=True, exist_ok=True)
        plain.replace(aside)
    except OSError as exc:
        return f'{plain} could not move into {HOME}: {exc}'
    return ''


def pending_migration(root: Path) -> bool:
    """Whether *root* still holds the retired :data:`RETIRED_POINTER` file."""
    return (Path(root) / RETIRED_POINTER).exists()


def migrate(root: Path, *, census: Census = processes) -> str:
    """THE ONE-TIME MIGRATION off :data:`RETIRED_POINTER`; ``''`` once *root* holds none.

    ``.venv`` is linked to the environment the file names (a plain ``.venv`` moved aside first), then the file goes.
    A file naming no environment goes too: ``.venv`` alone decides.
    """
    root = Path(root)
    retired = root / RETIRED_POINTER
    if not retired.exists():
        return ''
    name = retired.read_text(encoding='utf-8').split('\n', 1)[0].strip()
    env = root / HOME / name
    if name and name not in {'.', '..'} and not any(c in name for c in '/\\:') and env.is_dir() and named(root) != env:
        try:
            publish(root, env, census=census)
        except OSError as exc:
            return f'{retired} kept: {exc}'
    retired.unlink(missing_ok=True)
    return f'{retired} migrated: {root / POINTER} -> {named(root) or "(unpublished)"}'


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
    lines = [line] if (line := migrate(root, census=census)) else []
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
