"""SALVAGE and ORPHAN doors behind ``python -m dev_lab.dev.worktrees --salvage NAME`` and ``--reap-orphans``.

Wall 2026-11-24 (a user-ruled cleanup of ~150 old worktrees): saving a dirty tree's work as a COMMIT ran the lint
hooks, which judged scratch probes as a landing and refused every one without naming a door; and ``*.reclaiming``
directories -- deletions :func:`dev_lab.dev.reclaim._removed` moved aside whose git record then vanished -- were
refused by ``--remove`` because git lists no such tree, with no door at all.

* :func:`salvage` SNAPSHOTS a tree -- tracked and untracked, what git ignores excluded -- into a commit on
  ``salvage/<name>`` by plumbing: ``write-tree`` from a TEMPORARY index, ``commit-tree``, ``update-ref``. A
  snapshot is a RECORD, not a landing, so no hook judges it; the tree, its index and its branch are untouched and
  nothing is pushed. A process holding the tree refuses it, by pid.
* :func:`salvaged` is true when a tree's content IS its salvage commit's: ``--remove`` then needs neither the
  clean-tree judgement nor the quiet wait -- the salvage is not a live session, and an edit after it is.
* :func:`reap_orphans` removes a directory under the worktree home that git does not list and whose ``.git``
  points at a vanished gitdir, once every file in it that git does not ignore is a blob some ref reaches; else it
  is kept with the first such file named.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.census import processes

from dev_lab.dev.checkout import worktrees
from dev_lab.dev.liverun import Census, describe, removal_holders
from dev_lab.dev.reclaim import _removed, repository_at
from dev_lab.dev.worktree_outputs import linked

__all__ = ['BRANCH', 'reap_orphans', 'salvage', 'salvaged', 'snapshot']

#: The branch a tree's salvage lives on: ``salvage/<tree name>``.
BRANCH: Final = 'salvage/{name}'

_GIT: Final = 'git'
_TIMEOUT_S: Final = 600


def _git(cwd: Path, *args: str, index: Path | None = None, stdin: str | None = None) -> str | None:
    """``git <args>`` in *cwd*, optionally on a temporary *index*; stdout, or ``None`` when git failed."""
    env = dict(os.environ, GIT_INDEX_FILE=str(index)) if index is not None else None
    try:
        done = _door.run(
            [_GIT, *args],
            cwd=cwd,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=_TIMEOUT_S,
        )
    except (OSError, ValueError):
        return None
    return done.stdout if done.returncode == 0 else None


def snapshot(tree: Path) -> str | None:
    """The tree object of *tree*'s content -- HEAD, its edits and its untracked, not-ignored files; ``None``: unread.

    Built in a temporary index so the tree's own index is never touched; a submodule records its checked-out sha.
    """
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / 'index'
        if _git(tree, 'read-tree', 'HEAD', index=index) is None:
            return None
        if _git(tree, 'add', '--all', '--ignore-errors', index=index) is None:  # a pathspec trips ignored dirs
            return None
        made = _git(tree, 'write-tree', index=index)
    return made.strip() if made else None


def _rev(root: Path, ref: str) -> str:
    return (_git(root, 'rev-parse', '--verify', '--quiet', ref) or '').strip()


def salvaged(tree: Path, name: str) -> bool:
    """True when *tree*'s content is exactly its salvage commit's: removing it loses nothing."""
    recorded = _rev(tree, f'{BRANCH.format(name=name)}^{{tree}}')
    return bool(recorded) and snapshot(tree) == recorded


def _salvageable(main: Path, name: str, census: Census) -> Path | str:
    """Linked tree *name* when it may be salvaged; else why not."""
    tree = linked(main, name)
    if isinstance(tree, str):
        return tree
    if live := removal_holders(tree, census=census):
        return f'the tree is live\n{describe(live)}'
    branch = BRANCH.format(name=name)
    if (_git(tree, 'symbolic-ref', '--quiet', 'HEAD') or '').strip() == f'refs/heads/{branch}':
        return f'{branch} is checked out in the tree; switch it back to its lane first'
    return tree


def salvage(root: Path, name: str, *, census: Census = processes) -> tuple[bool, str]:
    """THE SALVAGE DOOR: record linked tree *name*'s work on ``salvage/<name>``; ``(salvaged, the line)``."""
    main = root.resolve()
    tree = _salvageable(main, name, census)
    if isinstance(tree, str):
        first, _, rest = tree.partition('\n')
        return False, f'refused  {name}: {first}; nothing was salvaged' + (f'\n{rest}' if rest else '')
    branch = BRANCH.format(name=name)
    head, made = _rev(tree, 'HEAD'), snapshot(tree)
    if not head or not made:
        return False, f'refused  {name}: git could not snapshot {tree}; nothing was salvaged'
    previous = _rev(main, f'refs/heads/{branch}')
    if made == _rev(main, f'{head}^{{tree}}'):
        return False, f'refused  {name}: nothing to salvage -- its content is its HEAD {head[:10]}'
    if previous and made == _rev(main, f'{previous}^{{tree}}'):
        return True, f'salvaged {name} -> {branch} {previous[:10]} (already recorded)'
    parents = ['-p', head] + (['-p', previous] if previous else [])
    message = f'chore(salvage): {name} uncommitted work\n'
    sha = (_git(main, 'commit-tree', made, *parents, stdin=message) or '').strip()
    if not sha or _git(main, 'update-ref', f'refs/heads/{branch}', sha, previous or '0' * len(sha)) is None:
        return False, f'refused  {name}: git could not record the snapshot; nothing was salvaged'
    changed = (_git(main, 'diff', '--name-only', '--no-renames', head, sha) or '').splitlines()
    return True, f'salvaged {name} -> {branch} {sha[:10]} ({len(changed)} files)'


def _vanished(directory: Path) -> bool:
    """True when *directory*'s ``.git`` is a gitfile naming a gitdir that no longer exists."""
    link = directory / '.git'
    try:
        text = link.read_text(encoding='utf-8').strip() if link.is_file() else ''
    except OSError:
        return False
    target = text.removeprefix('gitdir:').strip() if text.startswith('gitdir:') else ''
    return bool(target) and not Path(target).exists()


def _orphans(main: Path) -> Iterator[Path]:
    home = main / '.claude' / 'worktrees'
    registered = {path.resolve() for path, _ in worktrees(main) or ()}
    for directory in sorted(home.iterdir()) if home.is_dir() else ():
        if directory.is_dir() and directory.resolve() not in registered and _vanished(directory):
            yield directory


def _unheld_file(main: Path, directory: Path, reachable: frozenset[str]) -> str | None:
    """The first not-ignored file of *directory* no reachable blob holds; ``''`` when none; ``None``: unread."""
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / 'index'
        where = (f'--git-dir={main / ".git"}', f'--work-tree={directory}')
        listed = _git(directory, *where, 'ls-files', '--others', '--exclude-standard', '-z', index=index)
        if listed is None:
            return None
        files = [name for name in listed.split('\0') if name and name != '.git']
        if not files:
            return ''
        hashed = _git(directory, *where, 'hash-object', '--stdin-paths', stdin='\n'.join(files) + '\n', index=index)
    if hashed is None:
        return None
    return next((path for path, blob in zip(files, hashed.split(), strict=False) if blob not in reachable), '')


def _reachable_blobs(main: Path) -> frozenset[str] | None:
    """Every blob a ref reaches in *main* and in each submodule gitdir under ``.git/modules``; ``None``: unread."""
    modules = main / '.git' / 'modules'
    gitdirs = [main / '.git', *(head.parent for head in modules.rglob('HEAD') if (head.parent / 'objects').is_dir())]
    blobs: set[str] = set()
    for gitdir in gitdirs:
        listed = _git(main, f'--git-dir={gitdir}', 'rev-list', '--objects', '--all', '--filter=object:type=blob')
        if listed is None:
            return None
        blobs.update(line.split(maxsplit=1)[0] for line in listed.splitlines() if line)
    return frozenset(blobs)


def reap_orphans(root: Path, *, census: Census = processes) -> tuple[str, ...]:
    """THE ORPHAN DOOR: remove every orphan tree directory whose content some ref reaches; one line each."""
    main = root.resolve()
    orphans = list(_orphans(main))
    if not orphans:
        return ()
    reachable = _reachable_blobs(main)
    if reachable is None:
        return (f'refused  git could not list the reachable blobs of {main}; nothing was removed',)
    lines = []
    for directory in orphans:
        if live := removal_holders(directory, census=census):
            lines.append(f'kept     {directory}  (live; nothing was deleted)\n{describe(live)}')
            continue
        unheld = _unheld_file(main, directory, reachable)
        if unheld is None:
            lines.append(f'kept     {directory}  (git could not read its files; nothing was deleted)')
        elif unheld:
            lines.append(f'kept     {directory}  ({unheld} is held by no reachable object; nothing was deleted)')
        elif refused := repository_at(main, directory) or _removed(directory):
            lines.append(refused.replace('{label}', str(directory)))
        else:
            lines.append(f'removed  {directory}  (an orphan: its gitdir vanished, every file reachable)')
    return tuple(lines)
