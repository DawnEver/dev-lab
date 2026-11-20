"""``ops secret place``: one declared secret file written on the host, its content on stdin, under one consent.

A host's secret files are DECLARED in its config: the judge's token and App-key files, the probe's tokens, the
promote credential, and the root-only environment and key-bundle files. Until this door, a secret minted on one host
had no command that put it on another: the ops account's sudo admits fixed commands only, and install only names
the ``chown`` step. So the door writes exactly one declared path:

    python -m dev_lab.ops.secretplace request --path P < content   # the consent request: {action, subject}
    python -m dev_lab.ops --config C secret place --path P --credential CRED < content   # an ops host
    python -m dev_lab.ops.secretplace place --path P --grant ID < content                # a workstation

* An ops host's declared files come from its ops config (:func:`declared`). A workstation has no ops config: its
  declared files are the ``credentials_file`` of every storage remote THIS machine reaches
  (:func:`lab_commons.storage.declared`, read from the machine file), owned by the user running the door
  (:func:`workstation_declared`). Its consent is the held grant ``ID`` the user's code minted
  (``python -m dev_lab.ops.consent grant``), redeemed through :func:`dev_lab.ops.consent.client.verify_held`.

* The consent action is :data:`ACTION`, single use. Its subject binds the path AND the content's sha256, never the
  value, so a credential the user granted for one file cannot write another file, or other bytes to the same one.
* Only a declared path is written. Its owner is the declared role's user, never an argument: the declaration is the
  one source of who reads the file. The mode is always 0600.
* The value never reaches an argv, the audit or the output; only a sha256 prefix does.
* The write is a fresh 0600 file in the same directory, owned before it is renamed over the target, so a reader never
  sees a wider or a partial file.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit
from lab_commons.storage import Storage
from lab_commons.storage import declared as storage_declared

from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.client import verify_held
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.served import credential_files

__all__ = [
    'ACTION',
    'SecretRefused',
    'add_parser',
    'declared',
    'place',
    'request',
    'subject',
    'workstation_declared',
]

ACTION: Final = 'ops.secret.place'

#: Redeem a consent credential for a subject; raises ``ConsentRefused`` when it does not consent.
type Redeem = Callable[[Mapping[str, Any], str], object]
#: Change a path's owner (``shutil.chown``'s shape).
type Chown = Callable[[Path, str | None, str | None], None]


class SecretRefused(RuntimeError):
    """A placement that cannot proceed; the message says why and what to do."""


def subject(path: str, content: bytes) -> str:
    """The consent subject of writing *content* at *path*: both bound, the value itself never carried."""
    text = f'{ACTION}\npath={path}\nsha256={hashlib.sha256(content).hexdigest()}'
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def request(path: str, content: bytes) -> dict[str, str]:
    """The consent request the user grants for this one placement."""
    return {'action': ACTION, 'subject': subject(path, content)}


def declared(config: OpsConfig) -> dict[str, str]:
    """Every secret file *config* declares, mapped to the account that reads it."""
    owners: dict[str, str] = {}
    if (promote := config.promote) is not None:
        owners[promote.credentials] = promote.user
    if (judge := config.judge) is not None:
        owners |= dict.fromkeys(judge.secrets, judge.user)
        owners |= dict.fromkeys(filter(None, (judge.keys_file, judge.environment_file)), 'root')
    if (glass := config.breakglass) is not None:
        owners |= dict.fromkeys(credential_files(glass.tokens, glass.apps), glass.account)
    if (probe := config.probe) is not None:
        owners |= dict.fromkeys(probe.tokens.values(), probe.user)
    if config.environment_file:
        owners[config.environment_file] = 'root'
    return owners


def workstation_declared(storage: Storage | None = None, *, user: str | None = None) -> dict[str, str]:
    """The reached storage remotes' ``credentials_file``s, each owned by *user* (default: the caller)."""
    found = storage_declared() if storage is None else storage
    owner = getpass.getuser() if user is None else user
    return {str(remote.credentials_file): owner for remote in found.reach if remote.credentials_file is not None}


def _same(path: str, owners: Mapping[str, str]) -> str | None:
    """The declared key *path* names, compared after ``~`` expansion; None when it names none."""
    wanted = Path(path).expanduser()
    return next((key for key in owners if Path(key).expanduser() == wanted), None)


def place(
    owners: Mapping[str, str], source: str, path: str, content: bytes, *, redeem: Redeem,
    credential: Mapping[str, Any], chown: Chown, root: Path | None = None,
) -> str:  # fmt: skip
    """Write *content* at the declared *path*, owned by its declared reader, mode 0600; what it did, value-free.

    *owners* is the declared files of *source* (:func:`declared` of an ops config, :func:`workstation_declared` of
    a workstation); *root* defaults to the path's own anchor.

    Raises:
        SecretRefused: the path is not declared, the content is empty, or the credential does not consent to exactly
            this path and content.

    """
    key = _same(path, owners)
    if key is None:
        msg = f'{path} is not a secret file {source} declares; declared: {sorted(owners) or "none"}'
        raise SecretRefused(msg)
    path = key  # the declared spelling is what the consent subject names
    if not content.strip():
        msg = f'no content on stdin for {path}: pipe the secret in, never pass it as an argument'
        raise SecretRefused(msg)
    try:
        redeem(credential, subject(path, content))
    except ConsentRefused as refused:
        msg = f'{path}: {refused}; grant {json.dumps(request(path, content))} and pass its credential'
        raise SecretRefused(msg) from refused
    local = Path(path).expanduser()
    root = Path(local.anchor) if root is None else root
    target = root / local.relative_to(local.anchor)
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_name(f'.{target.name}.placing')
    with contextlib.suppress(FileNotFoundError):
        fresh.unlink()
    handle = os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, 'wb') as out:
        out.write(content)
    try:
        chown(fresh, owners[key], None)
        fresh.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            fresh.unlink()
    digest = hashlib.sha256(content).hexdigest()[:12]
    return f'[ops secret] placed {path} (sha256 {digest}), owner {owners[key]}, mode 0600'


def add_parser(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``secret place --path P (--credential C | --subject)``: the content is read from stdin, never an argument."""
    placing = verbs.add_parser('secret', help='write one declared secret file (content on stdin) under consent')
    placing.add_argument('action', choices=('place',))
    placing.add_argument('--path', required=True, help='a secret file this host config declares')
    placing.add_argument('--credential', default='', help='an ops.secret.place consent credential file')
    placing.add_argument(
        '--subject', action='store_true', help='print the subject the consent must name; place nothing'
    )


def _own(_path: Path, user: str | None, _group: str | None) -> None:
    """A workstation's file is the caller's own: nothing to change; another declared owner is refused."""
    if user not in {None, getpass.getuser()}:
        msg = f"a workstation places only its own user's files, not {user}'s"
        raise SecretRefused(msg)


def main(argv: Sequence[str] | None = None) -> int:
    """``request --path P``: the consent request for stdin; ``place --path P --grant ID``: a workstation's placement."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.secretplace', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('request', 'place'))
    parser.add_argument('--path', required=True)
    parser.add_argument('--grant', default='', help='place: the held ops.secret.place credential id the user granted')
    args = parser.parse_args(argv)
    content = sys.stdin.buffer.read()
    if args.action == 'request':
        emit(json.dumps(request(str(Path(args.path).expanduser()), content)))
        return 0
    if not args.grant:
        emit('refused: place needs --grant <id> (python -m dev_lab.ops.consent grant <request.json> --code <code>)',
             err=True)  # fmt: skip
        return 2
    try:
        said = place(
            workstation_declared(), 'this machine file ([storage.reach.<remote>] credentials_file)', args.path, content,
            redeem=lambda _found, wanted: verify_held(args.grant, action=ACTION, subject=wanted), credential={},
            chown=_own,
        )  # fmt: skip
    except (SecretRefused, ConsentRefused, OSError, ValueError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    emit(said)
    return 0


if __name__ == '__main__':
    sys.exit(main())
