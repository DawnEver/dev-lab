"""The forge credentials of this machine against its declaration: read by ``devhost drift``, applied by its doors.

A development machine declares, per forge host, the logins its agents use (``[dev] forges.<host>``) and the helper
git must read for that host (``[dev] helpers.<host>``; the family declares ``store``). Tokens never rotate by default
(user ruling 2026-11-20), so a credential is placed ONCE and its absence is drift, not a schedule:

- each declared login must have a line in the store for that host; its door is :mod:`dev_lab.dev.devcredential`;
- the helper list for ``https://<host>`` must be exactly ``["", "store"]`` -- the inherited helpers reset, then the
  store, so ONLY ``~/.git-credentials`` answers for that host. STORE FIRST, HELPER SECOND: switching to the store
  while it lacks a declared login cuts the host off the forge (the machine's working helper is reset away), so the
  place door switches it itself once every declared login is stored, and ``devhost use-store --host H`` refuses
  while one is missing (measured 2026-11-21: offered before any token existed, it cost a workstation the forge).

PRESENCE ONLY: a store line is parsed for its scheme, user and host; the secret part is never read into a value,
printed, or hashed. ``git credential`` is never run (it may prompt, and it would return the secret).
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.checkout import git_out
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'LOGIN_DOOR', 'PLACE_DOOR', 'STORE_ONLY', 'USE_STORE_DOOR', 'add_use_store', 'drift', 'helpers', 'store_lines',
    'stored_logins', 'unstored', 'use_declared', 'use_store',
]  # fmt: skip

#: The host-scoped helper list that reads only the store.
STORE_ONLY: Final = ['', 'store']
#: The door placing one minted token for a declared login.
#: The door that stores a token already in hand for one forge, named by host (never the checkout's forge by default).
LOGIN_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.forge auth login --host {{host}}'
PLACE_DOOR: Final = (
    f'{running_interpreter()} -m dev_lab.dev.devcredential --login {{login}} '
    '--forge-config <forge host file> < <minted token file>'
)
#: The door making a host read only the store.
USE_STORE_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost use-store --host {{host}}'
#: git's store file.
STORE: Final = Path.home() / '.git-credentials'


def helpers(host: str) -> list[str]:
    """The credential helpers configured for ``https://<host>`` alone (an empty entry resets the inherited list)."""
    said = git_out(Path.cwd(), 'config', '--global', '--get-all', f'credential.https://{host}.helper')
    return [line.strip() for line in (said or '').splitlines()]


def use_store(host: str) -> None:
    """Make ``https://<host>`` read ONLY the store: reset the inherited helpers for that host, then ``store``."""
    git, key = shutil.which('git') or 'git', f'credential.https://{host}.helper'
    _door.run([git, 'config', '--global', '--unset-all', key], capture_output=True, check=False)
    for value in STORE_ONLY:
        _door.run([git, 'config', '--global', '--add', key, value], capture_output=True, check=True)


def add_use_store(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``use-store`` verb on *verbs* (the ``devhost`` subparsers)."""
    storing = verbs.add_parser('use-store', help='make one declared forge host read only the git credential store')
    storing.add_argument('--host', required=True, help='a forge host this machine declares the store helper for')


def use_declared(
    dev: Mapping[str, Any], host: str, apply: Callable[[str], None] = use_store, store: Path | None = None
) -> int:
    """Make *host* read only the store, refused unless declared AND the store holds every declared login.

    Reading only a store that lacks a login *dev* declares for *host* cuts the host off the forge (2026-11-21).
    """
    if dev.get('helpers', {}).get(host) != 'store':
        emit(f'use-store: refused -- this machine declares no store helper for {host} ([dev] helpers.{host})')
        return 2
    if absent := unstored(dev, host, store_lines(STORE if store is None else store)):
        emit(f'use-store: refused -- the store holds no credential for {host} login(s) {absent}; reading only it '
             'would cut this host off the forge. Mint each (forge token mint, a one-code consent plan), then place '
             f'it: {PLACE_DOOR.format(login=absent[0])} -- placing switches the helper itself')  # fmt: skip
        return 2
    apply(host)
    emit(f'{host}: git reads only the store (credential.https://{host}.helper = "", store)')
    return 0


def stored_logins(host: str, lines: Iterable[str]) -> set[str]:
    """The users with a store line for *host*; each line is cut at its last ``@`` and the secret is never kept."""
    found: set[str] = set()
    for raw in lines:
        scheme, sep, rest = raw.strip().partition('://')
        if not sep or scheme != 'https' or '@' not in rest:
            continue
        userinfo, _, where = rest.rpartition('@')
        if where.split('/', 1)[0].split(':', 1)[0].lower() == host.lower():
            found.add(userinfo.split(':', 1)[0])
    return found


def unstored(dev: Mapping[str, Any], host: str, lines: Iterable[str], placed: str = '') -> list[str]:
    """The logins *dev* declares for *host* with no line in *lines* (*placed* counts as stored)."""
    held = stored_logins(host, lines) | ({placed} if placed else set())
    return [login for login in dev.get('forges', {}).get(host, []) if login not in held]


def store_lines(store: Path) -> list[str]:
    """*store*'s lines (none when it is unreadable); callers keep only scheme, user and host of each."""
    try:
        return store.read_text(encoding='utf-8').splitlines()
    except OSError:
        return []


def drift(
    dev: Mapping[str, Any],
    *,
    helpers_for: Callable[[str], list[str]] = helpers,
    store: Path | None = None,
) -> list[str]:
    """One line per declared forge login or helper this machine departs from, each naming its door."""
    found: list[str] = []
    lines = store_lines(STORE if store is None else store)
    declared_helpers = dev.get('helpers', {})
    for host, logins in sorted(dev.get('forges', {}).items()):
        if not logins:
            continue
        want = declared_helpers.get(host)
        if want != 'store':
            found.append(f'forge {host}: no store helper declared ([dev] helpers.{host} = "store"), so no placed '
                         'token is read -- declare it in the family file through its pull request')  # fmt: skip
            continue
        if absent := unstored(dev, host, lines):
            found += [
                f'forge {host}: no stored credential for declared login {login!r} -- mint one (forge token mint, a '
                f'one-code consent plan), then {PLACE_DOOR.format(login=login)} (placing switches git to the store); '
                f'a token in hand: {LOGIN_DOOR.format(host=host)}'
                for login in absent
            ]
        elif (have := helpers_for(host)) != STORE_ONLY:
            found.append(f'forge {host}: git reads helpers {have}, declared only the store {STORE_ONLY} -- '
                         f'{USE_STORE_DOOR.format(host=host)}')  # fmt: skip
    return found
