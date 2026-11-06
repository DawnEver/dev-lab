"""``forge secrets sync --task <task>``: one ai-lab task's key bundle set on every repo this machine declares.

A task's bundle (:mod:`dev_lab.dev.taskkeys`) lives in ONE secret per repo, named by
:func:`~dev_lab.dev.taskkeys.secret_name`. The repos are the machine file's ``[serve] repos`` -- the one list this
machine declares -- each at its serve checkout (:func:`dev_lab.dev.servetask.checkout`) and placed on its forge by
that checkout's own ``origin`` remote; a name with no checkout is skipped with its reason:

* GitHub: ``gh secret set <NAME> -R <owner>/<repo>``, the value on stdin (GitHub seals it client-side, which
  ``gh`` does and the REST door does not), retried through :func:`~dev_lab.dev.netverb.run_network_verb`, whose
  table names a rate limit transient and a bad credential or a missing repository refused;
* Gitea: ``PUT <repo>/actions/secrets/<NAME>`` through the forge door (:class:`~dev_lab.dev.forgework.Client`),
  WITHOUT its outbox journal -- a journaled write keeps its body on disk to replay it, and a bundle never touches
  disk. The write is idempotent, so the door's own retry sends a lost answer again.

ONE LOOP EACH, never one around another: a loop here around the door's re-sent a REFUSED write three times
(nine requests), and named nothing but the last message.

The bundle is read from stdin -- never argv, never a file, never a log line: a line names the repo, the secret and
the bundle's sha256 prefix only. ``--dry-run`` lists the targets and reads and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.forge import Forge, UnreadableRemote, forge_from_remote
from dev_lab.dev.forgework import stored_client
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.servelock import forge_home
from dev_lab.dev.servetask import checkout
from dev_lab.dev.taskkeys import secret_name

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping, Sequence

__all__ = ['Target', 'declared', 'main', 'set_secret', 'targets']


@dataclass(frozen=True)
class Target:
    """One repo the bundle goes to: its declared name, its checkout and its forge."""

    name: str
    checkout: Path
    forge: Forge


def declared() -> dict[str, Path]:
    """Each ``[serve] repos`` name -> its serve checkout under the forge home."""
    home = forge_home()
    return {str(name): checkout(home, str(name)) for name in section('serve').get('repos', ())}


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


def _gh(target: Target, name: str, bundle: str) -> None:
    """``gh secret set``, the bundle on stdin; a failure names the report's remedy, never the output (it may echo)."""
    argv = ['gh', 'secret', 'set', name, '-R', f'{target.forge.owner}/{target.forge.repo}']

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _door.run(command, input=bundle, capture_output=True, check=False, **kwargs)

    report = run_network_verb(argv, run=run)
    if not report.ok:
        raise OSError(report.remedy)


def _gitea(target: Target, name: str, bundle: str) -> None:
    client = stored_client(target.forge, cwd=target.checkout)  # no journal: the body would land on disk
    client.call('PUT', f'{client.repo}/actions/secrets/{name}', {'data': bundle})


def set_secret(target: Target, name: str, bundle: str) -> None:
    """Set secret *name* to *bundle* on *target*'s forge, retried by its one door; the last refusal raises.

    Raises:
        OSError: the door refused or ran out (``gh``'s report, or the forge's ``ForgeCallFailed``).

    """
    (_gh if target.forge.host == GITHUB_HOST else _gitea)(target, name, bundle)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge secrets', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    sync = verbs.add_parser('sync', help="set the task's key bundle (read on stdin) on every declared repo")
    sync.add_argument('--task', required=True, help='the ai-lab task, e.g. pr-review')
    sync.add_argument('--dry-run', action='store_true', help='list the targets; read and write nothing')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Callable[[], str] | None = None,
    repos: Callable[[], Mapping[str, Path]] = declared,
    write: Callable[[Target, str, str], None] = set_secret,
) -> int:
    """``secrets sync --task <task> [--dry-run]``: exit 0 every target set, 1 one refused or skipped, 2 refused."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        name = secret_name(args.task)
    except ValueError as bad:
        emit(f'[secrets] refused: {bad}', err=True)
        return 2
    found, skipped = targets(repos())
    for why in skipped:
        emit(f'[secrets] skipped {why}', err=True)
    if not found:
        emit('[secrets] refused: no [serve] repos checkout on a forge in the machine file', err=True)
        return 2
    if args.dry_run:
        for target in found:
            emit(f'[secrets] would set {name} on {target.forge.identity}')
        return 1 if skipped else 0
    bundle = (stdin or sys.stdin.read)()
    if not bundle.strip():
        emit(f'[secrets] refused: no {args.task} key bundle on stdin', err=True)
        return 2
    said = f'sha256 {hashlib.sha256(bundle.encode()).hexdigest()[:12]}'
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
