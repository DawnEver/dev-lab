"""DISK USAGE -- an account's quota read off the cluster's filesystem, and what one path holds.

``mmlsquota`` (GPFS, Ada's home filesystem) reports blocks in KB and files against their quotas; on Ada
the FILE quota is the nearer ceiling (2026-10-13: 26-48% of 2 M files against under 2% of 1000 GB).
``mmlsquota`` lives in ``/usr/lpp/mmfs/bin``, which cron's PATH does not name, so that path is tried too;
where it is absent the Linux ``quota -w`` is the fallback. Unreadable is ``None``, never a zero. Off a
cluster the usage is the disk the checkout sits on. Read by :mod:`dev_lab.dev.retention` and, as the
``files`` supply of a Slurm account, by :mod:`dev_lab.dev.forgeslurm`.

STILL OVER, THE ALARM NAMES THE LIMIT AND THE CONSUMERS (user ruling 2026-10-14). Ada carol sat at its
2,020,000-file hard limit with 43 GB of 1 TB used, and the alarm said only "still near its quota" -- not
which limit, nor that 1.34 M of the files were one experiment directory the forge does not own.
:func:`pressure_text` states bytes and files used/limit, which one binds, and the biggest directories of
the home by FILE COUNT (:func:`consumers`), each one outside :data:`FORGE_OWNED` marked "not forge-owned,
not touched".
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door

__all__ = [
    'FORGE_OWNED',
    'Usage',
    'consumers',
    'count_files',
    'extended',
    'files_first',
    'measure',
    'parse_mmlsquota',
    'parse_quota',
    'pressure_text',
    'read_usage',
    'remove_tree',
    'storage_text',
    'writable',
]

# the block grace is ``none`` or ``7 days`` -- one word or two -- so it is read up to the bar
_QUOTA_ROW: Final = re.compile(r'^\S+\s+\S+\s+USR\s+(\d+)\s+(\d+)\s+\d+\s+\d+[^|\n]*\|\s*(\d+)\s+(\d+)', re.MULTILINE)
# ``quota -w``: filesystem, KB used (``*`` when over), quota, limit, [grace], files used, quota, limit
_LINUX_ROW: Final = re.compile(r'^\s*/\S+\s+(\d+)\*?\s+(\d+)\s+\d+\s+(?:\S+\s+)??(\d+)\*?\s+(\d+)\s+\d+', re.MULTILINE)
_MMLSQUOTA: Final = ('mmlsquota', '/usr/lpp/mmfs/bin/mmlsquota')

#: The directories of an account home the forge owns (:mod:`dev_lab.dev.retention`); nothing else is touched.
FORGE_OWNED: Final = ('ci',)


@dataclass(frozen=True)
class Usage:
    """Bytes and files held against their quota; ``files`` is ``None`` where no file quota is read."""

    used: int
    limit: int
    files: int | None
    files_limit: int | None

    def fraction(self, freed: int = 0, freed_files: int = 0) -> float:
        """The nearer of the two ceilings, as a fraction, after *freed* bytes and *freed_files* files."""
        parts = [(self.used - freed) / self.limit] if self.limit else []
        if self.files is not None and self.files_limit:
            parts.append((self.files - freed_files) / self.files_limit)
        return max(parts, default=0.0)

    @property
    def files_left(self) -> float | None:
        """Files the quota still takes, never below 0; ``None`` when no file quota is read."""
        if self.files is None or not self.files_limit:
            return None
        return float(max(0, self.files_limit - self.files))

    def binding(self, freed: int = 0, freed_files: int = 0) -> str:
        """``'files'`` or ``'bytes'``: the ceiling :meth:`fraction` is nearer to."""
        if self.files is None or not self.files_limit:
            return 'bytes'
        files = (self.files - freed_files) / self.files_limit
        return 'files' if files >= ((self.used - freed) / self.limit if self.limit else 0.0) else 'bytes'

    def after(self, freed: int, freed_files: int) -> list[str]:
        """``usage bytes ... -> ...`` and, with a file quota, ``usage files ... -> ...``: now, then once freed."""
        gb, left = 1024**3, self.used - freed
        lines = [f'usage bytes {self.used / gb:.1f}/{self.limit / gb:.1f} GB -> {left / gb:.1f} GB']
        if self.files is not None and self.files_limit:
            now, rest, cap = self.files, self.files - freed_files, self.files_limit
            lines.append(f'usage files {now}/{cap} ({now / cap:.1%}) -> {rest} ({rest / cap:.1%})')
        return lines

    def text(self) -> str:
        """``bytes <used>/<limit> GB, files <used>/<limit>``; files ``unread`` when no file quota is read."""
        gb = 1024**3
        files = f'{self.files}/{self.files_limit}' if self.files is not None and self.files_limit else 'unread'
        return f'bytes {self.used / gb:.1f}/{self.limit / gb:.1f} GB, files {files}'


def _usage(hit: re.Match[str] | None) -> Usage | None:
    if hit is None:
        return None
    used, limit, files, files_limit = (int(v) for v in hit.groups())
    return Usage(used * 1024, limit * 1024, files, files_limit)


def parse_mmlsquota(text: str) -> Usage | None:
    """The ``USR`` row of ``mmlsquota`` (KB blocks, then files); ``None`` when there is none."""
    return _usage(_QUOTA_ROW.search(text))


def parse_quota(text: str) -> Usage | None:
    """The first filesystem row of Linux ``quota -w`` (KB blocks, then files); ``None`` when there is none."""
    return _usage(_LINUX_ROW.search(text))


def read_usage(home: Path, *, cluster: bool, run: Callable[..., Any] = _door.run) -> Usage | None:
    """The account quota on a cluster (``mmlsquota``, else ``quota -w``; ``None`` unreadable), else *home*'s disk."""
    if not cluster:
        disk = shutil.disk_usage(home)
        return Usage(disk.used, disk.total, None, None)
    readers = [((name,), parse_mmlsquota) for name in _MMLSQUOTA] + [(('quota', '-w'), parse_quota)]
    for argv, parse in readers:
        if found := shutil.which(argv[0]) or (Path(argv[0]).is_file() and argv[0]):
            done = run(
                [found, *argv[1:]], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False
            )
            return parse(done.stdout or '')
    return None


def measure(path: Path) -> tuple[int, int]:
    """The bytes and files *path* holds, symlinks not followed."""
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size, 1
    size, files = 0, 0
    for here, dirs, names in os.walk(path):
        for name in (*names, *dirs):
            try:
                size += (Path(here) / name).lstat().st_size
            except OSError:
                continue
            files += 1
    return size, files + 1


def count_files(path: Path) -> int:
    """How many entries *path* holds, itself included -- names only, nothing ``stat``-ed: the cheap count."""
    if not path.is_dir() or path.is_symlink():
        return 1
    return 1 + sum(len(dirs) + len(names) for _, dirs, names in os.walk(path))


def consumers(home: Path, *, count: Callable[[Path], int] = count_files, top: int = 8) -> list[tuple[Path, int, bool]]:
    """The *top* directories of *home* by file count, most first, each with whether the forge owns it.

    A forge-owned directory (:data:`FORGE_OWNED`) is counted per child, so ``ci/trees`` and ``ci/envs``
    are named apart; any other directory is one entry.
    """
    owned = [home / name for name in FORGE_OWNED]
    seen = [(p, False) for p in sorted(home.iterdir()) if p not in owned and p.is_dir() and not p.is_symlink()]
    seen += [(p, True) for root in owned if root.is_dir() for p in sorted(root.iterdir()) if p.is_dir()]
    counted = [(path, count(path), mine) for path, mine in seen]
    return sorted(counted, key=lambda row: -row[1])[:top]


def storage_text(usage: Usage | None) -> str:
    """What a cluster host card says of its home: used/limit of each, AT THE FILE LIMIT when full; ``unread``."""
    if usage is None:
        return 'unread (no mmlsquota or quota answered): files are not capped by admission'
    full = ' -- AT THE FILE LIMIT: claims nothing' if usage.files_left == 0 else ''
    return f'{usage.text()}{full}'


def pressure_text(usage: Usage | None, freed: tuple[int, int], home: Path | None) -> str:
    """The storage alarm's body: what was freed, which limit binds, used/limit of each, *home*'s biggest consumers."""
    head = f'freed {freed[0]} bytes and {freed[1]} files; still over [retention] pressure'
    if usage is None:
        return f'{head}; the quota is unreadable'
    lines = [f'{head} on {usage.binding(*freed)}: {usage.text()}']
    heavy = consumers(home) if home is not None else []
    lines += [f'- {path}: {n} files' + ('' if mine else ' (not forge-owned, not touched)') for path, n, mine in heavy]
    return '\n'.join(lines)


def files_first[T](items: Sequence[T], path: Callable[[T], Path]) -> list[T]:
    """*items* grouped by their path's NAME (a run with its tree), the group holding the most files first.

    The sort is stable, so groups that tie keep the order they came in (retention's: oldest first).
    """
    groups: dict[str, list[T]] = {}
    for item in items:
        groups.setdefault(path(item).name, []).append(item)
    held = {name: sum(count_files(path(i)) for i in group if path(i).exists()) for name, group in groups.items()}
    return [item for name in sorted(groups, key=lambda name: -held[name]) for item in groups[name]]


def extended(path: Path) -> str:
    r"""*path* as the OS opens it past MAX_PATH: ``\\?\<absolute>`` on Windows, the plain absolute path elsewhere."""
    full = str(Path(path).absolute())
    if os.name != 'nt' or full.startswith('\\\\'):  # already extended, or a UNC share left as given
        return full
    return f'\\\\?\\{full}'


def remove_tree(path: Path) -> None:
    """Remove the directory *path* whatever it holds: a path past MAX_PATH, a read-only file; absent is done.

    THE ONE REMOVAL PATH (2026-10-21): a producer's tree held a ``.venv`` deeper than 260 characters,
    ``git worktree remove`` failed with ``Filename too long`` and left debris that blocked the next add. Through
    :func:`extended` no host setting (``LongPathsEnabled``, ``core.longpaths``) is needed.
    """
    target = extended(path)
    if os.path.lexists(target):
        shutil.rmtree(target, onexc=writable)


def writable(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    """``rmtree``'s ``onexc``: make *path* writable and retry -- a read-only git object on Windows."""
    Path(path).chmod(stat.S_IWRITE)  # a read-only git object on Windows
    func(path)
