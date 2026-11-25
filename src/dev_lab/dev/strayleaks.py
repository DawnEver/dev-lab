"""The trees the family's suites left OUTSIDE every temp root, each named with its cause and removed only by proof.

A rooted or relative path a test once used without a base resolved against the drive root or the home dir
(user report 2026-11-24: ``C:/var/tmp``, ``C:/results/<2hex>``, ``C:/src/repos/product``, ``C:/r/repos``,
``C:/tmp_diag``, ``~/output``, ``~/.pytest_cache``). Each cause is fixed at its source; what it already wrote
stays until a host removes it, and that is this module: :data:`FAMILIES` is the set, as data.

A FAMILY IS REMOVED ONLY WHEN ITS CONTENT PROVES IT OURS (:attr:`Family.ours`): a drive-root ``src/repos`` is a
person's work unless every checkout in it was cloned from a ``file://`` url, as only a test fixture does; a
tree with no traced producer goes only when it holds no file (``tmp_diag``); a :data:`SUSPECT` checkout only
when :func:`unshared` proves no work of its own is in it. A link or junction is never followed or removed.
A removed family's parents are removed too while they are left empty, up to the drive or home it was found under.

A family may instead be an AGED SET (:attr:`Family.glob`): the entries matching a glob inside a directory a tool
fills and never empties (JMAG Designer's ``~/JMAGDesignerTemp/ProjectTemp_*``, user ruling 2026-11-24). An entry
is removed when every file in it is older than the family's age AND no running holder process (:attr:`Family.holders`,
name prefixes) has its cwd or an open file inside it AND the entry can be renamed (Windows refuses that while any
handle inside is open): the lock probe runs at removal, the process check at the listing.

The door is ``python -m dev_lab.dev.tmpsweep --leaks`` (a listing) and ``--leaks --apply`` (the removal).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from lab_commons import launch

from dev_lab.dev.testtemp import writable_retry
from dev_lab.supervise.reading import psutil_module

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

__all__ = ['FAMILIES', 'Family', 'Found', 'find', 'remove']

_OBJECT: Final = re.compile(r'^[0-9a-f]{2}/[0-9a-f]{64}$')
_METRICS: Final = re.compile(r'^logs/\d{2}/\d{2}/\d{2}/metrics/[a-z_-]+\.jsonl$')
_FILE_URL: Final = re.compile(r'^\s*url\s*=\s*file://', re.MULTILINE)
#: What pytest writes into its cache dir and nothing else does (user ruling 2026-11-24: cache content only).
_PYTEST_CACHE: Final = re.compile(r'^(?:README\.md|\.gitignore|CACHEDIR\.TAG|v/cache/[A-Za-z_]+)$')
#: Drive-relative checkouts a test fixture is suspected of having left (user ruling 2026-11-24). Each is removed
#: only after :func:`unshared` proves it holds no commit missing from every remote it names and no change.
SUSPECT: Final[tuple[str, ...]] = ('src/repos/product',)
_GIT_TIMEOUT_S: Final = 60
_GIT_EXE: Final = shutil.which('git') or 'git'


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _files(root: Path) -> Iterator[str]:
    """Every file under *root* as a POSIX relative path; links are neither followed nor listed."""
    stack = [root]
    while stack:
        here = stack.pop()
        for child in here.iterdir():
            if _linked(child):
                continue
            if child.is_dir():
                stack.append(child)
            else:
                yield child.relative_to(root).as_posix()


def _every_file(pattern: re.Pattern[str], what: str) -> Callable[[Path], str | None]:
    def judge(path: Path) -> str | None:
        files = list(_files(path))
        stray = next((name for name in files if not pattern.match(name)), None)
        if not files:
            return None
        return None if stray is None else f'{stray} is not {what}'

    return judge


def _file_clones(path: Path) -> str | None:
    """Ours when every direct child is a checkout cloned from a ``file://`` url, as only a test fixture is."""
    for child in sorted(path.iterdir()):
        config = child / '.git' / 'config'
        if _linked(child) or not config.is_file() or not _FILE_URL.search(config.read_text(encoding='utf-8')):
            return f'{child.name} is no checkout cloned from a file:// url: somebody may work in it'
        if (why := unshared(child)) is not None:
            return f'{child.name}: {why}'
    return None


def _git(path: Path, *args: str) -> str:
    done = launch.run(
        [_GIT_EXE, '-C', str(path), *args], capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=True
    )
    return done.stdout.strip()


def unshared(path: Path) -> str | None:
    """Why the checkout at *path* holds work only it has (a change, or a commit no remote it names has); else None."""
    if not (path / '.git').exists():
        return "not a git checkout: a suspect path holding anything else is somebody else's"
    try:
        if changed := _git(path, 'status', '--porcelain', '--untracked-files=all'):
            return f'uncommitted change(s): {changed.splitlines()[0].strip()}'
        if not _git(path, 'remote'):
            return (
                'it names no remote, so every commit in it is its own'
                if _git(path, 'rev-list', '-n1', '--all')
                else None
            )
        if own := _git(path, 'rev-list', '-n1', '--all', '--not', '--remotes'):
            return f'commit {own[:12]} is on no remote it names'
    except (OSError, subprocess.SubprocessError) as exc:
        return f'git cannot read it: {exc}'
    return None


def _newest(path: Path) -> float:
    """The newest mtime in *path*'s tree; a link is neither entered nor counted."""
    newest = path.lstat().st_mtime
    stack = [path] if path.is_dir() else []
    while stack:
        for child in stack.pop().iterdir():
            if _linked(child):
                continue
            newest = max(newest, child.lstat().st_mtime)
            if child.is_dir():
                stack.append(child)
    return newest


def held_paths(prefixes: Sequence[str]) -> list[Path] | str:
    """The cwd and open files of every running process whose name starts with one of *prefixes*.

    A string instead names why that cannot be told (psutil absent, a holder's files unreadable): the caller keeps.
    """
    psutil = psutil_module()
    if psutil is None:
        return 'psutil is not installed, so a running holder cannot be ruled out'
    paths: list[Path] = []
    for proc in psutil.process_iter(['name']):
        name = (proc.info.get('name') or '').lower()
        if not name.startswith(tuple(prefixes)):
            continue
        try:
            paths.append(Path(proc.cwd()))
            paths.extend(Path(one.path) for one in proc.open_files())
        except psutil.NoSuchProcess:
            continue
        except psutil.Error as exc:
            return f'{name} (pid {proc.pid}) runs and its files cannot be read: {exc}'
    return paths


def _aged_unheld(max_age_days: float, holders: Sequence[str]) -> Callable[[Path], str | None]:
    def judge(path: Path) -> str | None:
        age = (time.time() - _newest(path)) / 86400.0
        if age < max_age_days:
            return f'written {age:.1f} day(s) ago, inside the {max_age_days:g}-day age: in use'
        held = held_paths(holders)
        if isinstance(held, str):
            return held
        if any(one == path or path in one.parents for one in held):
            return 'a running holder process has its cwd or an open file inside'
        return None

    return judge


def _named(_path: Path) -> str | None:
    return None


def _no_files(path: Path) -> str | None:
    """Ours when it holds no file at all (empty dirs only): anything else is somebody's."""
    stray = next(_files(path), None)
    return None if stray is None else f'{stray} is a file: only an empty tree is removed'


@dataclass(frozen=True, slots=True)
class Family:
    """One leak family: where it lands, what proves an instance ours, and the cause that wrote it."""

    name: str
    anchor: Literal['drive', 'home']
    relative: str
    ours: Callable[[Path], str | None]  # None: ours, removable; else why it is kept
    cause: str
    glob: str = ''  # set: an aged set, each match inside *relative* is one instance


FAMILIES: Final[tuple[Family, ...]] = (
    Family(
        'supervise-candidate',
        'drive',
        'var/tmp/lab-supervise-candidate',
        _named,
        'supervise preflight built its candidate at the module constant /var/tmp/... in tests',
    ),
    Family(
        'fake-remote-objects',
        'drive',
        'results',
        _every_file(_OBJECT, 'a content-addressed <2hex>/<sha256> object'),
        "the fake rclone joined a rooted 'bucket:/results/..' spec onto its dir",
    ),
    *(Family(f'suspect:{one}', 'drive', one, unshared, 'a test fixture is suspected') for one in SUSPECT),
    Family('deploy-src-clones', 'drive', 'src/repos', _file_clones, "an hpc deploy fixture's relative root 'src'"),
    Family('deploy-r-clones', 'drive', 'r/repos', _file_clones, "an hpc deploy fixture's rooted root '/r'"),
    Family('tmp-diag', 'drive', 'tmp_diag', _no_files, 'a diagnostic run with a rooted path; no producer found'),
    Family(
        'home-metrics',
        'home',
        'output',
        _every_file(_METRICS, 'a metrics line file'),
        'forgealarm recorded metrics at the cwd of a process started in the home dir',
    ),
    Family(
        'home-pytest-cache',
        'home',
        '.pytest_cache',
        _every_file(_PYTEST_CACHE, 'pytest cache content'),
        'a pytest session rooted at the home dir',
    ),
    Family(
        'jmag-designer-temp',
        'home',
        'JMAGDesignerTemp',
        _aged_unheld(7.0, ('designer', 'jcwrap', 'jmag')),
        'JMAG Designer leaves a ProjectTemp_* per project session and never removes it',
        glob='ProjectTemp_*',
    ),
)


@dataclass(frozen=True, slots=True)
class Found:
    """An instance of *family* at *path* under *base*; *kept* says why it stays, ``None`` when ours to remove."""

    family: Family
    path: Path
    kept: str | None
    base: Path


def find(drives: Sequence[Path], home: Path, families: Sequence[Family] = FAMILIES) -> list[Found]:
    """Every family instance present under each of *drives* or *home*, with its verdict; nothing is changed."""
    found: list[Found] = []
    for family in families:
        for base in drives if family.anchor == 'drive' else (home,):
            path = base / family.relative
            if family.glob:
                found.extend(_judged(family, entry, path) for entry in sorted(path.glob(family.glob)))
                continue
            if not path.exists() and not _linked(path):
                continue
            found.append(_judged(family, path, base))
    return found


def _judged(family: Family, path: Path, base: Path) -> Found:
    try:
        kept = 'a link or junction is never followed' if _linked(path) else family.ours(path)
    except OSError as exc:
        kept = f'unreadable: {exc.strerror or exc}'
    return Found(family, path, kept, base)


def _unlocked(path: Path) -> bool:
    """Whether *path* can be renamed and back: Windows refuses while any handle inside it is open."""
    probe = path.with_name(f'{path.name}.sweeping')
    try:
        path.rename(probe)
    except OSError:
        return False
    probe.rename(path)
    return True


def _prune(path: Path, stop: Path) -> None:
    """Remove *path*'s now-empty parents, up to (never including) *stop*."""
    for parent in path.parents:
        if parent == stop or stop not in parent.parents:
            return
        try:
            parent.rmdir()
        except OSError:
            return  # not empty, or held: it stays


def remove(found: Sequence[Found]) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Remove each instance proven ours, and its emptied parents; return ``(removed, [(kept, why)])``."""
    removed: list[Path] = []
    kept: list[tuple[Path, str]] = []
    for one in found:
        if one.kept is not None:
            kept.append((one.path, one.kept))
            continue
        if not one.path.exists():
            continue  # inside a family removed just before it (a suspect checkout in src/repos)
        if one.family.glob and not _unlocked(one.path):
            kept.append((one.path, 'locked: a handle inside it is open'))
            continue
        try:
            shutil.rmtree(one.path, onexc=writable_retry)  # a clone's git objects are read-only on Windows
        except OSError as exc:
            kept.append((one.path, f'held: {exc.strerror or exc}'))
            continue
        _prune(one.path, one.base)
        removed.append(one.path)
    return removed, kept
