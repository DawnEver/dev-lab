"""``forge secrets sync --task <task>``: one ai-lab task's key bundle set on every repo this machine declares.

``secrets list [--org]`` reads the secret NAMES a member (or its org) holds, read only (:mod:`forgesecretnames`).

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

The bundle is never argv, never a log line: a line names the repo, the secret and the bundle's sha256 prefix only.
``secrets store --from <path>`` reads a bundle the USER placed as a file (ruling 2026-11-10), stores it as stdin
would, then deletes the file; a failure keeps the file and names it. A path inside a git checkout is refused -- a
key file must never sit where git could commit it -- and so is a directory.

``--dry-run`` lists the targets and reads and writes nothing.
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
from dev_lab.dev.forgesecretnames import Reader, listed
from dev_lab.dev.forgework import client_for
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.taskkeys import secret_name

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    'BUNDLE_HOST',
    'Target',
    'declared',
    'main',
    'set_secret',
    'store_bundle',
    'stored_bundle',
    'targets',
    'withheld',
]


#: The credential-store host the task bundles are kept under (a name, never contacted); the username is the secret.
BUNDLE_HOST: Final = 'task-keys.dev-lab.invalid'


def store_bundle(task: str, bundle: str) -> None:
    """Keep *task*'s *bundle* in the git credential store, replacing the one there (a rotation)."""
    encoded = base64.b64encode(bundle.encode('utf-8')).decode('ascii')
    store_credential(BUNDLE_HOST, secret_name(task), encoded)


def stored_bundle(task: str) -> str:
    """*task*'s stored bundle; ``''`` when none is stored."""
    try:
        return base64.b64decode(credential_for(BUNDLE_HOST, username=secret_name(task))[1]).decode('utf-8')
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


def _gh(target: Target, name: str, bundle: str) -> None:
    """``gh secret set``, the bundle on stdin; a failure names the report's remedy, never the output (it may echo)."""
    argv = ['gh', 'secret', 'set', name, '-R', f'{target.forge.owner}/{target.forge.repo}']

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


def _piped() -> str:
    """Stdin when something is piped to it; ``''`` at a terminal, which would otherwise wait for a person."""
    return '' if sys.stdin.isatty() else sys.stdin.read()


def _said(bundle: str) -> str:
    return f'sha256 {hashlib.sha256(bundle.encode()).hexdigest()[:12]}'


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge secrets', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    keep = verbs.add_parser('store', help="keep the task's key bundle (stdin, or --from) in the credential store")
    keep.add_argument('--task', required=True, help='the ai-lab task, e.g. pr-review')
    keep.add_argument(
        '--from',
        dest='source',
        type=Path,
        help='read the bundle from this file instead of stdin, then delete it; refused inside a git checkout',
    )
    sync = verbs.add_parser('sync', help="set the task's key bundle (stdin, else the stored one) on every member")
    sync.add_argument('--task', required=True, help='the ai-lab task, e.g. pr-review')
    sync.add_argument('--dry-run', action='store_true', help='list the targets; read and write nothing')
    names = verbs.add_parser('list', help="print the secret NAMES the checkout's repository (or --org) holds")
    names.add_argument('--org', action='store_true', help="the owner org's secrets, not the repository's")
    names.add_argument('--path', type=Path, default=Path(), help='the checkout whose origin is read (default: .)')
    return parser


def _reachable(repos: Mapping[str, Path]) -> tuple[list[Target], list[str]]:
    """The targets a bundle may reach, each skipped and withheld one said; the skipped ones' reasons."""
    every, skipped = targets(repos)
    for why in skipped:
        emit(f'[secrets] skipped {why}', err=True)
    for why in filter(None, map(withheld, every)):
        emit(f'[secrets] {why}')
    return [target for target in every if not withheld(target)], skipped


def _store(
    task: str, name: str, read: Callable[[], str], store: Callable[[str, str], None], source: Path | None
) -> int:
    """``secrets store``: keep the bundle from *source* when named, else the piped one; refused (2) when none."""
    if source is not None:
        return _store_from(task, name, source, store)
    piped = read()
    if not piped.strip():
        emit(f'[secrets] refused: no {task} key bundle on stdin', err=True)
        return 2
    store(task, piped)
    emit(f'[secrets] stored {name} ({_said(piped)}); run `secrets sync --task {task}` to reach every member')
    return 0


def _in_checkout(path: Path) -> Path | None:
    """The git checkout *path* sits in (a ``.git`` dir or file above it), ``None`` when none."""
    return next((parent for parent in path.parents if (parent / '.git').exists()), None)


def _read_source(task: str, source: Path) -> tuple[str, str]:
    """*source*'s bundle and ``''``, or ``''`` and why it is refused (the file untouched)."""
    if source.is_dir():
        return '', f'{source} is a directory, not a key bundle file'
    if checkout := _in_checkout(source):
        return '', f'{source} sits in the git checkout {checkout}; move it outside any checkout'
    try:
        bundle = source.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as unread:
        return '', f'cannot read {source} ({type(unread).__name__})'
    if not bundle.strip():
        return '', f'{source} holds no {task} key bundle; the file is kept'
    return bundle, ''


def _store_from(task: str, name: str, source: Path, store: Callable[[str, str], None]) -> int:
    """``secrets store --from``: keep the bundle in *source*, then unlink it; refused (2) with the file kept."""
    source = source.absolute()
    bundle, why = _read_source(task, source)
    if why:
        emit(f'[secrets] refused: {why}', err=True)
        return 2
    try:
        store(task, bundle)
    except (OSError, NoCredential) as failed:  # its message is not echoed: it never names a key, but need not
        emit(f'[secrets] refused: storing {source} failed ({type(failed).__name__}); the file is kept', err=True)
        return 2
    try:
        source.unlink()
    except OSError as kept:
        emit(f'[secrets] stored {name} ({_said(bundle)}) but could not delete {source} ({type(kept).__name__}); '
             'delete it by hand', err=True)  # fmt: skip
        return 1
    emit(f'[secrets] stored {name} ({_said(bundle)}) and deleted {source}; '
         f'run `secrets sync --task {task}` to reach every member')  # fmt: skip
    return 0


def _named(task: str) -> str:
    """The task's secret name, ``''`` (said) when the task is malformed."""
    try:
        return secret_name(task)
    except ValueError as bad:
        emit(f'[secrets] refused: {bad}', err=True)
        return ''


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Callable[[], str] | None = None,
    stored: Callable[[str], str] = stored_bundle,
    store: Callable[[str, str], None] = store_bundle,
    members: Callable[[], Mapping[str, Path]] = declared,
    write: Callable[[Target, str, str], None] = set_secret,
    client: Callable[[Path], Reader] = client_for,
) -> int:
    """``secrets store|sync --task <task> [--dry-run]|list``: exit 0 done, 1 one target refused/skipped, 2 refused."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.verb == 'list':
        return listed(client(args.path), org=args.org)
    name = _named(args.task)
    if not name:
        return 2
    read = stdin or _piped
    if args.verb == 'store':
        return _store(args.task, name, read, store, args.source)
    return _sync(args, name, read, stored=stored, members=members, write=write)


def _sync(
    args: argparse.Namespace,
    name: str,
    read: Callable[[], str],
    *,
    stored: Callable[[str], str],
    members: Callable[[], Mapping[str, Path]],
    write: Callable[[Target, str, str], None],
) -> int:
    """``secrets sync``: the bundle set on every reachable member; see :func:`main`'s exit codes."""
    found, skipped = _reachable(members())
    if not found:
        emit('[secrets] refused: no [repos] member checkout on a forge in the machine file', err=True)
        return 2
    if args.dry_run:
        for target in found:
            emit(f'[secrets] would set {name} on {target.forge.identity}')
        return 1 if skipped else 0
    piped = read()
    bundle = piped if piped.strip() else stored(args.task)
    if not bundle.strip():
        emit(f'[secrets] refused: no {args.task} key bundle on stdin or stored: `secrets store --task {args.task}`',
             err=True)  # fmt: skip
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
