"""CHECKOUT-FOLLOWS-INTEGRATION: a clean primary checkout left behind ``origin/<integration>`` moves itself.

User ruling 2026-11-12: keeping a checkout's toolchain current is the toolchain's own work, never a person's
prompt. A primary checkout left DETACHED on an old commit -- or sitting on its integration branch behind origin --
runs a kit that can no longer read its own manifest, so neither its venv nor its hooks can follow. This moves it,
under three conditions that make the move lossless:

* the PRIMARY checkout only (a linked worktree is a lane, and its branch is its author's);
* CLEAN in every tracked path (an untracked file the move would overwrite makes git refuse, and that is reported),
  except an APPEND to a task journal (``<ledger>/<slug>/JOURNAL.md``, :func:`dev_lab.dev.taskbinding.ledger`) that
  upstream leaves alone: the rem task hooks write that ledger in the main checkout, and the fast-forward carries the
  appended lines across unchanged (toolchain O19, user ruling 2026-11-17);
* NO LIVE RUN reads it (TREE-HAS-A-LIVE-RUN, :func:`holders`): a run executing from the tree would report on a tree
  that never existed, so the follow waits for it and names the holder;
* HEAD is an ANCESTOR of ``origin/<integration>`` (a fast-forward), or -- when detached -- a commit some ``origin``
  ref holds, so leaving it loses nothing.

The integration branch is the checkout's own ``[tool.dev_lab.integrator] integration``; a tree too old to declare
it is read at ``origin/HEAD`` instead (:mod:`dev_lab.dev.lanepolicy`). Any other state is reported, never moved.
Called by :mod:`dev_lab.dev.venvfollow` before the venv follows, so the venv follows the moved lock; its session-start
notice reads :func:`obstacle` to say why a behind checkout stays (toolchain O14: the per-call hook inputs are read
from disk, so a checkout left behind serves stale rules to every session).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev import liverun
from dev_lab.dev.checkout import git_out
from dev_lab.dev.lanepolicy import load_policy, policy_at
from dev_lab.dev.prcurrent import fetch_ref
from dev_lab.dev.taskbinding import ledger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ['advance', 'behind', 'holders', 'integration', 'obstacle']

#: Where a tree too old to declare its integration branch reads the declaration instead.
UPSTREAM_DECLARATION: Final = 'refs/remotes/origin/HEAD'


def integration(root: Path) -> str | None:
    """*root*'s declared integration branch, read upstream when its own tree cannot; ``None`` when neither can."""
    for read in (lambda: load_policy(root), lambda: policy_at(root, UPSTREAM_DECLARATION)):
        try:
            return read().integration
        except (OSError, ValueError, RuntimeError):
            continue
    return None


def _primary(root: Path) -> bool:
    git_dir, common = git_out(root, 'rev-parse', '--absolute-git-dir'), git_out(root, 'rev-parse', '--git-common-dir')
    if git_dir is None or common is None:
        return False
    common_dir = git_out(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    return common_dir is not None and git_dir.strip() == common_dir.strip()


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return git_out(root, 'merge-base', '--is-ancestor', older, newer) is not None


def _state(root: Path) -> tuple[str, str, str] | None:
    """``(branch or '', integration, origin tip)`` of a primary checkout the follow may judge, else ``None``."""
    if not _primary(root) or (name := integration(root)) is None:
        return None
    tip = git_out(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{name}^{{commit}}')
    if tip is None:
        return None
    branch = (git_out(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') or '').strip()
    if branch and branch != name:
        return None
    return branch, name, tip.strip()


def behind(root: Path) -> bool:
    """*root* is a primary checkout detached, or on integration behind the origin ref it already holds."""
    state = _state(root)
    if state is None:
        return False
    branch, _name, tip = state
    head = (git_out(root, 'rev-parse', 'HEAD') or '').strip()
    return not branch or head != tip


def _held_upstream(root: Path, tip: str) -> bool:
    """HEAD is an ancestor of *tip*, or held by some ``origin`` ref: leaving it loses no commit."""
    if _ancestor(root, 'HEAD', tip):
        return True
    return bool((git_out(root, 'for-each-ref', '--count=1', '--contains', 'HEAD', 'refs/remotes/origin') or '').strip())


def _journal(root: Path, path: str) -> bool:
    """*path* is a task journal ``<ledger>/<slug>/JOURNAL.md`` of *root*."""
    parts, home = (root / path).relative_to(root).parts, ledger(root).relative_to(root).parts
    return len(parts) == len(home) + 2 and parts[: len(home)] == home and parts[-1] == 'JOURNAL.md'


def _dirt(root: Path, tip: str) -> str | None:
    """Why *root*'s uncommitted tracked changes block the fast-forward to *tip*, else ``None``.

    ``None`` when there are none, or when each is an append to a task journal upstream leaves alone: the
    fast-forward carries it across.
    """
    if (listed := git_out(root, 'diff', '--name-only', 'HEAD')) is None:
        return 'git could not list its uncommitted changes'
    if not (changed := listed.split()):
        return None
    if others := [path for path in changed if not _journal(root, path)]:
        return f'it has uncommitted changes ({", ".join(others)})'
    upstream = set((git_out(root, 'diff', '--name-only', 'HEAD', tip) or '').split())
    for path in changed:
        if path in upstream:
            return f'its task journal {path} has local appends and upstream changed it too'
        before = (git_out(root, 'show', f'HEAD:{path}') or '').rstrip()  # text mode: newlines normalised
        try:
            now = (root / path).read_text(encoding='utf-8')
        except OSError:
            now = ''
        if not now.startswith(before):
            return f'its task journal {path} has uncommitted changes that are not an append'
    return None


def _refusal(root: Path, branch: str, name: str, tip: str) -> str | None:
    """Why moving *root* onto *tip* could lose work, or ``None`` when the move is lossless."""
    local = git_out(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}')
    dirt = _dirt(root, tip)
    reasons = (
        (dirt is not None, dirt or ''),
        (branch and not _ancestor(root, 'HEAD', tip), f'{name} has commits origin/{name} lacks'),
        (not branch and not _held_upstream(root, tip), f'its commit is not an ancestor of origin/{name} nor on origin'),
        (not branch and local is not None and not _ancestor(root, local.strip(), tip),
         f'local {name} has commits origin/{name} lacks'),
    )  # fmt: skip
    return next((why for refused, why in reasons if refused), None)


def _move(root: Path, branch: str, name: str, tip: str) -> str | None:
    """Switch a detached *root* onto *name* and fast-forward it to *tip*; the git step that refused, else ``None``."""
    if not branch:
        exists = git_out(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}') is not None
        switch = ('switch', name) if exists else ('switch', '-c', name, tip)
        if git_out(root, *switch) is None:
            return f'`git {" ".join(switch)}` refused (an untracked file in the way?)'
        if not exists:
            git_out(root, 'branch', '--quiet', f'--set-upstream-to=origin/{name}', name)
    if git_out(root, 'merge', '--ff-only', '--quiet', tip) is None:
        return f'the fast-forward to origin/{name} refused'
    return None


def holders(root: Path) -> str:
    """The live runs reading *root* (:func:`dev_lab.dev.liverun.live_runs`), one phrase; ``''`` when there are none."""
    return '; '.join(line.strip() for line in liverun.describe(liverun.live_runs(root)).splitlines())


def obstacle(root: Path, *, busy: Callable[[Path], str] = holders) -> str:
    """Why the follow leaves a behind *root* where it is, judged on the last fetch; ``''`` when it would move it."""
    state = _state(root)
    if state is None:
        return 'it is not a primary checkout on its declared integration branch'
    if runs := busy(root):
        return f'a live run reads it ({runs})'
    return _refusal(root, *state) or ''


def advance(
    root: Path,
    *,
    fetch: Callable[[Path, str], str | None] = fetch_ref,
    busy: Callable[[Path], str] = holders,
) -> str:
    """Fast-forward *root* onto ``origin/<integration>`` when that is lossless; what was done, ``''`` for nothing."""
    if not behind(root):
        return ''
    if runs := busy(root):
        head = (git_out(root, 'rev-parse', 'HEAD') or '').strip()
        return f'checkout {root}: left at {head[:12]} -- a live run reads it ({runs})'
    fetched = fetch(root, (_state(root) or ('', '', ''))[1])
    state = _state(root)
    if state is None or not behind(root):
        return ''
    branch, name, tip = state
    head = (git_out(root, 'rev-parse', 'HEAD') or '').strip()
    note = f' (origin/{name} not fetched: {fetched})' if fetched else ''
    if why := _refusal(root, branch, name, tip) or _move(root, branch, name, tip):
        return f'checkout {root}: left at {head[:12]} -- {why}{note}'
    return f'checkout {root}: {head[:12]} -> {name} at {tip[:12]}{note}'
