"""DISK USAGE -- an account's quota read off the cluster's filesystem, and what one path holds.

``mmlsquota`` (GPFS, Ada's home filesystem) reports blocks in KB and files against their quotas; on Ada
the FILE quota is the nearer ceiling (2026-10-13: 26-48% of 2 M files against under 2% of 1000 GB).
``mmlsquota`` lives in ``/usr/lpp/mmfs/bin``, which cron's PATH does not name, so that path is tried too.
Off a cluster the usage is the disk the checkout sits on. Read by :mod:`lab_commons.dev.retention`.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = ['Usage', 'measure', 'parse_mmlsquota', 'read_usage', 'writable']

_QUOTA_ROW: Final = re.compile(r'^\S+\s+\S+\s+USR\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\S+\s*\|\s*(\d+)\s+(\d+)', re.MULTILINE)
_MMLSQUOTA: Final = ('mmlsquota', '/usr/lpp/mmfs/bin/mmlsquota')


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


def parse_mmlsquota(text: str) -> Usage | None:
    """The ``USR`` row of ``mmlsquota`` (KB blocks, then files); ``None`` when there is none."""
    hit = _QUOTA_ROW.search(text)
    if hit is None:
        return None
    used, limit, files, files_limit = (int(v) for v in hit.groups())
    return Usage(used * 1024, limit * 1024, files, files_limit)


def read_usage(home: Path, *, cluster: bool, run: Callable[..., Any] = subprocess.run) -> Usage | None:
    """The account quota on a cluster (``mmlsquota``; ``None`` when unreadable), else *home*'s disk."""
    if not cluster:
        disk = shutil.disk_usage(home)
        return Usage(disk.used, disk.total, None, None)
    for name in _MMLSQUOTA:
        if found := shutil.which(name) or (Path(name).is_file() and name):
            done = run([found], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
            return parse_mmlsquota(done.stdout or '')
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


def writable(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    """``rmtree``'s ``onexc``: make *path* writable and retry -- a read-only git object on Windows."""
    Path(path).chmod(stat.S_IWRITE)  # a read-only git object on Windows
    func(path)
