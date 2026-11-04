"""THE HOST'S CLONES: one per configured repo under ``[ops] home``, owned by this module for every role.

:func:`sync` makes the clone on first use (no working tree, a detached HEAD so ``integrate promote`` may move the
trunk, pushes through the given credential store), fetches it and points ``origin/HEAD`` at the forge's default
branch. :func:`declared` reads the repo's own lane declaration at :data:`DECLARED_AT` -- the one place the roles learn
the trunk and integration branch names -- and raises :class:`CloneUnusable` naming the remedy when the clone is
missing or its declaration cannot be read. The promote role syncs; break-glass only reads (it runs as root and must
not create clones the promote user then cannot write).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.ops.config import OpsConfig

__all__ = ['DECLARED_AT', 'CloneUnusable', 'declared', 'git', 'sync']

#: The ref every clone resolves its declaration at: the forge's default branch, which carries the repo's table.
DECLARED_AT: Final = 'origin/HEAD'
_GIT: Final = shutil.which('git') or 'git'


class CloneUnusable(RuntimeError):
    """The clone is missing, cannot be fetched, or holds no readable declaration; the message names the remedy."""


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git command in *root*, never raising on its exit."""
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=600
    )


def sync(config: OpsConfig, url: str, *, credentials: str) -> Path:
    """The clone of *url*, made when absent and fetched; raises :class:`CloneUnusable` with git's own words."""
    root = config.checkout(url)
    if not root.is_dir():
        config.home.mkdir(parents=True, exist_ok=True)
        helper = f'credential.helper=store --file={credentials}'
        done = git(config.home, 'clone', '--no-checkout', '-c', helper, url, str(root))
        if done.returncode != 0:
            msg = f'clone {url}: {done.stderr.strip()}'
            raise CloneUnusable(msg)
        detached = git(root, 'update-ref', '--no-deref', 'HEAD', 'HEAD')
        if detached.returncode != 0:
            msg = f'detach {root}: {detached.stderr.strip()}'
            raise CloneUnusable(msg)
    fetched = git(root, 'fetch', '--prune', 'origin')
    if fetched.returncode != 0:
        msg = f'fetch {root}: {fetched.stderr.strip()}'
        raise CloneUnusable(msg)
    git(root, 'remote', 'set-head', 'origin', '--auto')
    return root


def declared(config: OpsConfig, url: str) -> tuple[Path, Policy]:
    """The clone of *url* and its declaration at :data:`DECLARED_AT`; raises :class:`CloneUnusable`."""
    root = config.checkout(url)
    if not root.is_dir():
        msg = f'no clone of {url} at {root}: the promote role makes it (python -m dev_lab.ops --config <toml> promote)'
        raise CloneUnusable(msg)
    try:
        return root, policy_at(root, DECLARED_AT)
    except (ValueError, subprocess.CalledProcessError) as unread:
        msg = f'the declaration of {root} at {DECLARED_AT} cannot be read: {unread}'
        raise CloneUnusable(msg) from unread
