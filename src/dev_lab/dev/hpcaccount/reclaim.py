"""``hpcaccount reclaim-foreign --account <user> <path> [--apply]``: what other fleet accounts own there, removed.

MEASURED 2026-11-23 (``hpcaccount look stuck``): 206,412 entries under alyyw103's ``drwx------`` home belonged to five
other fleet accounts, in their ``drwxr-s---`` directories. The account could not remove them (not the owner: chmod
and unlink refused, "Operation not permitted") and the owners could not reach them (the home is ``drwx------``), so
retention kept them, naming each owner (:mod:`dev_lab.dev.accountsweep`). This door is that owner route:

1. the census: who owns how many entries under ``~/<path>``;
2. every owner that is not *user* must be a declared fleet account (a grant this session reaches), else the door is
   refused BEFORE any write;
3. on *user*: ``setfacl -m u:<owner>:x`` on exactly the ancestor chain (the home down to the target's parent), and
   ``u:<owner>:rwx`` on every directory *user* owns under the target (the target included);
4. each owner, through its OWN grant runner, deletes only its own entries (``find <target> -user <owner> -delete``),
   in rounds while any owner still makes progress (one owner's directory may hold another's entry);
5. *user* removes what is left;
6. in a ``finally``: every grant revoked (``setfacl -x``), then VERIFIED by re-reading the ACLs (``getfacl``); a grant
   still there fails the door, named.

Without ``--apply`` it prints the plan with each owner's count and writes nothing. Every step's output is said.
"""

from __future__ import annotations

import argparse
import functools
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.hpc.grants import AccessRefused, Grant, Machine
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.look import home_path
from dev_lab.dev.hpcaccount.storage import UNREACHABLE
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['CENSUS_MARK', 'VERIFY_MARK', 'main', 'reclaim']

#: How the census line begins (the account's ``$HOME``, then the owner counts).
CENSUS_MARK: Final = 'printf "home %s\\n" "$HOME"'
#: How the ACL re-read after the revoke begins.
VERIFY_MARK: Final = 'getfacl -p'
_TIMEOUT_S: Final = 3600.0
_FAILED = (RuntimeError, OSError, subprocess.SubprocessError, Unreachable)


def _census(out: str) -> tuple[str, dict[str, int]]:
    lines = out.splitlines()
    home = next(line[5:].strip() for line in lines if line.startswith('home '))
    counts = {}
    for line in lines:
        if found := re.fullmatch(r'\s*(\d+)\s+(\S+)\s*', line):
            counts[found[2]] = int(found[1])
    return home, counts


def _ancestors(home: str, path: str) -> list[str]:
    parts = path.split('/')
    return [home] + [f'{home}/{"/".join(parts[:n])}' for n in range(1, len(parts))]


def _apply(
    user: str, *, run: dict[str, Runner], home: str, path: str, owners: list[str], say: Callable[[str], None]
) -> int:
    target, mine = shlex.quote(f'{home}/{path}'), run[user]
    chain = [shlex.quote(one) for one in _ancestors(home, path)]
    code, step = 0, user
    try:
        grants = [f'setfacl -m u:{o}:x {one}' for o in owners for one in chain]
        grants += [f'find {target} -type d -user {user} -exec setfacl -m u:{o}:rwx {{}} +' for o in owners]
        say(f'reclaim-foreign: {user}: grant -- ' + mine(' && '.join(grants) + ' && echo granted', None).strip())
        left = dict.fromkeys(owners, -1)
        for round_ in range(1, len(owners) + 2):
            before = dict(left)
            for owner in [o for o in owners if left[o]]:
                step = owner
                out = run[owner](
                    f'find {target} -user {owner} -delete 2>&1 | tail -n 5; '
                    f'echo "left $(find {target} -user {owner} 2>/dev/null | wc -l)"',
                    None,
                )
                say(f'reclaim-foreign: {owner}: round {round_} -- ' + ' | '.join(out.strip().splitlines()))
                found = re.search(r'left (\d+)', out)
                left[owner] = int(found[1]) if found else 0
            if not any(left.values()) or left == before:
                break
        if stuck := {o: n for o, n in left.items() if n}:
            say(f'reclaim-foreign: still owned after the rounds: {stuck}')
            code = 2
        step = user
        out = mine(
            f'find {target} -user {user} -delete 2>&1 | tail -n 5; echo "left $(find {target} 2>/dev/null | wc -l)"',
            None,
        )
        say(f'reclaim-foreign: {user}: the rest -- ' + ' | '.join(out.strip().splitlines()))
        if not re.search(r'left 0\b', out):
            code = 2
    except _FAILED as failed:
        say(f'reclaim-foreign: {step}: failed mid-way -- {failed}; revoking every grant')
        code = 2
    finally:
        code = max(code, _revoke(mine, target=target, chain=chain, user=user, owners=owners, say=say))
    return code


def _revoke(
    mine: Runner, *, target: str, chain: list[str], user: str, owners: list[str], say: Callable[[str], None]
) -> int:
    """Revoke every grant, then re-read the ACLs: 0 when none is left, 2 named otherwise."""
    names = ','.join(f'u:{owner}' for owner in owners)
    try:
        say(
            f'reclaim-foreign: {user}: revoke -- '
            + mine(
                f'setfacl -x {names} {" ".join(chain)}; [ -d {target} ] && '
                f'find {target} -type d -user {user} -exec setfacl -x {names} {{}} +; echo revoked',
                None,
            ).strip()
        )
    except _FAILED as failed:
        say(f'reclaim-foreign: the revoke failed -- {failed}')
    try:
        acl = mine(
            f'{VERIFY_MARK} {" ".join(chain)} 2>/dev/null; [ -d {target} ] && '
            f'find {target} -type d -user {user} -exec {VERIFY_MARK} {{}} +',
            None,
        )
    except _FAILED as failed:
        say(f'reclaim-foreign: grants NOT verified -- the ACL re-read failed: {failed}')
        return 2
    granted = re.compile(rf'^user:({"|".join(map(re.escape, owners))}):', re.MULTILINE)
    if left := [line for line in acl.splitlines() if granted.match(line)]:
        say(f'reclaim-foreign: grants NOT revoked: {"; ".join(left)} -- re-run reclaim-foreign or setfacl -x by hand')
        return 2
    say(f'reclaim-foreign: grants revoked and verified (getfacl: no user:{{{",".join(owners)}}} entry left)')
    return 0


def _looked(
    user: str, path: str, connect: Callable[..., Runner], say: Callable[[str], None]
) -> tuple[Machine, Runner, str] | int:
    """The reached machine, *user*'s runner and its census of ``~/<path>``; 2 when refused (said)."""
    try:
        home_path(path)
    except ValueError as refused:
        say(f'reclaim-foreign: refused -- {str(refused).removeprefix("look: ")}')
        return 2
    try:
        machine = reached_machine([user])
        mine = connect(machine.grant(user))
        return (
            machine,
            mine,
            mine(f'{CENSUS_MARK}; find "$HOME"/{shlex.quote(path)} -printf "%u\\n" | sort | uniq -c', None),
        )
    except Unreachable:
        say(f'reclaim-foreign: {user}: refused -- {UNREACHABLE}')
    except (*_FAILED, PermissionError, LookupError, ValueError) as refused:
        say(f'reclaim-foreign: {user}: refused -- {refused}')
    return 2


def _owner_grants(machine: Machine, owners: list[str], say: Callable[[str], None]) -> dict[str, Grant] | None:
    """Each owner's reached grant; ``None`` when any is undeclared or another role's (each said with its door)."""
    grants, refused = {}, []
    for owner in owners:
        try:
            grants[owner] = machine.grant(owner)
        except (AccessRefused, LookupError) as why:
            refused.append(f'  {owner}: {why}')
    if not refused:
        return grants
    say('reclaim-foreign: refused, nothing was granted -- an owner this session cannot act as:')
    for line in refused:
        say(line)
    return None


def reclaim(
    user: str,
    path: str,
    *,
    apply: bool = False,
    connect: Callable[..., Runner] = grant_runner,
    say: Callable[[str], None] = emit,
) -> int:
    """Remove the entries other fleet accounts own under *user*'s ``~/<path>``; 2 refused, failed or not revoked."""
    found = _looked(user, path, connect, say)
    if isinstance(found, int):
        return found
    machine, mine, out = found
    home, counts = _census(out)
    owners = sorted(owner for owner in counts if owner != user)
    say(f'reclaim-foreign: {home}/{path}{"" if apply else " (dry run)"}')
    for owner in owners:
        say(f'  {owner}: {counts[owner]} entries -- {owner} deletes them through a traverse grant')
    if user in counts:
        say(f'  {user}: {counts[user]} entries -- {user} removes them last')
    grants = _owner_grants(machine, owners, say)
    if grants is None:
        return 2
    if not owners:
        say('reclaim-foreign: no entry another account owns -- retention removes the rest')
    if not owners or not apply:
        return 0
    try:
        run = {name: connect(grants[name]) for name in owners} | {user: mine}
    except (*_FAILED, PermissionError, LookupError) as refused:
        say(f'reclaim-foreign: refused before any grant -- {refused}')
        return 2
    return _apply(user, run=run, home=home, path=path, owners=owners, say=say)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``reclaim-foreign`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount reclaim-foreign', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='the account whose home holds the entries')
    parser.add_argument('path', help='home-relative path, e.g. ci/experiments/2026-10-13-branch-merge')
    parser.add_argument('--apply', action='store_true', help='grant, delete per owner, revoke (default: the plan)')
    args = parser.parse_args(list(argv or ()))
    connect = functools.partial(grant_runner, timeout=_TIMEOUT_S)
    return reclaim(args.account, args.path, apply=args.apply, connect=connect)
