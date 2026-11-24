"""The trees the family's suites left OUTSIDE every temp root, each named with its cause and removed only by proof.

A rooted or relative path a test once used without a base resolved against the drive root or the home dir
(user report 2026-11-24: ``C:/var/tmp``, ``C:/results/<2hex>``, ``C:/src/repos/product``, ``C:/r/repos``,
``C:/tmp_diag``, ``~/output``, ``~/.pytest_cache``). Each cause is fixed at its source; what it already wrote
stays until a host removes it, and that is this module: :data:`FAMILIES` is the set, as data.

A FAMILY IS REMOVED ONLY WHEN ITS CONTENT PROVES IT OURS (:attr:`Family.ours`): a drive-root ``src/repos`` is a
person's work unless every checkout in it was cloned from a ``file://`` url, as only a test fixture does; a
family whose origin was never traced is NAMED and never removed. A link or junction is never followed or removed.
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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from dev_lab.dev.testtemp import writable_retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

__all__ = ['FAMILIES', 'Family', 'Found', 'find', 'remove']

_OBJECT: Final = re.compile(r'^[0-9a-f]{2}/[0-9a-f]{64}$')
_METRICS: Final = re.compile(r'^logs/\d{2}/\d{2}/\d{2}/metrics/[a-z_-]+\.jsonl$')
_FILE_URL: Final = re.compile(r'^\s*url\s*=\s*file://', re.MULTILINE)
_PYTEST_CACHE: Final = 'pytest cache directory'
_UNTRACED: Final = 'origin never traced: named for a person to review, never removed'


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
    return None


def _pytest_cache(path: Path) -> str | None:
    readme = path / 'README.md'
    if readme.is_file() and _PYTEST_CACHE in readme.read_text(encoding='utf-8', errors='replace'):
        return None
    return 'no pytest cache README: not a pytest cache'


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
    try:
        import psutil  # noqa: PLC0415 -- a transitive dependency; its absence keeps every aged entry
    except ImportError:
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


def _untraced(_path: Path) -> str | None:
    return _UNTRACED


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
    Family('deploy-src-clones', 'drive', 'src/repos', _file_clones, "an hpc deploy fixture's relative root 'src'"),
    Family('deploy-r-clones', 'drive', 'r/repos', _file_clones, "an hpc deploy fixture's rooted root '/r'"),
    Family('tmp-diag', 'drive', 'tmp_diag', _untraced, 'a diagnostic run with a rooted path; no producer found'),
    Family(
        'home-metrics',
        'home',
        'output',
        _every_file(_METRICS, 'a metrics line file'),
        'forgealarm recorded metrics at the cwd of a process started in the home dir',
    ),
    Family('home-pytest-cache', 'home', '.pytest_cache', _pytest_cache, 'a pytest session rooted at the home dir'),
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
