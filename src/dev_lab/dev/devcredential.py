"""``python -m dev_lab.dev.devcredential --login L --forge-config F [--url U] [--host-config H]`` < token.

PLACES ONE MINTED FORGE TOKEN IN THIS DEVELOPMENT MACHINE'S git credential store: the workstation counterpart of
``hpcaccount credential``, through the same core (:func:`dev_lab.dev.credstore.place_verified`: staged alone,
verified by the forge's own ``auth role`` as *L*, backup, then replace; a refusal leaves the store untouched). The
token is read from stdin, never argv; output names it only by a sha256 prefix.

DECLARED ONLY, before anything is staged: the login must be one this machine declares for that forge host
(``[dev] forges.<host>`` of its host file, :mod:`dev_lab.dev.devhost`) AND a login the forge host's config declares
(``[ops.forge.accounts]``, where ``forge token mint`` mints it); the url must be on that forge. The store helper is a
DECLARATION (``[dev] helpers.<host> = "store"``): the door applies it -- the host's inherited helpers reset by an
empty entry, then ``store``, so ONLY ``~/.git-credentials`` answers for that host and every other host keeps the
machine's own helper. A host with no declared store helper is refused: a placement git never reads is dead.

Getting the token: a one-code consent plan whose step is ``forge token mint`` with ``stdout_local``
(:mod:`dev_lab.dev.planrun`) writes it owner-only on this machine; pipe that file into this door, then delete it.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import lab_commons.launch as _door
from lab_commons import config as machineconfig
from lab_commons.log import emit

from dev_lab.dev import devhost
from dev_lab.dev.checkout import git_out
from dev_lab.dev.credstore import CredentialRefused, DeclaredForge, Shell, digest, place_verified, read_forge
from dev_lab.dev.venvpath import running_interpreter

__all__ = ['DOOR', 'STORE_ONLY', 'helpers', 'local_shell', 'main', 'place', 'use_store']

#: This door, as a remedy names it.
DOOR: Final = (
    f'{running_interpreter()} -m dev_lab.dev.devcredential --login <login> '
    '--forge-config <forge host file> < <minted token file>'
)


def local_shell(cmd: str, stdin: str | None) -> str:
    """Run *cmd* in this machine's POSIX shell (Git's ``sh`` on Windows); raise on a non-zero exit."""
    done = _door.run(
        [shutil.which('sh') or 'sh', '-c', cmd],
        input=stdin, capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    if done.returncode:
        msg = f'exit {done.returncode}: {done.stderr.strip()[-300:]}'
        raise RuntimeError(msg)
    return done.stdout


def helpers(host: str) -> list[str]:
    """The credential helpers configured for ``https://<host>`` alone (an empty entry resets the inherited list)."""
    said = git_out(Path.cwd(), 'config', '--global', '--get-all', f'credential.https://{host}.helper')
    return [line.strip() for line in (said or '').splitlines()]


def use_store(host: str) -> None:
    """Make ``https://<host>`` read ONLY the store: reset the inherited helpers for that host, then ``store``."""
    git, key = shutil.which('git') or 'git', f'credential.https://{host}.helper'
    _door.run([git, 'config', '--global', '--unset-all', key], capture_output=True, check=False)
    for value in ('', 'store'):
        _door.run([git, 'config', '--global', '--add', key, value], capture_output=True, check=True)


#: The host-scoped helper list that reads only the store.
STORE_ONLY: Final = ['', 'store']


def _store_only(
    host: str, helpers_for: Callable[[str], list[str]], store_for: Callable[[str], None], say: Callable[[str], None]
) -> bool:
    """Apply the declared store helper for *host* unless it is already the only one; ``False`` when it failed."""
    if helpers_for(host) == STORE_ONLY:
        return True
    try:
        store_for(host)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as failed:
        say(f'credential: refused -- the store helper for {host} could not be set: {failed}')
        return False
    say(f'{host}: git reads only the store (credential.https://{host}.helper = "", store)')
    return True


def _declared(*, login: str, token: str, url: str, forge: DeclaredForge, dev: Mapping[str, Any]) -> tuple[str, str]:
    """``(why refused, '')`` or ``('', repo url)``: every check made before anything is staged or configured."""
    if not token:
        return 'no token on stdin', ''
    if login not in forge.accounts:
        return f'{login!r} is not in {forge.path} [ops.forge.accounts]: cannot be minted', ''
    try:
        repo = forge.url_for(login, url)
    except CredentialRefused as refused:
        return str(refused), ''
    host = urlsplit(repo).hostname or ''
    mine = dev.get('forges', {}).get(host, [])
    if login not in mine:
        return f'{login!r} is not a login this machine declares for {host} ([dev] forges: {mine})', ''
    if dev.get('helpers', {}).get(host) != 'store':
        return f'{host} declares no store helper ([dev] helpers.{host} = "store"), so git would not read it', ''
    return '', repo


def place(
    *,
    login: str,
    token: str,
    url: str,
    forge: DeclaredForge,
    dev: Mapping[str, Any],
    say: Callable[[str], None],
    shell: Shell = local_shell,
    helpers_for: Callable[[str], list[str]] = helpers,
    store_for: Callable[[str], None] = use_store,
    python: str = sys.executable,
) -> int:
    """Place *token* as *login* after the declarations allow it and the forge answers as *login*; 2 on refusal."""
    why, repo = _declared(login=login, token=token, url=url, forge=forge, dev=dev)
    if why:
        say(f'credential: refused -- {why}')
        return 2
    host = urlsplit(repo).hostname or ''
    if not _store_only(host, helpers_for, store_for, say):
        return 2
    role = shlex.join([Path(python).as_posix(), '-m', 'dev_lab.dev.forge', 'auth', 'role', '--url', repo])
    try:
        refusal, backup = place_verified(shell, login=login, token=token, repo=repo, role=role)
    except (RuntimeError, OSError, ValueError) as failed:
        say(f'credential: refused -- {failed}')
        return 2
    if refusal:
        say(f'credential: refused -- {refusal}')
        return 2
    say(f'the forge answers as {login} on {repo}; placed {digest(token)} for {host} (0600) {backup}'.strip())
    return 0


def _dev_table(host_config: Path | None) -> dict[str, Any]:
    if host_config is not None:
        return devhost.declared(host_config, host_config.parent.parent / 'family.toml')
    own = machineconfig.machine().get(devhost.OWN_TABLE, {})
    if not own.get('host') or not own.get('source'):
        return {}
    source = Path(own['source'])
    return devhost.declared(source / 'hosts' / f'{own["host"]}.toml', source / 'family.toml')


def main(argv: Sequence[str] | None = None) -> int:
    """Place the token on stdin for a declared login of this machine."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.devcredential', description=__doc__.splitlines()[0])
    parser.add_argument('--login', required=True, help="a login this machine's host file declares")
    parser.add_argument('--forge-config', type=Path, required=True, help="the forge host's reviewed config")
    parser.add_argument('--url', default='', help='a repository url on that forge')
    parser.add_argument('--host-config', type=Path, default=None, help="this machine's host file (default: render's)")
    args = parser.parse_args(argv)
    try:
        forge = read_forge(args.forge_config)
    except CredentialRefused as refused:
        emit(f'credential: refused -- {refused}')
        return 2
    token = sys.stdin.read().strip()
    dev = _dev_table(args.host_config)
    return place(login=args.login, token=token, url=args.url, forge=forge, dev=dev, say=emit)


if __name__ == '__main__':
    raise SystemExit(main())
