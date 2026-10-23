"""The network half of :mod:`dev_lab.dev.dep`: every resolving command through the ONE retry door, and submodules.

NETWORK-RETRY-THEN-REPORT (2026-10-19, motronics): a ``uv sync`` of a git dependency failed once on forge auth
and was not retried, and a worktree's ``git submodule update`` from a LOCAL path was refused as ``transport
'file' not allowed`` and retried as if transient. :func:`run_change` routes by
:func:`~dev_lab.dev.netverb.is_network_verb`; :func:`init_submodules` opens the file transport for that
one command, only when a submodule really is local.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.netverb import is_network_verb, run_network_verb

__all__ = ['CHILD_WALL_S', 'init_submodules', 'run_change']

#: A HANG DETECTOR on the child process, not a performance bound. Thirty minutes is the wall the
#: family's `gate` tier already declares for a whole verdict run: a dependency change still running
#: past the wall of the tier that would be waiting on it is hung by the family's own definition,
#: whatever an install normally costs. No install here has been timed on an idle box, and a timing
#: from a busy one is not a property of the command.
CHILD_WALL_S: Final = 30 * 60


def run_change(
    argv: Sequence[str],
    *,
    run: Callable[..., Any],
    timeout: float,
    cwd: Path | None,
    environment: dict[str, str] | None,
) -> int:
    """*argv*'s exit code; a resolving command goes through the ONE retry door (NETWORK-RETRY-THEN-REPORT)."""
    if is_network_verb(argv):
        report = run_network_verb(argv, run=run, timeout=timeout, cwd=cwd, env=environment)
        if not report.ok:
            emit(f'[netverb] {report.remedy}', err=True)
        return report.returncode
    options: dict[str, Any] = {'check': False, 'timeout': timeout}
    if cwd is not None:
        options['cwd'] = cwd
    if environment is not None:
        options['env'] = environment
    return run(list(argv), **options).returncode


def _local_submodule_urls(root: Path) -> bool:
    """Whether any submodule of *root* is fetched from a LOCAL path -- git's ``file`` transport.

    The effective URL is the repo config's (``git submodule init`` copies it there, and a worktree shares
    it), so a ``.gitmodules`` naming the forge can still clone from ``<main>/.git/modules/...``.
    """
    urls = []
    for source in (['config'], ['config', '-f', str(root / '.gitmodules')]):
        done = _door.run(
            [shutil.which('git') or 'git', '-C', str(root), *source, '--get-regexp', r'^submodule\..*\.url$'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=60,
        )
        urls += [line.split(None, 1)[1] for line in done.stdout.splitlines() if ' ' in line]
    return any(_is_local(url) for url in urls)


def _is_local(url: str) -> bool:
    """A path or ``file://`` URL, never ``scheme://`` or scp-style ``host:path`` (a drive letter is a path)."""
    if url.startswith('file://'):
        return True
    if '://' in url:
        return False
    head, colon, _ = url.partition(':')
    return not colon or (len(head) == 1 and head.isalpha()) or '/' in head


def init_submodules(root: Path, *, dry_run: bool = False) -> str | None:
    """Initialise every submodule *root*'s commit records, through the network door; why it failed, else ``None``.

    A path dependency may point INTO a submodule (a product's engine under ``components/``, plan C5), so a
    checkout whose submodules were never initialised cannot be resolved: ``uv`` reports the path as not
    existing. MEASURED 2026-10-19 on a serve checkout of motronics-studio, which bootstrapped only after a
    manual ``git submodule update --init``. Every sync, bootstrap and lock therefore does this first.
    """
    if not (root / '.gitmodules').is_file():
        return None
    # 2026-10-19: a worktree's submodule cloned from `<main>/.git/modules/...` was refused as `transport 'file'
    # not allowed` (git's default since 2.38.1) and retried as transient. The opening is scoped to this one
    # command and only when a submodule really is local; a forge URL never needs it.
    opening = ['-c', 'protocol.file.allow=always'] if _local_submodule_urls(root) else []
    command = [shutil.which('git') or 'git', *opening, '-C', str(root), 'submodule', 'update', '--init', '--recursive']
    if dry_run:
        emit('would run: ' + ' '.join(command))
        return None
    report = run_network_verb(command, timeout=CHILD_WALL_S)
    return None if report.ok else f'submodules of {root} could not be initialised: {report.remedy}'
