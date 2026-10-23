"""WORKTREE-ARCHIVE: before a linked worktree is removed, its run outputs go HOME and its work is saved.

The door is ``python -m dev_lab.dev.worktrees --archive NAME`` -- a flag of the worktree door every
adopting repo already allows, so a consumer gets it by bumping lab-commons and regenerates no permission.

THE INCIDENTS IT ENCODES (a consumer, 2026-10-04, 10-12, 10-18, 10-21):

* removals deleted run archives twice -- a ``;`` let ``git worktree remove`` run after the move had failed.
  So this module NEVER removes: it reports the tree safe to remove, and removal is a separate explicit step;
* a COPY of ~90 GB of outputs nearly filled the volume, and whole ``.venv`` copies reached the archive. So a
  file is MOVED by ``os.replace`` (a rename, atomic on one volume), a tree on ANOTHER volume is refused rather
  than copied, and a directory holding ``pyvenv.cfg`` never travels;
* a removal raced another session's live tree. So a tree with any OCCUPANT (:func:`dev_lab.dev.liverun.
  occupants`: a process working in it, executing from it, or reading it) is refused before anything is written.

WHAT MOVES, as data: ``[tool.lab_commons.worktrees] archive-outputs`` of the main checkout's ``pyproject.toml``
(default :data:`OUTPUTS`), each a directory relative to a checkout whose files land at the SAME relative path in
the main checkout -- a dated ``output/logs/<yy>/<mm>/<dd>/`` stays dated. An identical file already there is
skipped (both copies stay; the main one is never touched); a differing one lands beside it as
``<name>.<worktree>``; when that name is taken by different bytes too, the file stays in the tree and the tree
is NOT safe.

WHAT IS SAVED: under ``archive-to`` (default :data:`ARCHIVE_TO`) ``/<yyyymmdd>/<worktree>/``: ``HEAD.txt`` (sha
and branch), ``dirty.patch`` (``git diff HEAD --binary``: every uncommitted tracked change) and ``untracked/``
(the untracked, non-ignored files, small by construction -- ignored ones are outputs or regenerable).
"""

from __future__ import annotations

import filecmp
import os
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.census import processes

from dev_lab.dev.checkout import git_out, worktrees
from dev_lab.dev.liverun import describe, occupants

if TYPE_CHECKING:
    from dev_lab.dev.liverun import Census

__all__ = ['ARCHIVE_TO', 'OUTPUTS', 'Archived', 'archive', 'volume']

#: The family default of what a worktree's runs produce and the main checkout keeps (``docs-src/dev/output-tree``).
OUTPUTS: Final = ('output/logs',)
#: Where the saved work of an archived tree goes, relative to the main checkout.
ARCHIVE_TO: Final = 'output/worktree-archive'
_VENV_MARK: Final = 'pyvenv.cfg'


@dataclass(frozen=True)
class Archived:
    """What :func:`archive` did to one worktree; every path relative to its checkout."""

    name: str
    saved: Path
    refused: str | None = None
    moved: tuple[Path, ...] = ()
    identical: tuple[Path, ...] = ()
    renamed: tuple[Path, ...] = ()
    conflicts: tuple[Path, ...] = ()

    @property
    def safe(self) -> bool:
        """Whether nothing the tree holds is lost by removing it now."""
        return self.refused is None and not self.conflicts

    def lines(self) -> tuple[str, ...]:
        """One report line per fact, then the verdict on removal."""
        if self.refused is not None:
            return (f'refused  {self.name}: {self.refused}; nothing was moved or written',)
        head = (
            f'archived {self.name}: {len(self.moved)} moved, {len(self.renamed)} renamed beside a differing'
            f' file, {len(self.identical)} identical skipped; work saved in {self.saved}'
        )
        tail = [f'  KEPT {path} (both names taken by different bytes)' for path in self.conflicts]
        verdict = (
            f'safe to remove: git worktree remove --force {self.name} (a separate, explicit step)'
            if self.safe
            else 'NOT safe to remove: the kept files above are in the tree only'
        )
        return (head, *tail, verdict)


def volume(path: Path) -> int:
    """The volume *path* lives on; a rename is a move only within one."""
    return path.stat().st_dev


def _declared(main: Path) -> tuple[tuple[str, ...], str]:
    manifest = main / 'pyproject.toml'
    table: dict[str, object] = {}
    if manifest.is_file():
        with manifest.open('rb') as handle:
            table = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get('worktrees', {})
    outputs, target = table.get('archive-outputs', list(OUTPUTS)), table.get('archive-to', ARCHIVE_TO)
    if not isinstance(outputs, list) or not all(isinstance(one, str) for one in outputs) or not isinstance(target, str):
        msg = f'[tool.lab_commons.worktrees] archive-outputs (list of str) / archive-to (str) in {manifest}'
        raise ValueError(msg)
    return tuple(outputs), target


def _in_venv(path: Path, top: Path) -> bool:
    """Whether *path* lies in a virtual environment below *top* (a directory holding ``pyvenv.cfg``)."""
    return any((parent / _VENV_MARK).is_file() for parent in (path, *path.parents) if parent.is_relative_to(top))


def _save(tree: Path, saved: Path) -> None:
    saved.mkdir(parents=True, exist_ok=True)
    head = (git_out(tree, 'rev-parse', 'HEAD') or '').strip()
    branch = (git_out(tree, 'branch', '--show-current') or '').strip() or '(detached)'
    (saved / 'HEAD.txt').write_text(f'{head}\n{branch}\n', encoding='utf-8')
    patch = git_out(tree, 'diff', 'HEAD', '--binary')
    if patch is None:
        msg = f'git could not diff {tree}'
        raise RuntimeError(msg)
    (saved / 'dirty.patch').write_text(patch, encoding='utf-8', newline='')
    for rel in filter(None, (git_out(tree, 'ls-files', '--others', '--exclude-standard', '-z') or '').split('\0')):
        source = tree / rel
        if source.is_file() and not _in_venv(source.parent, tree):
            target = saved / 'untracked' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _files(top: Path) -> list[Path]:
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(top):
        here = Path(directory)
        dirnames[:] = sorted(name for name in dirnames if not (here / name / _VENV_MARK).is_file())
        if (here / _VENV_MARK).is_file():
            continue
        found += [here / name for name in sorted(filenames)]
    return found


def archive(main: Path, name: str, *, census: Census = processes, today: date | None = None) -> Archived:
    """Move worktree *name*'s outputs into *main*, save its work, and say whether it is safe to remove."""
    main = main.resolve()
    outputs, target = _declared(main)
    saved = main / target / (today or datetime.now(UTC).astimezone().date()).strftime('%Y%m%d') / name
    registered = worktrees(main)
    if registered is None:
        return Archived(name, saved, refused=f'git could not list the worktrees of {main}')
    found = [path.resolve() for path, _ in registered[1:] if path.name == name]
    if len(found) != 1:
        return Archived(name, saved, refused=f'{len(found)} linked worktrees of {main} are named {name!r}')
    tree = found[0]
    if live := occupants(tree, census=census):
        return Archived(name, saved, refused=f'the tree is live:\n{describe(live)}')
    if volume(tree) != volume(main):
        return Archived(name, saved, refused='the tree is on another volume, where a move is a copy')
    _save(tree, saved)
    moved, identical, renamed, conflicts = [], [], [], []
    for rel_top in outputs:
        for source in _files(tree / rel_top):
            rel = source.relative_to(tree)
            home = main / rel
            beside = home.with_name(f'{home.name}.{name}')
            if home.exists() and filecmp.cmp(source, home, shallow=False):
                identical.append(rel)
            elif not home.exists() or not beside.exists():
                landing = beside if home.exists() else home
                landing.parent.mkdir(parents=True, exist_ok=True)
                source.replace(landing)  # a rename: same volume, checked above
                (renamed if landing == beside else moved).append(landing.relative_to(main))
            elif filecmp.cmp(source, beside, shallow=False):
                identical.append(beside.relative_to(main))
            else:
                conflicts.append(rel)
    return Archived(name, saved, None, tuple(moved), tuple(identical), tuple(renamed), tuple(conflicts))
