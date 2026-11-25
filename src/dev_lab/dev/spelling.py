"""US-SPELLING-IS-CHECKED: typos, in locale en-us, over the identifiers, file names, docs and memory of a tree.

User ruling 2026-11-24 (v1-migration D35): the family spells US English. ``verify`` runs this module as a lint
step (:data:`dev_lab.dev.verifysteps.LINT_STEPS`), so every verify in every family repo checks it.

ONE CONFIG, DEV-LAB'S: :data:`CONFIG` ships in this package and every repo's run passes it to typos; no repo
carries a copy, so the vocabulary moves for the whole family at one relock.

WHAT IS CHECKED: every file git would track -- tracked, plus untracked and not ignored -- except dated memory
written before the ruling (:data:`MEMORY_CUTOFF`). A memory entry is immutable history, so the ruling is not
applied to it backwards; an entry written on or after the cutoff is checked like any other file.

Exit codes follow :func:`dev_lab.dev.reports.read_lint`: ``0`` clean, ``1`` findings (printed), ``2`` the
checker did not run. ``--write`` lets typos fix every unambiguous finding in place.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import sysconfig
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import IO, Final

import lab_commons.launch as _door

__all__ = ['CLEAN', 'CONFIG', 'ERRORED', 'FOUND', 'INSTALL_DOOR', 'MEMORY_CUTOFF', 'binary', 'check', 'checked', 'main']

#: The family's one typos config.
CONFIG: Final = Path(__file__).with_name('typos.toml')

#: The ruling's date: dated memory before it is history and is not checked.
MEMORY_CUTOFF: Final = date(2026, 11, 24)

CLEAN: Final = 0
FOUND: Final = 1
ERRORED: Final = 2

#: What a missing checker is fixed by: typos ships in the ``dev-lab[test]`` kit.
INSTALL_DOOR: Final = 'python -m dev_lab.dev.dep --sync (typos ships in the dev-lab[test] extra)'

_DATED: Final = re.compile(r'^\.claude/memory/(\d{4})/(\d{2})/(\d{2})/')
_GIT: Final = shutil.which('git') or 'git'
_TYPOS_FOUND: Final = 2


def checked(paths: Iterable[str]) -> tuple[str, ...]:
    """*paths* (repo-relative, ``/``-separated) without the dated memory written before :data:`MEMORY_CUTOFF`."""

    def kept(path: str) -> bool:
        dated = _DATED.match(path)
        return dated is None or date(*map(int, dated.groups())) >= MEMORY_CUTOFF

    return tuple(path for path in paths if kept(path))


def binary() -> Path | None:
    """The typos installed in THIS interpreter's environment, so the checker is the locked one."""
    name = 'typos.exe' if sys.platform == 'win32' else 'typos'
    path = Path(sysconfig.get_path('scripts')) / name
    return path if path.is_file() else None


def _files(root: Path) -> tuple[str, ...]:
    done = _door.run(
        [_GIT, '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=120,
    )
    return tuple(path for path in done.stdout.split('\0') if path and (root / path).is_file())


def check(root: Path, *, handle: IO[str], write: bool = False) -> int:
    """Run typos over *root*'s checked files, its findings into *handle*; ``CLEAN``, ``FOUND`` or ``ERRORED``."""
    typos = binary()
    if typos is None:
        handle.write(f'typos is not installed in {sys.prefix}: {INSTALL_DOOR}\n')
        return ERRORED
    files = checked(_files(root))
    done = _door.run(
        [str(typos), '--config', str(CONFIG), '--format', 'brief', '--file-list', '-', *(('--write-changes',) * write)],
        cwd=root,
        input='\n'.join(files),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=600,
    )
    handle.write(done.stdout + done.stderr)
    if done.returncode == 0:
        return CLEAN
    return FOUND if done.returncode == _TYPOS_FOUND else ERRORED


def main(argv: list[str] | None = None) -> int:
    """Check the tree at the working directory; ``--write`` fixes the unambiguous findings first."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.spelling', description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true', help='fix every unambiguous finding in place')
    parsed = parser.parse_args(argv)
    return check(Path.cwd(), handle=sys.stdout, write=parsed.write)


if __name__ == '__main__':
    raise SystemExit(main())
