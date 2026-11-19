"""WORKTREE OUTPUTS GO HOME: before a linked worktree is removed, its run outputs move into the main checkout.

A worktree's WORK is never saved aside (D31, user 2026-11-17, restating 2026-11-05): it is MERGED (committed on
its branch and landed through a PR) or the tree is CLEANED when it holds nothing unlanded
(:func:`dev_lab.dev.reclaim.unlanded_work`). What this module moves is only what a run PRODUCED: the declared
output directories.

THE INCIDENTS IT ENCODES (a consumer, 2026-10-04, 10-12, 10-18, 10-21):

* removals deleted run archives twice -- a ``;`` let ``git worktree remove`` run after the move had failed. So
  :func:`home_outputs` is VERIFIED and its caller chains the removal on it;
* a COPY of ~90 GB of outputs nearly filled the volume, and whole ``.venv`` copies travelled. So a file is MOVED
  by ``os.replace`` (a rename, atomic on one volume), a tree on ANOTHER volume is refused rather than copied, and
  a directory holding ``pyvenv.cfg`` never travels.

WHAT MOVES, as data: ``[tool.dev_lab.worktrees] archive-outputs`` of the main checkout's ``pyproject.toml``
(default :data:`OUTPUTS`), each a directory relative to a checkout whose files land at the SAME relative path in
the main checkout -- a dated ``output/logs/<yy>/<mm>/<dd>/`` stays dated. An identical file already there is
skipped; a differing one lands beside it as ``<name>.<worktree>``; when that name is taken by different bytes
too, the move is refused and the tree kept. The retired ``archive-to`` key is refused by name.
"""

from __future__ import annotations

import filecmp
import os
import tomllib
from pathlib import Path
from typing import Final

from dev_lab.dev.checkout import git_out, worktrees
from dev_lab.dev.family import declared_table
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'OUTPUTS',
    'home_outputs',
    'linked',
    'unheld_head',
    'volume',
    'worktrees_door',
]

#: The family default of what a worktree's runs produce and the main checkout keeps (``docs-src/dev/output-tree``).
OUTPUTS: Final = ('output/logs',)
_VENV_MARK: Final = 'pyvenv.cfg'
#: The key D31 retired: a worktree's work is merged or cleaned, never saved under ``output/``.
_RETIRED_KEY: Final = 'archive-to'


def worktrees_door(main: Path, flags: str) -> str:
    """The runnable ``worktrees`` door of checkout *main* with *flags*: what a printed line hands out."""
    where = main.as_posix()
    where = f'"{where}"' if any(c.isspace() for c in where) else where
    return f'{running_interpreter()} -m dev_lab.dev.worktrees --root {where} {flags}'


def volume(path: Path) -> int:
    """The volume *path* lives on; a rename is a move only within one."""
    return path.stat().st_dev


def _declared(main: Path) -> tuple[str, ...]:
    manifest = main / 'pyproject.toml'
    table: dict[str, object] = {}
    if manifest.is_file():
        with manifest.open('rb') as handle:
            table = declared_table(tomllib.load(handle), 'worktrees', {})
    if _RETIRED_KEY in table:
        msg = (
            f'[tool.dev_lab.worktrees] {_RETIRED_KEY} in {manifest} is retired (D31, 2026-11-17): a worktree is '
            'merged or cleaned, its work never saved aside -- delete the line'
        )
        raise ValueError(msg)
    outputs = table.get('archive-outputs', list(OUTPUTS))
    if not isinstance(outputs, list) or not all(isinstance(one, str) for one in outputs):
        msg = f'[tool.dev_lab.worktrees] archive-outputs (list of str) in {manifest}'
        raise ValueError(msg)
    return tuple(outputs)


def unheld_head(tree: Path) -> str:
    """The detached HEAD sha no ref contains, or ``''`` -- a branch's commits survive the tree in its ref."""
    if (git_out(tree, 'branch', '--show-current') or '').strip():
        return ''
    head = (git_out(tree, 'rev-parse', 'HEAD') or '').strip()
    holders = git_out(tree, 'for-each-ref', '--contains', head, '--format=%(refname)')
    if holders is None:
        msg = f'git could not say which refs contain {head} in {tree}'
        raise RuntimeError(msg)
    return '' if holders.strip() else head


def _files(top: Path) -> list[Path]:
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(top):
        here = Path(directory)
        dirnames[:] = sorted(name for name in dirnames if not (here / name / _VENV_MARK).is_file())
        if (here / _VENV_MARK).is_file():
            continue
        found += [here / name for name in sorted(filenames)]
    return found


def _move(main: Path, tree: Path, name: str, outputs: tuple[str, ...]) -> tuple[list[Path], ...]:
    """Rename every file under *outputs* of *tree* to the same path in *main*: moved, identical, renamed, conflicts."""
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
                source.replace(landing)  # a rename: same volume, checked by the caller
                (renamed if landing == beside else moved).append(landing.relative_to(main))
            elif filecmp.cmp(source, beside, shallow=False):
                identical.append(beside.relative_to(main))
            else:
                conflicts.append(rel)
    return moved, identical, renamed, conflicts


def linked(main: Path, name: str) -> Path | str:
    """The one LINKED worktree of *main* named *name* (never the main checkout), resolved; else why not."""
    registered = worktrees(main)
    if registered is None:
        return f'git could not list the worktrees of {main}'
    found = [path.resolve() for path, _ in registered[1:] if path.name == name]
    return found[0] if len(found) == 1 else f'{len(found)} linked worktrees of {main} are named {name!r}'


def home_outputs(main: Path, tree: Path) -> str:
    """Move *tree*'s outputs into *main* and VERIFY each landed; ``''`` when verified, else why not.

    *tree* is a linked worktree or an orphan directory of *main*. Nothing outside the outputs is touched.
    """
    main = main.resolve()
    try:
        outputs = _declared(main)
        if any((tree / top).exists() for top in outputs) and volume(tree) != volume(main):
            return 'outputs not moved home: the tree is on another volume, where a move is a copy'
        moved, identical, renamed, conflicts = _move(main, tree, tree.name, outputs)
    except (OSError, ValueError) as error:
        return f'outputs not moved home: {error}'
    if conflicts:
        return f'outputs not moved home: both names taken by different bytes for {conflicts[0]}'
    missing = [rel for rel in (*moved, *renamed, *identical) if not (main / rel).is_file()]
    if missing:
        return f'outputs not verified home: {missing[0]} is not there'
    return ''
