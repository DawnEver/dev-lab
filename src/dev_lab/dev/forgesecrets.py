"""``forge secrets sync --task <task>``: one ai-lab task's key bundle set on every repo this machine declares.

The same door carries the family review month's two derived facts (:mod:`dev_lab.dev.reviewledger`): ``secrets
store|sync --secret DEV_LAB_LEDGER_TOKEN`` keeps and distributes the ONE ledger's token like a bundle, and ``secrets
month`` writes the machine's month as the repository VARIABLE ``DEV_LAB_REVIEW_MONTH`` (``gh variable set``, the
value on stdin) -- derived data, no secret, from the one source ``section('ai_lab')`` and ``section('review')``.

A task's bundle (:mod:`dev_lab.dev.taskkeys`) lives in ONE secret per repo, named by
:func:`~dev_lab.dev.taskkeys.secret_name`. The repos are this machine's FAMILY -- the machine file's ``[repos]``, the
one member list (:mod:`dev_lab.dev.family.members`) -- each at its declared checkout and placed on its forge by
that checkout's own ``origin`` remote; a name with no checkout is skipped with its reason. The bundle is set through
``gh secret set <NAME> -R <owner>/<repo>``, the value on stdin (GitHub seals it client-side, which ``gh`` does and the
REST door does not), retried through :func:`~dev_lab.dev.netverb.run_network_verb`, whose table names a rate limit
transient and a bad credential or a missing repository refused.

ONLY A GITHUB MEMBER GETS IT (ruling 2026-11-03). Gitea's ``pull_request`` workflow runs the PR branch's own code
with the repository's secrets readable, so a bundle there is a bundle any PR can print; Gitea's review runs on the
isolated judge host with its own key. A member on any other forge is WITHHELD by name (:func:`withheld`), and
:func:`set_secret` refuses one -- and ``family check`` names a non-GitHub member that holds a bundle as a leak.

ONE LOOP EACH, never one around another: a loop here around the door's re-sent a REFUSED write three times
(nine requests), and named nothing but the last message.

THE BUNDLE IS STORED ONCE (user, 2026-11-09: "I have provided the review key bundle countless times"). ``secrets
store --task <task>`` -- the USER's door -- reads it from stdin and hands it to the git credential store, the one place
the family already keeps a secret (:mod:`lab_commons.credentials`: Git Credential Manager / the OS keychain on a
workstation), under ``https://`` :data:`BUNDLE_HOST` with the secret's name as the username, base64-encoded because
the credential protocol is line-based. ``secrets sync`` reads stdin when one is piped, else the stored bundle, so a
rotation is one ``store`` and one ``sync``, and ``family join`` sets a new member's secret with no user step. THE
TRADE-OFF: any process running as this OS user can read the credential store -- as it can every forge token there.

The bundle is never argv, never a file, never a log line: a line names the repo, the secret and the bundle's sha256
prefix only. ``--dry-run`` lists the targets and reads and writes nothing.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.credentials import NoCredential, credential_for, store_credential
from lab_commons.home import repos
from lab_commons.log import emit

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.forge import Forge, UnreadableRemote, forge_from_remote
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.reviewledger import LEDGER_TOKEN, MONTH_VAR, FamilyMonth, declared_month
from dev_lab.dev.taskkeys import secret_name

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    'BUNDLE_HOST',
    'PLAIN_SECRETS',
    'Target',
    'declared',
    'main',
    'set_secret',
    'set_variable',
    'store_bundle',
    'stored_bundle',
    'targets',
    'withheld',
]


#: The credential-store host the task bundles are kept under (a name, never contacted); the username is the secret.
BUNDLE_HOST: Final = 'task-keys.dev-lab.invalid'

#: The secrets that are no task bundle, each kept and synced by its own name (``--secret``).
PLAIN_SECRETS: Final = (LEDGER_TOKEN,)


def store_bundle(name: str, bundle: str) -> None:
    """Keep secret *name*'s *bundle* in the git credential store, replacing the one there (a rotation)."""
    encoded = base64.b64encode(bundle.encode('utf-8')).decode('ascii')
    store_credential(BUNDLE_HOST, name, encoded)


def stored_bundle(name: str) -> str:
    """Secret *name*'s stored value; ``''`` when none is stored."""
    try:
        return base64.b64decode(credential_for(BUNDLE_HOST, username=name)[1]).decode('utf-8')
    except NoCredential:
        return ''


@dataclass(frozen=True)
class Target:
    """One repo the bundle goes to: its declared name, its checkout and its forge."""

    name: str
    checkout: Path
    forge: Forge


def declared() -> dict[str, Path]:
    """Each family member -> its checkout: the machine file's ``[repos]`` (:func:`lab_commons.home.repos`)."""
    return repos()


def targets(repos: Mapping[str, Path]) -> tuple[list[Target], list[str]]:
    """Each declared checkout placed on its forge, and why each that cannot be is skipped."""
    found, skipped = [], []
    for name, where in sorted(repos.items()):
        if not where.is_dir():
            skipped.append(f'{name}: no checkout at {where}')
            continue
        try:
            found.append(Target(name, where, forge_from_remote(where)))
        except (UnreadableRemote, OSError) as unread:
            skipped.append(f'{name}: {unread}')
    return found, skipped


def withheld(target: Target) -> str:
    """Why *target* never receives a bundle (its forge is not GitHub; module docstring), ``''`` when it may."""
    if target.forge.host == GITHUB_HOST:
        return ''
    return (
        f'{target.name}: withheld -- {target.forge.host} runs a PR branch with its secrets readable (ruling 2026-11-03)'
    )


def _gh(target: Target, name: str, bundle: str, *, kind: str = 'secret') -> None:
    """``gh <kind> set``, the value on stdin; a failure names the report's remedy, never the output (it may echo)."""
    argv = ['gh', kind, 'set', name, '-R', f'{target.forge.owner}/{target.forge.repo}']

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _door.run(command, input=bundle, capture_output=True, check=False, **kwargs)

    report = run_network_verb(argv, run=run)
    if not report.ok:
        raise OSError(report.remedy)


def set_secret(target: Target, name: str, bundle: str) -> None:
    """Set secret *name* to *bundle* on *target*'s forge, retried by its one door; the last refusal raises.

    Raises:
        OSError: the door refused or ran out (``gh``'s report, or the forge's ``ForgeCallFailed``).

    """
    if why := withheld(target):
        raise OSError(why)
    _gh(target, name, bundle)


def set_variable(target: Target, name: str, value: str) -> None:
    """Set repository variable *name* to *value* on *target* (``gh variable set``); a non-GitHub member is refused.

    Raises:
        OSError: withheld, or the door refused or ran out.

    """
    if why := withheld(target):
        raise OSError(why)
    _gh(target, name, value, kind='variable')


def _piped() -> str:
    """Stdin when something is piped to it; ``''`` at a terminal, which would otherwise wait for a person."""
    return '' if sys.stdin.isatty() else sys.stdin.read()


def _said(bundle: str) -> str:
    return f'sha256 {hashlib.sha256(bundle.encode()).hexdigest()[:12]}'


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge secrets', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    keep = verbs.add_parser('store', help="keep the task's key bundle (read on stdin) in the credential store")
    sync = verbs.add_parser('sync', help="set the task's key bundle (stdin, else the stored one) on every member")
    for one in (keep, sync):
        which = one.add_mutually_exclusive_group(required=True)
        which.add_argument('--task', help='the ai-lab task, e.g. pr-review')
        which.add_argument('--secret', choices=PLAIN_SECRETS, help='a secret that is no task bundle, by its name')
    sync.add_argument('--dry-run', action='store_true', help='list the targets; read and write nothing')
    month = verbs.add_parser('month', help=f"set {MONTH_VAR} on every GitHub member from this machine's month")
    month.add_argument('--dry-run', action='store_true', help='list the targets and the value; write nothing')
    return parser


def _month(
    found: Sequence[Target], skipped: Sequence[str], month: Callable[[], FamilyMonth | None], *, dry_run: bool,
    write: Callable[[Target, str, str], None],
) -> int:  # fmt: skip
    """``secrets month``: the derived variable on every reachable member; refused (2) when no month is declared."""
    try:
        family = month()
    except ValueError as bad:
        emit(f'[secrets] refused: {bad}', err=True)
        return 2
    if family is None:
        emit('[secrets] refused: this machine declares no review month ([ai_lab.standing] review)', err=True)
        return 2
    value, failed = family.text(), False
    for target in found:
        if dry_run:
            emit(f'[secrets] would set {MONTH_VAR}={value} on {target.forge.identity}')
            continue
        try:
            write(target, MONTH_VAR, value)
        except OSError as refused:
            failed = True
            emit(f'[secrets] {target.forge.identity}: {MONTH_VAR} refused: {refused}', err=True)
            continue
        emit(f'[secrets] {target.forge.identity}: {MONTH_VAR} set ({value})')
    return 1 if failed or skipped else 0


def _reachable(repos: Mapping[str, Path]) -> tuple[list[Target], list[str]]:
    """The targets a bundle may reach, each skipped and withheld one said; the skipped ones' reasons."""
    every, skipped = targets(repos)
    for why in skipped:
        emit(f'[secrets] skipped {why}', err=True)
    for why in filter(None, map(withheld, every)):
        emit(f'[secrets] {why}')
    return [target for target in every if not withheld(target)], skipped


def _store(flag: str, name: str, piped: str, store: Callable[[str, str], None]) -> int:
    """``secrets store``: keep the piped value under *name*; refused (2) when nothing was piped."""
    if not piped.strip():
        emit(f'[secrets] refused: no {name} value on stdin', err=True)
        return 2
    store(name, piped)
    emit(f'[secrets] stored {name} ({_said(piped)}); run `secrets sync {flag}` to reach every member')
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Callable[[], str] | None = None,
    stored: Callable[[str], str] = stored_bundle,
    store: Callable[[str, str], None] = store_bundle,
    members: Callable[[], Mapping[str, Path]] = declared,
    write: Callable[[Target, str, str], None] = set_secret,
    variable: Callable[[Target, str, str], None] = set_variable,
    month: Callable[[], FamilyMonth | None] = declared_month,
) -> int:
    """``secrets store|sync --task|--secret [--dry-run]``, ``secrets month [--dry-run]``.

    Exit 0 done, 1 one target refused or skipped, 2 refused.
    """
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    task, plain = getattr(args, 'task', None), getattr(args, 'secret', None)
    try:
        name = secret_name(task) if task else plain or ''
    except ValueError as bad:
        emit(f'[secrets] refused: {bad}', err=True)
        return 2
    flag = f'--task {task}' if task else f'--secret {plain}'
    read = stdin or _piped
    if args.verb == 'store':
        return _store(flag, name, read(), store)
    found, skipped = _reachable(members())
    if not found:
        emit('[secrets] refused: no [repos] member checkout on a forge in the machine file', err=True)
        return 2
    if args.verb == 'month':
        return _month(found, skipped, month, dry_run=args.dry_run, write=variable)

    def value() -> str:
        return _or_stored(read(), name, stored)

    return _sync(found, skipped, name, flag, dry_run=args.dry_run, value=value, write=write)


def _or_stored(piped: str, name: str, stored: Callable[[str], str]) -> str:
    """The piped value when one was piped, else the one stored under *name*."""
    return piped if piped.strip() else stored(name)


def _sync(
    found: Sequence[Target], skipped: Sequence[str], name: str, flag: str, *, dry_run: bool,
    value: Callable[[], str], write: Callable[[Target, str, str], None],
) -> int:  # fmt: skip
    """``secrets sync``: secret *name* on every reachable member, its value piped else stored."""
    if dry_run:
        for target in found:
            emit(f'[secrets] would set {name} on {target.forge.identity}')
        return 1 if skipped else 0
    bundle = value()
    if not bundle.strip():
        emit(f'[secrets] refused: no {name} value on stdin or stored: `secrets store {flag}`', err=True)
        return 2
    said = _said(bundle)
    failed = False
    for target in found:
        try:
            write(target, name, bundle)
        except OSError as refused:
            failed = True
            emit(f'[secrets] {target.forge.identity}: {name} refused: {refused}', err=True)
            continue
        emit(f'[secrets] {target.forge.identity}: {name} set ({said})')
    return 1 if failed or skipped else 0
