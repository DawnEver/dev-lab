"""THE TRUNK IS PROMOTED BY THE HOST, unattended: per configured repo, ``integrate promote``, which pushes.

The decision is :func:`dev_lab.dev.integrate.promote` with ``--newest`` -- every derived part PASS at scope full on
the NEWEST first parent of the integration tip (W5, dev-lab#644) -- never re-derived here. This role only gives it a
clone (made on first run), the tip to judge
(``origin/<integration>``, the branch the repo's own declaration names) and the configured credential its
fast-forward push of origin's trunk uses. NO REFUSAL IS QUIET (W5): a refusal, and each commit the walk
passed over, is an alert naming its reason, as a fetch, promote or push FAILURE is, through ``[alerts]``
(:func:`dev_lab.ops.hostverbs.promote_verb`). A frozen trunk was a consumer's ``main`` 639 commits behind.
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
    """One repo's night: ``promoted``, ``current``, ``refused`` or ``failed``, with what was said.

    *alarmed*: a promotion that passed over newer commits, each named in *detail* -- alerted like a refusal.
    """

    repo: str
    state: str
    detail: str = ''
    alarmed: bool = False


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


#: A promotion pass: the exit of ``integrate`` on *argv* in a clone, and every ALARM line it said.
Promote = Callable[[list[str], Path], tuple[int, tuple[str, ...]]]


def _one(config: OpsConfig, url: str, credentials: str, promote: Promote) -> Outcome:
    name, prepared = repo_name(url), _prepare(config, url, credentials)
    if isinstance(prepared, Outcome):
        return prepared
    root, policy, tip = prepared
    if not integrate.pending(root, policy, tip):
        return Outcome(name, 'current', tip[:12])
    code, alarms = promote(['promote', '--newest', tip], root)
    if code == REFUSED:
        return Outcome(name, 'refused', '; '.join([f'{tip[:12]} and every first parent to the trunk', *alarms]))
    if code != 0:
        return Outcome(name, 'failed', f'integrate promote exit {code}')
    moved = git(root, 'rev-parse', f'origin/{policy.trunk}').stdout.strip()
    return Outcome(name, 'promoted', '; '.join([f'{policy.trunk} -> {moved[:12]}', *alarms]), alarmed=bool(alarms))


def _integrate(argv: list[str], root: Path) -> tuple[int, tuple[str, ...]]:
    said: list[str] = []
    return integrate.main(argv, cwd=root, said=said.append), tuple(said)


def run(config: OpsConfig, *, promote: Promote = _integrate) -> list[Outcome]:
    """Promote every configured repo, one line each; a failure in one never stops the next."""
    if config.promote is None:
        msg = f'{config.path} enables no [ops.promote]'
        raise ValueError(msg)
    outcomes = [_one(config, url, config.promote.credentials, promote) for url in config.repos]
    for outcome in outcomes:
        emit(f'[ops promote] {outcome.repo}: {outcome.state} {outcome.detail}'.rstrip())
    return outcomes
