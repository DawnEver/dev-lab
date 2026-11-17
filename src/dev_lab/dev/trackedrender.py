"""A TRACKED RENDER IS THE CHECKOUT'S OWN KIT'S, AND NEVER A MAIN CHECKOUT'S (toolchain O14, 2026-11-17).

THE INCIDENT. A consumer's MAIN checkout held a ``deny-commands.js`` and a ``settings.json`` differing from HEAD:
``agent_guard --install`` ran there from a dev-lab its lock does not pin, and the dirt made the fast-forward
refresh refuse the checkout until it was 180 commits behind.

THE TENSION. The same install is how a LANE re-renders those files after a relock and commits them, so the rule
is not "never write tracked files". It is: a write that would leave a TRACKED file differing from the index
(:func:`tracked_dirt`, git's own ``hash-object --path`` so eol rules and clean filters count as git counts them)
happens only when the running :class:`Kit` is the checkout's own -- its package IS the checkout's ``src/dev_lab``
(dev-lab itself), or it was installed from the commit the checkout's ``uv.lock`` pins -- AND the checkout is a
linked worktree. A main checkout has one editor and moves only by fast-forward, so even its own kit's render
belongs in a lane commit. :func:`check_render` raises :class:`RenderRefused` naming the files, the cause and the
door; an untracked or ignored write and a checkout outside git are not judged, which keeps a first adoption open.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.agent_wiring import REINSTALL_COMMAND
from dev_lab.dev.backgroundrun import main_checkout
from dev_lab.dev.checkout import git_out
from dev_lab.dev.lockpins import installed_git, locked_git, sync_door

__all__ = ['Kit', 'RenderRefused', 'check_render', 'refusal', 'running_kit', 'tracked_dirt']

#: The distribution whose kit renders these files, as :mod:`dev_lab.dev.lockpins` names packages.
_KIT_DIST: Final = 'dev-lab'
_GIT: Final = shutil.which('git') or 'git'


@dataclass(frozen=True, slots=True)
class Kit:
    """The dev-lab an install runs from: its package directory, and the git commit it was installed at ('' if none)."""

    package: Path
    commit: str


def running_kit() -> Kit:
    """The kit THIS process runs: the package this module was imported from, and its PEP 610 git commit."""
    commits = {one.name: one.commit for one in installed_git()}
    return Kit(Path(__file__).resolve().parent.parent, commits.get(_KIT_DIST, ''))


class RenderRefused(RuntimeError):
    """A tracked file would move in a main checkout or under a kit not the checkout's own; nothing was written."""


def _blob(repo: Path, rel: str, data: bytes) -> str:
    """The blob id git would store for *data* at *rel* (clean filters and eol rules applied); '' if git cannot say."""
    done = _door.run(
        [_GIT, 'hash-object', f'--path={rel}', '--stdin'], cwd=repo, input=data, capture_output=True, check=False
    )
    return done.stdout.decode('utf-8', 'replace').strip() if done.returncode == 0 else ''


def tracked_dirt(repo: Path, writes: dict[Path, bytes]) -> tuple[str, ...]:
    """The TRACKED files *writes* would leave differing from the index, repo-relative; none outside git."""
    data = {path.relative_to(repo).as_posix(): content for path, content in writes.items()}
    staged = git_out(repo, 'ls-files', '--stage', '-z', '--', *data) if data else None
    index: dict[str, str] = {}
    for row in (staged or '').split('\0'):
        meta, tab, rel = row.partition('\t')
        if tab and rel in data:
            index[rel] = meta.split()[1]
    return tuple(sorted(rel for rel, blob in index.items() if _blob(repo, rel, data[rel]) != blob))


def _foreign(repo: Path, kit: Kit) -> str | None:
    """Why *kit* is not *repo*'s own; ``None`` when its package IS the repo's source or its commit is the lock's pin."""
    if kit.package.resolve() == (repo / 'src' / 'dev_lab').resolve():
        return None
    pin = locked_git(repo / 'uv.lock').get(_KIT_DIST, '')
    if pin and pin == kit.commit:
        return None
    running = (
        f'dev-lab {kit.commit[:12]}' if kit.commit else f'the dev-lab at {kit.package}, installed from no git commit'
    )
    pinned = f'its uv.lock pins {pin[:12]}' if pin else 'its uv.lock pins no dev-lab commit'
    return f'the running kit is not its own: {running}, {pinned}'


def refusal(repo: Path, dirt: tuple[str, ...], kit: Kit) -> str | None:
    """The refusal for moving *dirt* in *repo* under *kit*; ``None`` when nothing tracked moves or both rules pass."""
    if not dirt:
        return None
    main = main_checkout(repo) is not None
    foreign = _foreign(repo, kit)
    if not main and foreign is None:
        return None
    if main:
        door = (
            f'{repo} is a MAIN checkout, which moves only by fast-forward -- re-render in a lane worktree '
            f'({REINSTALL_COMMAND}) and commit the render there with its lock; this checkout catches up by fast-forward'
        )
    else:
        door = (
            f"run the install under this checkout's own interpreter ({REINSTALL_COMMAND}) once "
            f'`{sync_door(repo)} {repo}` has made its venv follow its uv.lock; to move the render to another '
            'dev-lab, relock this lane and commit the render with the lock'
        )
    cause = f'; {foreign}' if foreign else ''
    return (
        f'writing would leave {", ".join(dirt)} differing from what {repo} committed{cause} -- dirt its '
        f'fast-forward refresh refuses. Nothing was written. Door: {door}.'
    )


def check_render(repo: Path, writes: dict[Path, bytes], *, kit: Kit | None = None) -> None:
    """Raise :class:`RenderRefused` when *writes* would move a tracked file of *repo* that *kit* may not move.

    *kit* defaults to :func:`running_kit`. Writing is the caller's, and only after this returns.
    """
    refused = refusal(repo, tracked_dirt(repo, writes), running_kit() if kit is None else kit)
    if refused is not None:
        raise RenderRefused(refused)
