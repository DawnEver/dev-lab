"""PROMOTION MOVES ORIGIN'S TRUNK, NEVER A CHECKOUT: fast-forward origin's trunk to an integration commit.

The trunk is one more session branch (:mod:`dev_lab.dev.sessionbranch`): what makes it legitimate is that
it lands by fast-forward on an integration commit whose every part stands PASS (TRUNK-MOVES-BY-FAST-FORWARD),
not which directory it was moved in. So the verb decides against ``origin/<trunk>`` and publishes with a plain,
non-forced ``git push origin <sha>:refs/heads/<trunk>`` through the network door -- a push git itself refuses
unless it fast-forwards, and the pre-push guard judges. No local branch of the trunk is read, moved or required:
one checked out somewhere (a live config checkout, say) is left alone and named stale -- pulling it is its owner's.

WHO MAY PUBLISH THE TRUNK is the forge's protection: on GitHub the ruleset admits the nightly promote job's token
alone (``ci.yml`` ``jobs.promote``, :data:`~dev_lab.dev.nightlycron.NIGHTLY_CRON`; :mod:`dev_lab.dev._protect_github`),
so anywhere else the verb DECIDES and moves nothing -- a local trunk no push can publish is a divergence, not a
promotion -- and says ``promotable`` with when the job runs. On Gitea the host's promoter runs this verb and pushes.

* ``promote <sha>`` -- fast-forward ORIGIN's trunk to *sha*, an integration commit on origin whose
  every derived AND every declared-required ``tests/<part>`` (:func:`dev_lab.dev.platformparts.required_at`)
  stands PASS at scope full under the policy *sha* declares, each naming its env -- save a part needing a resource
  of `[tool.dev_lab.parts] optional_needs` (:mod:`dev_lab.dev.producers`), never a condition (:func:`decide`, the
  standing push admission reads, over the commit's whole status history). Never a merge onto the trunk.
* ``promote --newest <tip>`` -- the same decision on each first parent of *tip* down to the trunk (at most
  :data:`DEPTH`), promoting the NEWEST that passes (W5, dev-lab#644: integration moves faster than a full run, so the
  tip alone was refused nightly and a consumer's trunk froze). Every commit passed over is an ALARM naming its
  reason (:func:`newest`), never a quiet refusal.
* ``pending <sha>`` -- print ``pending=true`` while the trunk does not hold *sha*, else ``pending=false`` (a
  ``$GITHUB_OUTPUT`` line): the nightly promotion run (D48-1A) tests and promotes integration's tip only while it is
  pending, so a tip already promoted runs nothing.

The integration branch is moved by the FORGE alone, server side, when it merges a reviewed, safe, clean pull request
-- whose parts need NOT pass: they gate only this promotion
(:mod:`dev_lab.dev.forgemerge`). A client has no verb for that, and this one is not a bypass: a trunk
that cannot fast-forward is refused rather than merged, and the push itself is non-forced.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev import metrics
from dev_lab.dev._forgebackends import FORGE_SERVE, GITHUB, actions_token, backend_for
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import CommitStatus, status_history
from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.hostedparts import hosted_parts
from dev_lab.dev.jobparts import off_gate
from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.nightlycron import NIGHTLY_CRON
from dev_lab.dev.platformparts import UndeclaredPart, derived, required_at, standing
from dev_lab.dev.producers import optional_needs_from, optional_parts
from dev_lab.dev.trialmerge import contains, rev
from dev_lab.dev.unproduced import unproduced_waived
from dev_lab.dev.verdictenv import verdict_policy_at

__all__ = ['DEPTH', 'IntegrateRefused', 'Promotion', 'decide', 'main', 'newest', 'pending', 'promote']

_GIT: Final = shutil.which('git') or 'git'

#: How many first parents below the tip ``promote --newest`` decides before it refuses.
DEPTH: Final = 64

#: The refusal's id in the metrics log (:mod:`dev_lab.dev.metrics`).
_RULE: Final = 'integrate-promote'


class IntegrateRefused(RuntimeError):
    """The promotion was refused; the message names why and the remedy."""


@dataclass(frozen=True)
class Promotion:
    """What promote decided: ``promote``, ``promotable``, ``current`` (nothing to do) or ``refused``, with why.

    ``promotable`` passes, but this process may not publish the trunk (:func:`publishes_trunk`): the ref stays.
    *passed_over* is each newer first parent :func:`newest` refused before it, newest first.
    """

    action: str
    sha: str
    reasons: tuple[str, ...] = ()
    passed_over: tuple[Promotion, ...] = ()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=300
    )


def _publish(root: Path, trunk: str, new: str) -> None:
    """Fast-forward origin's *trunk* to *new*: a non-forced push, so git refuses anything but a fast-forward."""
    report = run_network_verb([_GIT, 'push', 'origin', f'{new}:refs/heads/{trunk}'], cwd=root)
    if not report.ok:
        msg = f'origin/{trunk} did not take {new[:12]}: {report.remedy}'
        raise IntegrateRefused(msg)


def _stale_local(root: Path, trunk: str, sha: str) -> str | None:
    """The note for a local *trunk* branch that is not at *sha*: promotion never moves it, its owner pulls."""
    local = rev(root, f'refs/heads/{trunk}')
    if local is None or local == sha:
        return None
    return f'local {trunk} stays at {local[:12]} (promotion moves origin only); its owner pulls it'


def _policy(root: Path, at: str) -> Policy:
    try:
        return policy_at(root, at)
    except (ValueError, subprocess.CalledProcessError) as exc:
        msg = f'the declaration at {at} cannot be read: {exc}'
        raise IntegrateRefused(msg) from exc


def _trunk(root: Path, policy: Policy) -> str | None:
    """The trunk's commit on origin: a local branch of it is never the trunk."""
    return rev(root, f'origin/{policy.trunk}')


def pending(root: Path, policy: Policy, sha: str) -> bool:
    """Whether the trunk does not yet hold *sha*: a promotion of it is still to be decided."""
    found, trunk = rev(root, sha), _trunk(root, policy)
    return not (found and trunk and contains(root, trunk, found))


def decide(root: Path, client: Client, policy: Policy, sha: str) -> Promotion:
    """Whether origin's trunk may fast-forward to *sha*; pure of any write. Reads origin's integration branch."""
    found = rev(root, sha)
    trunk = _trunk(root, policy)
    published = rev(root, f'origin/{policy.integration}')
    if found is None or published is None or not contains(root, published, found):
        return Promotion('refused', sha, (f'{sha} is not a commit of origin/{policy.integration}',))
    if trunk == found:
        return Promotion('current', found)
    if trunk is not None and not contains(root, found, trunk):
        why = f'{policy.trunk} ({trunk[:12]}) is not an ancestor of {found[:12]}: it cannot fast-forward'
        return Promotion('refused', found, (why,))
    statuses = status_history(client, found)  # every fact: another env or policy never overwrote one
    off = _off_gate(root, client, found, statuses)
    try:
        required = required_at(root, found)
    except UndeclaredPart as why:
        return Promotion('refused', found, (str(why),))
    optional = optional_parts(derived(statuses), optional_needs_from(pyproject_at(root, found)))
    waived = (unproduced_waived(root, found, statuses) | off | optional) - required
    policy = verdict_policy_at(root, found)
    parts = standing(statuses, head=found, scope=FULL, waived=waived, required=required, policy=policy)
    if parts.result is not Conclusion.PASS:
        return Promotion('refused', found, (f'the parts of {found[:12]} stand {parts.result.name}', *parts.problems))
    return Promotion(
        'promote', found, tuple(f'tests/{part}: off the gate, no Actions job produces it' for part in sorted(off))
    )


def newest(root: Path, client: Client, policy: Policy, tip: str) -> Promotion:
    """:func:`decide` on *tip*'s first parents above the trunk, newest first: the first that is not refused.

    Each refused commit above it rides along as *passed_over*; when every one refuses, the tip's refusal carries them.
    """
    trunk = _trunk(root, policy)
    listed = _git(root, 'rev-list', '--first-parent', f'--max-count={DEPTH}', tip, *([f'^{trunk}'] if trunk else ()))
    refused: list[Promotion] = []
    for sha in listed.stdout.split() if listed.returncode == 0 else ():
        found = decide(root, client, policy, sha)
        if found.action != 'refused':
            return dataclasses.replace(found, passed_over=tuple(refused))
        refused.append(found)
    if not refused:
        return decide(root, client, policy, tip)
    return dataclasses.replace(refused[0], passed_over=tuple(refused[1:]))


def _off_gate(root: Path, client: Client, sha: str, statuses: Sequence[CommitStatus]) -> frozenset[str]:
    """The derived parts no producer *client*'s forge wires, waived (a heavy test: kept, never waited on).

    On GitHub (Actions alone, user ruling 2026-11-11) that is each part no Actions job produces
    (:func:`dev_lab.dev.jobparts.off_gate`).
    """
    if FORGE_SERVE in client.backend.producers:
        return frozenset()
    try:
        declared = hosted_parts(pyproject_at(root, sha))
    except (ValueError, subprocess.SubprocessError):
        declared = {}
    return off_gate(derived(statuses), declared)


def publishes_trunk(client: Client, env: Mapping[str, str]) -> bool:
    """Whether this process may push the trunk: on GitHub only the promote job's token (the ruleset admits no other)."""
    return backend_for(client.forge) is not GITHUB or bool(actions_token(client.forge, env))


def promote(
    root: Path, client: Client, sha: str, *, env: Mapping[str, str] = os.environ, walk: bool = False
) -> Promotion:
    """:func:`decide` (*walk*: :func:`newest`), then origin's trunk fast-forwarded on ``promote`` when we publish.

    A process that may not publish the trunk (:func:`publishes_trunk`) gets ``promotable``, the ref untouched.

    The declaration is the one *sha* -- the commit being promoted -- carries, never the working tree's.
    """
    policy = _policy(root, sha)
    found = (newest if walk else decide)(root, client, policy, sha)
    if found.action == 'promote':
        if not publishes_trunk(client, env):
            return Promotion('promotable', found.sha, found.reasons, found.passed_over)
        _publish(root, policy.trunk, found.sha)
    stale = _stale_local(root, policy.trunk, found.sha) if found.action in {'promote', 'current'} else None
    return dataclasses.replace(found, reasons=(*found.reasons, stale)) if stale else found


def _log(root: Path, kind: str, sha: str) -> None:
    """The metrics line of one promotion (:mod:`dev_lab.dev.metrics`): a hand action, or its refusal."""
    named = {'rule': _RULE, 'reason': 'integrate'} if kind == metrics.REFUSAL else {'lab_action': 'integrate promote'}
    metrics.record(kind, root=root, repo=metrics.repo_of(root), vcs_ref_head_revision=sha, **named)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
    said: Callable[[str], None] | None = None,
) -> int:
    """``promote <sha>``: exit 0 done, 2 refused, 1 on a failure.

    ``promote --newest <tip>``: likewise, and each commit passed over is an ALARM line, also handed to *said*.

    ``pending <sha>``: exit 0 answered, 2 refused (no declaration at *sha*), 1 on a failure.
    """
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.integrate', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    promoting = verbs.add_parser('promote')
    promoting.add_argument('--newest', action='store_true', help='promote the newest first parent that passes')
    promoting.add_argument('sha')
    verbs.add_parser('pending', help='print pending=true while the trunk does not hold <sha>').add_argument('sha')
    args = parser.parse_args(argv)
    root = Path.cwd() if cwd is None else cwd
    try:
        fetch(root)
        if args.verb == 'pending':
            emit(f'pending={str(pending(root, _policy(root, args.sha), args.sha)).lower()}')
            return 0
        found = promote(root, client or client_for(root), args.sha, walk=args.verb == 'promote' and args.newest)
        trunk = _policy(root, args.sha).trunk
    except IntegrateRefused as refused:
        _log(root, metrics.REFUSAL, args.sha)
        emit(f'[integrate] REFUSED: {refused}', err=True)
        return 2
    except (ForgeCallFailed, OSError) as failed:
        emit(f'[integrate] {failed}', err=True)
        return 1
    for over in found.passed_over:  # never a quiet refusal: each commit passed over is said, with why
        alarm = f'[integrate] ALARM: {over.sha[:12]} passed over: ' + '; '.join(over.reasons)
        emit(alarm, err=True)
        if said is not None:
            said(alarm)
    if found.action == 'refused':
        _log(root, metrics.REFUSAL, args.sha)
        emit(f'[integrate] REFUSED: {trunk} stays where it is.', err=True)
        for reason in found.reasons:
            emit(f'[integrate]   {reason}', err=True)
        return 2
    _log(root, metrics.HAND_ACTION, args.sha)
    for reason in found.reasons:
        emit(f'[integrate]   {reason}')
    if found.action == 'promotable':
        emit(
            f'[integrate] {found.sha} may promote, and {trunk} stays where it is: on GitHub the ruleset admits a '
            f'push of {trunk} from the nightly promote job alone (ci.yml jobs.promote, cron "{NIGHTLY_CRON}" UTC), '
            f'which promotes a green {_policy(root, args.sha).integration} tip. When it ran: '
            f'gh run list --workflow ci.yml --event schedule'
        )
        return 0
    verb = 'already at' if found.action == 'current' else 'fast-forwarded to'
    emit(f'[integrate] origin/{trunk} {verb} {found.sha}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
