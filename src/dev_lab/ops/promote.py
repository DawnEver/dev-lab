"""THE TRUNK IS PROMOTED BY THE HOST, unattended: per configured repo, ``integrate promote`` then a push.

The decision is :func:`dev_lab.dev.integrate.promote` -- every derived part PASS at scope full on the
integration tip -- never re-derived here. This role only gives it a clone (made on first run), the tip to judge
(``origin/<integration>``, the branch the repo's own declaration names) and, when it moves the local trunk, the
push of that trunk with the configured credential. A refusal is the normal nightly answer and is quiet; a fetch,
promote or push FAILURE is an alert through the configuration's ``[alerts]``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import integrate
from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.ops.config import OpsConfig, repo_name

__all__ = ['Outcome', 'run']

_GIT: Final = shutil.which('git') or 'git'

#: The ref every clone resolves its declaration at: the forge's default branch, which carries the repo's table.
DECLARED_AT: Final = 'origin/HEAD'
#: ``integrate promote``'s exit when it refuses: the tip is not yet promotable, the normal nightly answer.
REFUSED: Final = 2


@dataclass(frozen=True)
class Outcome:
    """One repo's night: ``promoted``, ``current``, ``refused`` or ``failed``, with what was said."""

    repo: str
    state: str
    detail: str = ''


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=600
    )


def _clone(config: OpsConfig, url: str, credentials: str) -> str | None:
    """Clone *url* without a working tree, its pushes using the configured credential; the error, else ``None``."""
    target = config.checkout(url)
    if target.is_dir():
        return None
    helper = f'store --file={credentials}'
    done = _git(config.home, 'clone', '--no-checkout', '-c', f'credential.helper={helper}', url, str(target))
    if done.returncode != 0:
        return done.stderr.strip()
    # A detached HEAD: `integrate promote` refuses to move a trunk some worktree has checked out.
    detached = _git(target, 'update-ref', '--no-deref', 'HEAD', 'HEAD')
    return None if detached.returncode == 0 else detached.stderr.strip()


def _prepare(config: OpsConfig, url: str, credentials: str) -> tuple[Path, Policy, str] | Outcome:
    """The clone, its declaration and its integration tip, freshly fetched; else the failed :class:`Outcome`."""
    name, root = repo_name(url), config.checkout(url)
    if failed := _clone(config, url, credentials):
        return Outcome(name, 'failed', f'clone: {failed}')
    fetched = _git(root, 'fetch', '--prune', 'origin')
    if fetched.returncode != 0:
        return Outcome(name, 'failed', f'fetch: {fetched.stderr.strip()}')
    _git(root, 'remote', 'set-head', 'origin', '--auto')
    try:
        policy = policy_at(root, DECLARED_AT)
    except (ValueError, subprocess.CalledProcessError) as unread:
        return Outcome(name, 'failed', f'declaration at {DECLARED_AT}: {unread}')
    tip = _git(root, 'rev-parse', '--verify', '--quiet', f'origin/{policy.integration}').stdout.strip()
    if not tip:
        return Outcome(name, 'failed', f'origin/{policy.integration} does not resolve')
    return root, policy, tip


def _one(config: OpsConfig, url: str, credentials: str, promote: Callable[[list[str], Path], int]) -> Outcome:
    name, prepared = repo_name(url), _prepare(config, url, credentials)
    if isinstance(prepared, Outcome):
        return prepared
    root, policy, tip = prepared
    if not integrate.pending(root, policy, tip):
        return Outcome(name, 'current', tip[:12])
    code = promote(['promote', tip], root)
    if code == REFUSED:
        return Outcome(name, 'refused', tip[:12])
    if code != 0:
        return Outcome(name, 'failed', f'integrate promote exit {code}')
    pushed = _git(root, 'push', 'origin', f'refs/heads/{policy.trunk}:refs/heads/{policy.trunk}')
    if pushed.returncode != 0:
        return Outcome(name, 'failed', f'push {policy.trunk}: {pushed.stderr.strip()}')
    return Outcome(name, 'promoted', f'{policy.trunk} -> {tip[:12]}')


def _integrate(argv: list[str], root: Path) -> int:
    return integrate.main(argv, cwd=root)


def run(config: OpsConfig, *, promote: Callable[[list[str], Path], int] = _integrate) -> list[Outcome]:
    """Promote every configured repo, one line each; a failure in one never stops the next."""
    if config.promote is None:
        msg = f'{config.path} enables no [ops.promote]'
        raise ValueError(msg)
    config.home.mkdir(parents=True, exist_ok=True)
    outcomes = [_one(config, url, config.promote.credentials, promote) for url in config.repos]
    for outcome in outcomes:
        emit(f'[ops promote] {outcome.repo}: {outcome.state} {outcome.detail}'.rstrip())
    return outcomes
