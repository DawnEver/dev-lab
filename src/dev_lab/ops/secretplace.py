"""``ops secret place``: one declared secret file written on the host, its content on stdin, under one consent.

A host's secret files are DECLARED in its config: the judge's token and App-key files, the probe's tokens, the
promote credential, and the root-only environment and key-bundle files. Until this door, a secret minted on one host
had no command that put it on another: the ops account's sudo admits fixed commands only, and install only names
the ``chown`` step. So the door writes exactly one declared path:

    python -m dev_lab.ops.secretplace request --path P < content   # the consent request: {action, subject}
    python -m dev_lab.ops --config C secret place --path P --credential CRED < content   # an ops host
    python -m dev_lab.ops.secretplace place --path P --grant ID < content                # a workstation
    python -m dev_lab.ops.secretplace enter --remote R       # a person at a terminal: asked once, placed, checked
    python -m dev_lab.ops.secretplace distribute --remote R  # then to every account that declares R (one code)
    python -m dev_lab.ops.secretplace migrate --remote R     # once: drop the declared facts an older file restated

* ``enter`` is the person's door: it asks each DECLARED secret key of the reached remote R
  (:attr:`lab_commons.storage.Remote.secret_keys`; its ``credentials_file`` is this machine's own declaration,
  :func:`path_of`) -- never a declared fact such as an S3 access key ID -- shown as typed
  (:func:`dev_lab.dev.ask.value`), builds the file in memory, asks the issuer for the consent of exactly that path
  and content -- the person's one code, also shown as typed -- places it, and lists the remote
  (``python -m dev_lab.dev.storage check``). The secret is typed once and lives only in this process and the placed
  file; a pipe is refused (that is ``request`` / ``place``).

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
import tomllib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit
from lab_commons.storage import Storage, StorageError
from lab_commons.storage import declared as storage_declared

from dev_lab.dev.ask import PASTE_NOTE, AskRefused
from dev_lab.dev.ask import value as asked_value
from dev_lab.dev.storage import check
from dev_lab.dev.toolrelease import resolve
from dev_lab.ops import secretdistribute
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.consent.client import grant, verify_held
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.served import credential_files

__all__ = [
    'ACTION',
    'SecretRefused',
    'add_parser',
    'declared',
    'enter',
    'migrate',
    'path_of',
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
#: Ask one line of the person, shown as typed (``input``'s shape).
type Ask = Callable[[str], str]
#: The issuer's grant of one request file; the held credential file it wrote.
type Grant = Callable[[Path], Path]
#: List one reached remote; what was reached (raises on a refusal).
type Check = Callable[[str], str]


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


def _keys_of(storage: Storage, path: str) -> tuple[str, tuple[str, ...], Mapping[str, str], Mapping[str, str]]:
    """The reached remote whose ``credentials_file`` is *path*: its declared secret keys, ask hints and shapes."""
    wanted = Path(path).expanduser()
    for remote in storage.reach:
        if remote.credentials_file is not None and Path(remote.credentials_file).expanduser() == wanted:
            return remote.name, remote.secret_keys, remote.ask, remote.shape
    msg = (
        f'{path} is the credentials_file of no reached remote: declare [storage.reach.<remote>] credentials_file first'
    )
    raise SecretRefused(msg)


def enter(
    path: str, *, storage: Storage, ask: Ask, tty: bool, grant: Grant, requests: Path, check: Check,
    redeem: Redeem | None = None, say: Callable[[str], None] = lambda _line: None,
    tool: Callable[[], object] | None = None,
) -> list[str]:  # fmt: skip
    """Ask each value once (shown), check it, consent with one code, place it, list the remote; value-free output.

    *tool* resolves what *check* runs with (rclone) and raises naming its install door when it is absent. It is
    called BEFORE anything is asked (2026-11-22: the secret was asked, a code spent and the file placed, and only then
    "rclone is not installed ... run enter again" -- when the install alone was missing).

    Raises:
        SecretRefused: not a terminal, an undeclared path, the check's tool absent (nothing asked), a value that is
            empty, holds control characters or does not match its declared shape (all before the consent code:
            nothing placed), or a refused consent.

    """
    if not tty:
        msg = ('enter asks at a terminal; a pipe goes through '
               '`secretplace request` then `secretplace place --grant <id>`')  # fmt: skip
        raise SecretRefused(msg)
    owners = workstation_declared(storage)
    key = _same(path, owners)
    if key is None:
        msg = f'{path} is not a secret file this machine declares; declared: {sorted(owners) or "none"}'
        raise SecretRefused(msg)
    remote, keys, hints, shapes = _keys_of(storage, key)
    if tool is not None:
        try:
            tool()
        except (StorageError, LookupError, OSError) as absent:
            msg = f'{remote}: nothing was asked and nothing placed -- {absent}; then run enter again'
            raise SecretRefused(msg) from absent
    say(f'[ops secret] {remote}: {PASTE_NOTE}')
    lines = []
    for name in keys:
        try:
            given = asked_value(
                f'{remote} {name}', hint=hints.get(name, ''), shape=shapes.get(name, ''), ask=ask, say=say
            )
        except AskRefused as refused:
            msg = f'{remote} {refused}; nothing was placed'
            raise SecretRefused(msg) from refused
        lines.append(f'{name} = {json.dumps(given)}')
    content = ''.join(f'{line}\n' for line in lines).encode('utf-8')
    asked = requests / f'secret-{remote}.request.json'
    asked.parent.mkdir(parents=True, exist_ok=True)
    asked.write_text(json.dumps(request(key, content)), encoding='utf-8')
    said = [f'[ops secret] {remote}: content sha256 {hashlib.sha256(content).hexdigest()[:12]}; request {asked}']
    held = grant(asked).stem
    verify = redeem or (lambda _found, wanted: verify_held(held, action=ACTION, subject=wanted))
    said.append(place(owners, 'this machine file ([storage.reach.<remote>] credentials_file)', key, content,
                      redeem=verify, credential={}, chown=_own))  # fmt: skip
    try:
        said.append(check(remote))
    except (StorageError, OSError) as refused:
        said.append(f'[ops secret] {remote}: the secret IS PLACED at {key}; only its check failed -- {refused}. '
                    f'Re-run the check alone, no secret and no code: `python -m dev_lab.dev.storage check {remote}`; '
                    'enter again only when that check says the remote refuses these values')  # fmt: skip
    return said


def migrate(remote: str, *, storage: Storage) -> str:
    """Once (D51): rewrite *remote*'s placed file to its declared secret keys, dropping the facts it restated.

    A key the family now declares as a fact is dropped only when the file holds the SAME value; a different value,
    or a key that is neither secret nor declared, is refused by name -- nothing is guessed. Value-free output.

    Raises:
        SecretRefused: no such reached remote, no placed file, or a restated fact that disagrees with its declaration.

    """
    found = next((r for r in storage.reach if r.name == remote), None)
    if found is None or found.credentials_file is None:
        msg = f'this machine declares no [storage.reach.{remote}] credentials_file'
        raise SecretRefused(msg)
    target = Path(found.credentials_file).expanduser()
    held = tomllib.loads(target.read_text(encoding='utf-8'))
    extra = {k: v for k, v in held.items() if k not in found.secret_keys}
    if not extra:
        return f'[ops secret] {remote}: {target} already holds only its secret keys; nothing to migrate'
    for key, value in extra.items():
        if key not in found.options:
            msg = f'{target} holds {key}, neither a secret key of {remote} nor a declared fact: re-enter it'
            raise SecretRefused(msg)
        if str(value) != found.options[key]:
            msg = f'{target} holds a {key} that differs from the declared one: fix the family file or re-enter'
            raise SecretRefused(msg)
    content = ''.join(f'{k} = {json.dumps(v)}\n' for k, v in held.items() if k in found.secret_keys).encode('utf-8')
    fresh = target.with_name(f'.{target.name}.placing')
    with contextlib.suppress(FileNotFoundError):
        fresh.unlink()
    with os.fdopen(os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
        out.write(content)
    fresh.replace(target)
    digest = hashlib.sha256(content).hexdigest()[:12]
    return f'[ops secret] {remote}: migrated {target} to its secret keys (dropped {sorted(extra)}; sha256 {digest})'


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


def path_of(storage: Storage, remote: str) -> str:
    """The ``credentials_file`` this machine declares for *remote* -- its own declaration, never an argument."""
    for found in storage.reach:
        if found.name == remote and found.credentials_file is not None:
            return str(found.credentials_file)
    msg = f'this machine declares no [storage.reach.{remote}] credentials_file: declare it in its host file first'
    raise SecretRefused(msg)


def _distribute(remote: str) -> int:
    """Send the secret placed here to every account that declares *remote*, under one consent code."""
    content = Path(path_of(storage_declared(), remote)).expanduser().read_bytes()
    requests = Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'consent'
    return secretdistribute.run(remote, content, requests=requests, say=emit)


def _by_remote(action: str, remote: str) -> int:
    """``enter --remote`` / ``distribute --remote``: the path comes from this machine's own declaration."""
    if action == 'distribute':
        return _distribute(remote)
    if action == 'migrate':
        emit(migrate(remote, storage=storage_declared()))
        return 0
    for line in enter(
        path_of(storage_declared(), remote), storage=storage_declared(), ask=input, say=emit,
        tty=sys.stdin.isatty(), grant=lambda asked: grant(asked, ask=input),
        check=lambda name: check(name, repo=Path.cwd()), tool=lambda: resolve('rclone'),
        requests=Path('output/logs') / f'{datetime.now(UTC):%y/%m/%d}' / 'consent',
    ):  # fmt: skip
        emit(line)
    return 0


def _by_path(action: str, path: str, held: str) -> int:
    """``request`` / ``place --grant`` (the content on stdin) for one declared path."""
    if action in {'enter', 'distribute', 'migrate'}:
        msg = f'{action} takes --remote <name>: its path is the one this machine declares'
        raise SecretRefused(msg)
    content = sys.stdin.buffer.read()
    if action == 'request':
        emit(json.dumps(request(str(Path(path).expanduser()), content)))
        return 0
    if not held:
        msg = 'place needs --grant <id> (python -m dev_lab.ops.consent grant <request.json> --code <code>)'
        raise SecretRefused(msg)
    emit(place(
        workstation_declared(), 'this machine file ([storage.reach.<remote>] credentials_file)', path, content,
        redeem=lambda _found, wanted: verify_held(held, action=ACTION, subject=wanted), credential={}, chown=_own,
    ))  # fmt: skip
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """``enter``/``distribute --remote R`` (a person at a terminal); ``request``/``place --grant`` (stdin)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.ops.secretplace', description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('request', 'place', 'enter', 'distribute', 'migrate'))
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument('--path', help='a declared secret file (request, place)')
    where.add_argument('--remote', help='a storage remote this machine reaches (enter, distribute, migrate)')
    parser.add_argument('--grant', default='', help='place: the held ops.secret.place credential id the user granted')
    args = parser.parse_args(argv)
    try:
        if args.remote:
            return _by_remote(args.action, args.remote)
        return _by_path(args.action, args.path, args.grant)
    except (SecretRefused, ConsentRefused, StorageError, OSError, ValueError, LookupError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
