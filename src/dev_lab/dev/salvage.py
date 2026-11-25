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
  clean-tree judgment nor the quiet wait -- the salvage is not a live session, and an edit after it is.
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

from dev_lab.dev.checkout import linked, worktrees
from dev_lab.dev.liverun import Census, describe, removal_holders
from dev_lab.dev.reclaim import _removed, repository_at

__all__ = ['BRANCH', 'reap_orphans', 'salvage', 'salvaged', 'snapshot']

#: The branch a tree's salvage lives on: ``salvage/<tree name>``.
BRANCH: Final = 'salvage/{name}'

_GIT: Final = 'git'
#: The ref an orphan's salvage commit is parented on.
INTEGRATION: Final = 'refs/remotes/origin/integrate/main'
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


def _where(main: Path, directory: Path) -> tuple[str, str]:
    return f'--git-dir={main / ".git"}', f'--work-tree={directory}'


def _unheld_files(main: Path, directory: Path, reachable: frozenset[str]) -> list[tuple[str, str]] | None:
    """Every not-ignored ``(path, blob)`` of *directory* no reachable blob holds; ``None``: unread."""
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / 'index'
        listed = _git(
            directory, *_where(main, directory), 'ls-files', '--others', '--exclude-standard', '-z', index=index
        )
        if listed is None:
            return None
        files = [name for name in listed.split('\0') if name and name != '.git']
        if not files:
            return []
        stdin = '\n'.join(files) + '\n'
        hashed = _git(directory, *_where(main, directory), 'hash-object', '--stdin-paths', stdin=stdin, index=index)
    if hashed is None:
        return None
    return [(path, blob) for path, blob in zip(files, hashed.split(), strict=False) if blob not in reachable]


def _salvaged_orphan(main: Path, directory: Path, unheld: list[tuple[str, str]]) -> str:
    """Record *unheld* on ``salvage/<dir name>``; its sha, or ``''`` when git failed.

    The commit's parent is ``origin/integrate/main`` and its tree that tip's tree with *unheld* overlaid at their
    paths, so its diff against integration is exactly the salvaged files and it merges like any lane (a
    parentless record could not: the merge hooks refuse unrelated histories). No integration ref: parentless.
    """
    paths = '\n'.join(path for path, _ in unheld) + '\n'
    where = _where(main, directory)
    if _git(directory, *where, 'hash-object', '-w', '--stdin-paths', stdin=paths) is None:
        return ''
    base = _rev(main, f'{INTEGRATION}^{{commit}}')
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / 'index'
        if base and _git(main, 'read-tree', base, index=index) is None:
            return ''
        rows = ''.join(f'100644 {blob}\t{path}\0' for path, blob in unheld)  # NUL: text mode turns \n into \r\n
        if _git(main, 'update-index', '-z', '--index-info', stdin=rows, index=index) is None:
            return ''
        made = (_git(main, 'write-tree', index=index) or '').strip()
    message = f'chore(salvage): orphan {directory.name} unreachable files\n'
    parent = ['-p', base] if base else []
    sha = (_git(main, 'commit-tree', made, *parent, stdin=message) or '').strip() if made else ''
    ref = f'refs/heads/{BRANCH.format(name=directory.name)}'
    return sha if sha and _git(main, 'update-ref', ref, sha) is not None else ''


def _shown(unheld: list[tuple[str, str]], most: int = 5) -> str:
    names = ', '.join(path for path, _ in unheld[:most])
    return f'{len(unheld)} files held by no reachable object: {names}' + (', ...' if len(unheld) > most else '')


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


def _reaped(main: Path, directory: Path, reachable: frozenset[str], census: Census, *, salvage: bool) -> list[str]:
    """The lines for one orphan: kept with its reason, or salvaged and/or removed."""
    if live := removal_holders(directory, census=census):
        return [f'kept     {directory}  (live; nothing was deleted)\n{describe(live)}']
    unheld = _unheld_files(main, directory, reachable)
    if unheld is None:
        return [f'kept     {directory}  (git could not read its files; nothing was deleted)']
    lines = []
    if unheld and not salvage:
        return [f'kept     {directory}  ({_shown(unheld)}; nothing was deleted)']
    if unheld:
        sha = _salvaged_orphan(main, directory, unheld)
        if not sha:
            return [f'kept     {directory}  (git could not record its {len(unheld)} unreachable files)']
        lines.append(
            f'salvaged {directory.name} -> {BRANCH.format(name=directory.name)} {sha[:10]} ({len(unheld)} files)'
        )
    if refused := repository_at(main, directory) or _removed(directory):
        return [*lines, refused.replace('{label}', str(directory))]
    return [*lines, f'removed  {directory}  (an orphan: its gitdir vanished, every file reachable)']


def reap_orphans(root: Path, *, census: Census = processes, salvage: bool = False) -> tuple[str, ...]:
    """THE ORPHAN DOOR: remove every orphan tree directory whose content some ref reaches; one line each.

    With *salvage*, an orphan's unreachable files are first recorded as one commit on ``salvage/<dir name>``.
    """
    main = root.resolve()
    orphans = list(_orphans(main))
    if not orphans:
        return ()
    reachable = _reachable_blobs(main)
    if reachable is None:
        return (f'refused  git could not list the reachable blobs of {main}; nothing was removed',)
    return tuple(line for directory in orphans for line in _reaped(main, directory, reachable, census, salvage=salvage))
