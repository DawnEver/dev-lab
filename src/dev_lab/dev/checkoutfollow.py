"""CHECKOUT-FOLLOWS-INTEGRATION: a clean primary checkout left behind ``origin/<integration>`` moves itself.

User ruling 2026-11-12: keeping a checkout's toolchain current is the toolchain's own work, never a person's
prompt. A primary checkout left DETACHED on an old commit -- or sitting on its integration branch behind origin --
runs a kit that can no longer read its own manifest, so neither its venv nor its hooks can follow. This moves it,
under three conditions that make the move lossless:

* the PRIMARY checkout only (a linked worktree is a lane, and its branch is its author's);
* CLEAN in every tracked path (an untracked file the move would overwrite makes git refuse, and that is reported);
* HEAD is an ANCESTOR of ``origin/<integration>``, so the move is a fast-forward and loses no commit.

The integration branch is the checkout's own ``[tool.dev_lab.integrator] integration``; a tree too old to declare
it is read at ``origin/HEAD`` instead (:mod:`dev_lab.dev.lanepolicy`). Any other state is reported, never moved.
Called by :mod:`dev_lab.dev.venvfollow` before the venv follows, so the venv follows the moved lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.checkout import git_out
from dev_lab.dev.lanepolicy import load_policy, policy_at
from dev_lab.dev.prcurrent import fetch_ref

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ['advance', 'behind', 'integration']

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


def advance(root: Path, *, fetch: Callable[[Path, str], str | None] = fetch_ref) -> str:
    """Fast-forward *root* onto ``origin/<integration>`` when that is lossless; what was done, ``''`` for nothing."""
    if not behind(root):
        return ''
    _branch, name, _tip = _state(root) or ('', '', '')
    if why := fetch(root, name):
        return f'checkout {root}: origin/{name} not fetched ({why}); following the ref already held'
    branch, name, tip = _state(root) or ('', name, '')
    head = (git_out(root, 'rev-parse', 'HEAD') or '').strip()
    if branch and head == tip:
        return ''
    if git_out(root, 'status', '--porcelain', '--untracked-files=no') != '':
        return f'checkout {root}: left at {head[:12]} -- it has uncommitted changes'
    if not _ancestor(root, 'HEAD', tip):
        return f'checkout {root}: left at {head[:12]} -- not an ancestor of origin/{name}'
    local = git_out(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}')
    if not branch and local is not None and not _ancestor(root, local.strip(), tip):
        return f'checkout {root}: left at {head[:12]} -- local {name} has commits origin/{name} lacks'
    if not branch:
        switch = ('switch', name) if local is not None else ('switch', '-c', name, 'HEAD')
        if git_out(root, *switch) is None:
            return f'checkout {root}: left at {head[:12]} -- `git {" ".join(switch)}` refused (an untracked file?)'
        if local is None:
            git_out(root, 'branch', '--quiet', f'--set-upstream-to=origin/{name}', name)
    if git_out(root, 'merge', '--ff-only', '--quiet', tip) is None:
        return f'checkout {root}: on {name}, the fast-forward to origin/{name} refused'
    return f'checkout {root}: {head[:12]} -> {name} at {tip[:12]}'
