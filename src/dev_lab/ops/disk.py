"""``python -m dev_lab.ops ... disk|clean``: measure a server's disk, and free only what regenerates.

The forge host's disk alarm (``dev_lab.supervise.pressure``) names this pair as its remedy; the integrator reaches
them through ``python -m dev_lab.dev.opsserver <server> disk|clean`` (2026-11-08: forge-a1 was days from full and
no door could even read ``df``).

``disk`` is read-only: ``df`` of the real mounts, the largest directories ``du -x`` finds on the mount holding the
Gitea data, the journal's usage and, where Docker is installed, ``docker system df``.

``clean`` frees ONLY what is regenerable or retention-bound, printing ``df`` before and after: the journal vacuumed
to a declared size, the apt package cache, Gitea's repo-archive and tmp caches (their CONTENTS, never the
directories), and Docker's build cache and dangling images. Everything Gitea cannot regenerate -- repositories, LFS,
attachments, avatars, packages, the database -- is :data:`PROTECTED`; a cache path that resolves into one of them is
refused before anything is removed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.log import emit

__all__ = [
    'CACHES',
    'DEFAULT_GITEA_DATA',
    'DEFAULT_JOURNAL_MAX_MB',
    'PROTECTED',
    'clean',
    'measure',
    'refuse_protected',
]

DEFAULT_GITEA_DATA: Final = '/var/lib/gitea/data'
DEFAULT_JOURNAL_MAX_MB: Final = 500
#: Gitea's regenerable caches, relative to its data directory: emptied, never removed.
CACHES: Final = ('repo-archive', 'tmp')
#: What Gitea cannot regenerate, relative to its data directory: never touched by ``clean``.
PROTECTED: Final = (
    'gitea-repositories',
    'repositories',
    'lfs',
    'attachments',
    'avatars',
    'repo-avatars',
    'packages',
    'gitea.db',
)
_DU_TOP: Final = 25

Runner = Callable[[Sequence[str]], tuple[int, str]]


def _run(argv: Sequence[str]) -> tuple[int, str]:
    done = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=900)
    return done.returncode, (done.stdout + done.stderr).strip()


def _say(runner: Runner, argv: Sequence[str]) -> int:
    code, out = runner(argv)
    emit(f'$ {" ".join(argv)}\n{out}')
    return code


def _df(runner: Runner) -> None:
    _say(runner, ['df', '-h', '-x', 'tmpfs', '-x', 'devtmpfs', '-x', 'overlay'])


def _largest(du_output: str, top: int = _DU_TOP) -> list[str]:
    """``du -xk`` lines, largest first, sized in GB."""
    rows = []
    for line in du_output.splitlines():
        size, _, path = line.partition('\t')
        if size.isdigit():
            rows.append((int(size), path))
    return [f'{size / 1024**2:8.2f} GB  {path}' for size, path in sorted(rows, reverse=True)[:top]]


def measure(gitea_data: str = DEFAULT_GITEA_DATA, *, runner: Runner = _run, has_docker: bool | None = None) -> int:
    """Print the server's disk picture; read-only. Exit 0."""
    _df(runner)
    code, mount = runner(['df', '--output=target', gitea_data])
    target = mount.splitlines()[-1].strip() if code == 0 and mount else '/'
    _, du = runner(['du', '-xk', '--max-depth=2', target])
    emit(f'largest under {target} (du -x):\n' + '\n'.join(_largest(du)))
    _say(runner, ['journalctl', '--disk-usage'])
    if has_docker if has_docker is not None else shutil.which('docker'):
        _say(runner, ['docker', 'system', 'df'])
    return 0


def refuse_protected(gitea_data: Path, cache: Path) -> str | None:
    """Why *cache* may not be emptied (inside or above a :data:`PROTECTED` path, or outside the data dir), else None."""
    root, path = gitea_data.resolve(), cache.resolve()
    if not path.is_relative_to(root) or path == root:
        return f'{cache} is not a cache inside {gitea_data}'
    for name in PROTECTED:
        kept = (root / name).resolve()
        if path == kept or path.is_relative_to(kept) or kept.is_relative_to(path):
            return f'{cache} overlaps {kept}, which Gitea cannot regenerate'
    return None


def _empty(directory: Path) -> int:
    """Remove the contents of *directory* (never the directory); the bytes freed."""
    freed = 0
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            freed += sum(f.stat().st_size for f in entry.rglob('*') if f.is_file() and not f.is_symlink())
            shutil.rmtree(entry)
        else:
            freed += entry.lstat().st_size
            entry.unlink()
    return freed


def clean(
    gitea_data: str = DEFAULT_GITEA_DATA,
    journal_max_mb: int = DEFAULT_JOURNAL_MAX_MB,
    *,
    runner: Runner = _run,
    has_docker: bool | None = None,
) -> int:
    """Free the regenerable and retention-bound; ``df`` before and after. Exit 0, or 2 when a cache was refused."""
    data = Path(gitea_data)
    caches = [data / name for name in CACHES]
    if refused := [why for cache in caches if (why := refuse_protected(data, cache))]:
        emit('clean: refused -- ' + '; '.join(refused), err=True)
        return 2
    emit('before:')
    _df(runner)
    _say(runner, ['journalctl', f'--vacuum-size={int(journal_max_mb)}M'])
    _say(runner, ['apt-get', 'clean'])
    for cache in caches:
        if cache.is_dir():
            emit(f'{cache}: freed {_empty(cache) / 1024**2:.1f} MB')
    if has_docker if has_docker is not None else shutil.which('docker'):
        _say(runner, ['docker', 'builder', 'prune', '-f'])
        _say(runner, ['docker', 'image', 'prune', '-f'])
    emit('after:')
    _df(runner)
    return 0
