"""The forge credentials of this machine against its declaration: read by ``devhost drift``, applied by its doors.

A development machine declares, per forge host, the logins its agents use (``[dev] forges.<host>``) and the helper
git must read for that host (``[dev] helpers.<host>``; the family declares ``store``). Tokens never rotate by default
(user ruling 2026-11-20), so a credential is placed ONCE and its absence is drift, not a schedule:

- the helper list for ``https://<host>`` must be exactly ``["", "store"]`` -- the inherited helpers reset, then the
  store, so ONLY ``~/.git-credentials`` answers for that host; ``devhost use-store --host H`` applies it;
- each declared login must have a line in the store for that host; its door is :mod:`dev_lab.dev.devcredential`.

PRESENCE ONLY: a store line is parsed for its scheme, user and host; the secret part is never read into a value,
printed, or hashed. ``git credential`` is never run (it may prompt, and it would return the secret).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev.checkout import git_out
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'PLACE_DOOR',
    'STORE_ONLY',
    'USE_STORE_DOOR',
    'drift',
    'helpers',
    'store_lines',
    'stored_logins',
    'use_store',
]

#: The host-scoped helper list that reads only the store.
STORE_ONLY: Final = ['', 'store']
#: The door placing one minted token for a declared login.
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
        if (have := helpers_for(host)) != STORE_ONLY:
            found.append(f'forge {host}: git reads helpers {have}, declared only the store {STORE_ONLY} -- '
                         f'{USE_STORE_DOOR.format(host=host)}')  # fmt: skip
        stored = stored_logins(host, lines)
        found += [
            f'forge {host}: no stored credential for declared login {login!r} -- mint one (forge token mint, a '
            f'one-code consent plan), then {PLACE_DOOR.format(login=login)}'
            for login in logins
            if login not in stored
        ]
    return found
