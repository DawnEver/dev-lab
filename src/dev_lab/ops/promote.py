"""THE TRUNK IS PROMOTED BY THE HOST, unattended: per configured repo, ``integrate promote`` then a push.

The decision is :func:`dev_lab.dev.integrate.promote` -- every derived part PASS at scope full on the
integration tip -- never re-derived here. This role only gives it a clone (made on first run), the tip to judge
(``origin/<integration>``, the branch the repo's own declaration names) and, when it moves the local trunk, the
push of that trunk with the configured credential. A refusal is the normal nightly answer and is quiet; a fetch,
promote or push FAILURE is an alert through the configuration's ``[alerts]``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev import integrate
from dev_lab.dev.lanepolicy import Policy
from dev_lab.ops.clones import CloneUnusable, declared, git, sync
from dev_lab.ops.config import OpsConfig, repo_name

__all__ = ['Outcome', 'run']

#: ``integrate promote``'s exit when it refuses: the tip is not yet promotable, the normal nightly answer.
REFUSED: Final = 2


@dataclass(frozen=True)
class Outcome:
    """One repo's night: ``promoted``, ``current``, ``refused`` or ``failed``, with what was said."""

    repo: str
    state: str
    detail: str = ''


def _prepare(config: OpsConfig, url: str, credentials: str) -> tuple[Path, Policy, str] | Outcome:
    """The clone, its declaration and its integration tip, freshly fetched; else the failed :class:`Outcome`."""
    name = repo_name(url)
    try:
        sync(config, url, credentials=credentials)
        root, policy = declared(config, url)
    except CloneUnusable as unusable:
        return Outcome(name, 'failed', str(unusable))
    tip = git(root, 'rev-parse', '--verify', '--quiet', f'origin/{policy.integration}').stdout.strip()
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
    pushed = git(root, 'push', 'origin', f'refs/heads/{policy.trunk}:refs/heads/{policy.trunk}')
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
    outcomes = [_one(config, url, config.promote.credentials, promote) for url in config.repos]
    for outcome in outcomes:
        emit(f'[ops promote] {outcome.repo}: {outcome.state} {outcome.detail}'.rstrip())
    return outcomes
