"""AN ENVIRONMENT IS PUBLISHED, NEVER UPGRADED IN PLACE (dev-lab #632, user ruling 2026-11-16).

Windows cannot overwrite an in-use ``python.exe`` or DLL, so an in-place venv upgrade waits for a free moment
that a live session, a watch or an MCP server may never leave. So no environment is ever changed under a
process: :mod:`dev_lab.dev.dep` builds each new one beside the live one at ``ROOT/.venvs/<name>/`` and
:func:`publish` makes it current by atomically replacing ONE pointer file, ``ROOT/.venv-current`` (write a
temp file, ``os.replace``). A running process keeps the environment it started from; every new launch reads
the pointer -- this module, ``agent_launcher.js`` and the githooks' ``with-venv.sh`` -- and takes the new one.

THE POINTER IS THE SOURCE OF TRUTH. ``ROOT/.venv`` stays as a junction (a symlink on POSIX) to the current
environment for tools that only know that path; it is re-pointed best-effort after the swap. A checkout with
no pointer is the legacy layout (a plain ``.venv`` directory) and resolves there: the one-time migration
moves that directory aside into ``.venvs/`` the first time nothing executes from it (:func:`retire_passed_over`), and
``.venv`` becomes the alias -- so a launcher or hook still spelling ``.venv`` runs the current environment. It is
retried by every publish, every reclaim and every follow (:mod:`dev_lab.dev.venvfollow`) until it lands.

An old environment is reclaimed (:func:`reclaim`) only when no process executes from it -- the holder census
of :func:`dev_lab.dev.liverun.removal_holders` -- and never while it is being built (its :data:`BUILDING`
marker). ``dep`` runs the reclaim after each publish; :mod:`dev_lab.dev.reclaimrun` runs it with its worktree
pass.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Final

from lab_commons.census import processes

from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.liverun import Census, label, removal_holders
from dev_lab.dev.venvpointer import ALIAS, HOME, POINTER, named

if sys.platform == 'win32':
    import _winapi

__all__ = [
    'BUILDING',
    'BUILD_WALL_S',
    'RECLAIMING',
    'abandon',
    'building',
    'fresh',
    'passed_over',
    'publish',
    'reclaim',
    'reclaimed',
    'retire_passed_over',
    'stale_alias',
    'target',
]

#: Suffix of the marker BESIDE an environment being built (``.venvs/<name>.building``): never reclaimed. Beside,
#: not inside: uv refuses to sync into a non-empty directory that is not yet a venv.
BUILDING: Final = '.building'
#: A build marker older than this is a dead builder's: its environment is reclaimable.
BUILD_WALL_S: Final = 6 * 3600.0
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
    """Make *env* current: atomically replace :data:`POINTER`, then re-point :data:`ALIAS` best-effort.

    A reader sees the old name or the new one, never a partial file: the content is written whole to a temp file
    beside the pointer and ``os.replace``-d over it. Returns one line on what became of the alias.
    """
    root, env = Path(root), Path(env)
    temporary = root / f'{POINTER}.{os.getpid()}.tmp'
    temporary.write_text(env.name + '\n', encoding='utf-8')
    _replace(temporary, root / POINTER)
    _marker(env).unlink(missing_ok=True)
    return _repoint(root, env)


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


def _link(alias: Path, env: Path) -> None:
    if sys.platform == 'win32':
        _winapi.CreateJunction(str(env), str(alias))
    else:
        alias.symlink_to(env, target_is_directory=True)


def _repoint(root: Path, env: Path) -> str:
    """Point :data:`ALIAS` at *env*; a legacy directory there is left for :func:`retire_passed_over`."""
    alias = root / ALIAS
    if alias.exists() and not _is_link(alias):
        return f'{alias} is a legacy directory; it moves aside once nothing runs from it (the pointer already rules)'
    try:
        if _is_link(alias):
            alias.unlink() if alias.is_symlink() else alias.rmdir()
        _link(alias, env)
    except OSError as exc:
        return f'{alias} not re-pointed ({exc}); the pointer {root / POINTER} still names {env.name}'
    return f'{alias} -> {env}'


def stale_alias(root: Path, env: Path, python: Path | None = None) -> str:
    """Why :data:`ALIAS` does not run the current *env* and the door out, ``''`` when it does (or is absent).

    *python* is *env*'s interpreter, named as the direct way round a held ``.venv``.
    """
    alias = Path(root) / ALIAS
    if not alias.exists() or alias.resolve() == Path(env).resolve():
        return ''
    why = f'{alias} still runs {alias.resolve()}, not the published {env}'
    return (
        why if python is None else f'{why}. Stop what runs from it and re-run this bootstrap, or run {python} directly.'
    )


def passed_over(root: Path) -> bool:
    """Whether *root*'s :data:`ALIAS` is a plain directory the pointer passed over (:func:`retire_passed_over`)."""
    alias = Path(root) / ALIAS
    return named(root) is not None and alias.is_dir() and not _is_link(alias)


def retire_passed_over(root: Path, *, census: Census = processes) -> str:
    """The ONE-TIME migration: a plain ``.venv`` directory moves into :data:`HOME` once nothing executes from it."""
    root = Path(root)
    alias, env = root / ALIAS, named(root)
    if env is None or not passed_over(root):
        return ''
    if users := removal_holders(alias, census=census):
        return f'legacy {alias} kept: {len(users)} process(es) run from it ({label(users[0])})'
    aside = root / HOME / f'legacy-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}'
    try:
        alias.replace(aside)
    except OSError as exc:
        return f'legacy {alias} kept: {exc}'
    return f'legacy {alias} moved to {aside}; ' + _repoint(root, env)


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


def reclaim(root: Path, *, census: Census = processes) -> tuple[str, ...]:
    """Remove every environment of *root* that is not current, not being built, and that nothing executes from."""
    root = Path(root)
    lines = [line] if (line := retire_passed_over(root, census=census)) else []
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
