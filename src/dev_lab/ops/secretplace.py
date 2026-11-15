"""``ops secret place``: one declared secret file written on the host, its content on stdin, under one consent.

A host's secret files are DECLARED in its config: the judge's token and App-key files, the probe's tokens, the
promote credential, and the root-only environment and key-bundle files. Until this door, a secret minted on one host
had no command that put it on another: the ops account's sudo admits fixed commands only, and install only names
the ``chown`` step. So the door writes exactly one declared path:

    python -m dev_lab.ops.secretplace request --path P < content   # the consent request: {action, subject}
    python -m dev_lab.ops --config C secret place --path P --credential CRED < content

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
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.served import credential_files

__all__ = ['ACTION', 'SecretRefused', 'add_parser', 'declared', 'place', 'request', 'subject']

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


def place(
    config: OpsConfig, path: str, content: bytes, *, redeem: Redeem, credential: Mapping[str, Any],
    chown: Chown, root: Path = Path('/'),
) -> str:  # fmt: skip
    """Write *content* at the declared *path*, owned by its declared reader, mode 0600; what it did, value-free.

    Raises:
        SecretRefused: the path is not declared, the content is empty, or the credential does not consent to exactly
            this path and content.

    """
    owners = declared(config)
    if path not in owners:
        msg = f'{path} is not a secret file {config.path} declares; declared: {sorted(owners) or "none"}'
        raise SecretRefused(msg)
    if not content.strip():
        msg = f'no content on stdin for {path}: pipe the secret in, never pass it as an argument'
        raise SecretRefused(msg)
    try:
        redeem(credential, subject(path, content))
    except ConsentRefused as refused:
        msg = f'{path}: {refused}; grant {json.dumps(request(path, content))} and pass its credential'
        raise SecretRefused(msg) from refused
    target = root / Path(path).relative_to(Path(path).anchor)
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_name(f'.{target.name}.placing')
    with contextlib.suppress(FileNotFoundError):
        fresh.unlink()
    handle = os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, 'wb') as out:
        out.write(content)
    try:
        chown(fresh, owners[path], None)
        fresh.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            fresh.unlink()
    digest = hashlib.sha256(content).hexdigest()[:12]
    return f'[ops secret] placed {path} (sha256 {digest}), owner {owners[path]}, mode 0600'


def add_parser(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``secret place --path P (--credential C | --subject)``: the content is read from stdin, never an argument."""
    placing = verbs.add_parser('secret', help='write one declared secret file (content on stdin) under consent')
    placing.add_argument('action', choices=('place',))
    placing.add_argument('--path', required=True, help='a secret file this host config declares')
    placing.add_argument('--credential', default='', help='an ops.secret.place consent credential file')
    placing.add_argument(
        '--subject', action='store_true', help='print the subject the consent must name; place nothing'
    )


def main(argv: Sequence[str] | None = None) -> int:
    """``request --path P``: print the consent request for the content on stdin; no host config is needed."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.secretplace', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('request',))
    parser.add_argument('--path', required=True)
    args = parser.parse_args(argv)
    emit(json.dumps(request(args.path, sys.stdin.buffer.read())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
