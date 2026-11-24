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

GPFS REFUSES POSIX ACLS (measured 2026-11-24: ``setfacl: /gpfs01/home/alyyw103: Operation not supported``), so on that
refusal the grant falls back to MODE BITS: every path it will touch (the ancestor chain, *user*'s directories under
the target) has its exact mode and group recorded FIRST (``stat -c '%a %g %G|%n'``), with each owner's groups
(``id -G``). Only the GROUP bits ever widen (``g+x`` on the ancestors, ``g+rwx`` on the target's directories), and
only when every touched path's group is one every owner is in AND that group is narrower than the site: a group the
cluster declares site-wide (:data:`SITE_WIDE_GROUPS`; on Ada ``domain users``, the whole university) is refused, as
is a cluster that declares none. The OTHER bits never widen (user ruling 2026-11-24). Refused, NOTHING is written:
the door names why, that only the owners' admin or a site admin can remove the path, the exact ``rm -rf`` for that
request, and the census per owner. The ``finally`` restores each recorded mode exactly and verifies it by
re-reading ``stat -c %a``; a mode left changed fails the door, named with what it was.

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

__all__ = [
    'CENSUS_MARK', 'MODES_MARK', 'RECORD_MARK', 'RESTORE_MARK', 'SITE_WIDE_GROUPS', 'VERIFY_MARK', 'main', 'reclaim',
]  # fmt: skip

#: How the census line begins (the account's ``$HOME``, then the owner counts).
CENSUS_MARK: Final = 'printf "home %s\\n" "$HOME"'
#: How the ACL re-read after the revoke begins.
VERIFY_MARK: Final = 'getfacl -p'
#: Per cluster, the groups that span the whole site: a widening to one is refused. Declared here because the family
#: layer's ``[hpc.clusters.<name>]`` is lab-commons' closed schema (an unknown key there refuses every load). A
#: cluster absent here widens nothing. Ada: measured 2026-11-24 (``look stuck``), every account's primary group.
SITE_WIDE_GROUPS: Final = {'ada': frozenset({'domain users'})}
#: How the mode record begins: ``<octal mode> <gid> <group>|<path>`` per touched path, then ``groups <owner> <gids>``.
RECORD_MARK: Final = 'stat -c "%a %g %G|%n"'
#: How the restore begins: ``<mode> <path>`` lines on stdin, each chmodded back.
RESTORE_MARK: Final = 'while read -r mode path; do [ -e "$path" ] && chmod'
#: How the re-read of the restored modes begins: ``<mode> <path>`` per recorded path that still exists.
MODES_MARK: Final = 'while read -r mode path; do [ -e "$path" ] && stat'
_UNSUPPORTED: Final = 'Operation not supported'
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


class _Refused(Exception):
    """No acceptable group: nothing may be widened, nothing was written."""


def _apply(
    user: str,
    *,
    run: dict[str, Runner],
    home: str,
    path: str,
    counts: dict[str, int],
    cluster: str,
    say: Callable[[str], None],
) -> int:
    owners = sorted(owner for owner in counts if owner != user)
    target, mine = shlex.quote(f'{home}/{path}'), run[user]
    chain = [shlex.quote(one) for one in _ancestors(home, path)]
    code, step, undo = 0, user, []
    try:
        _grant(user, mine, target=target, chain=chain, owners=owners, cluster=cluster, undo=undo, say=say)
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
    except _Refused as why:
        say(
            f"reclaim-foreign: refused, nothing was written -- {why}: only the owners' admin or a site admin can "
            f'remove {home}/{path}'
        )
        say(f'  request: rm -rf {home}/{path}')
        for owner in owners + [user] * (user in counts):
            say(f'  {owner}: {counts[owner]} entries')
        code = 2
    except _FAILED as failed:
        say(f'reclaim-foreign: {step}: failed mid-way -- {failed}; undoing every grant')
        code = 2
    finally:
        for one in undo:
            code = max(code, one())
    return code


def _grant(
    user: str,
    mine: Runner,
    *,
    target: str,
    chain: list[str],
    owners: list[str],
    cluster: str,
    undo: list[Callable[[], int]],
    say: Callable[[str], None],
) -> None:
    """Open the chain to every owner -- ACLs, else (GPFS) mode bits; each undo lands in *undo* BEFORE its write."""
    acls = [f'setfacl -m u:{o}:x {one}' for o in owners for one in chain]
    acls += [f'find {target} -type d -user {user} -exec setfacl -m u:{o}:rwx {{}} +' for o in owners]
    undo.append(functools.partial(_revoke, mine, target=target, chain=chain, user=user, owners=owners, say=say))
    try:
        granted = mine(' && '.join(acls) + ' && echo granted', None)
    except _FAILED as failed:
        if _UNSUPPORTED not in str(failed):
            raise
        undo.pop()  # the first setfacl was refused: nothing was granted
        say(f'reclaim-foreign: {user}: setfacl -- {_UNSUPPORTED} (GPFS): falling back to mode bits')
    else:
        say(f'reclaim-foreign: {user}: grant -- {granted.strip()}')
        return
    groups = ''.join(f'; echo "groups {o} $(id -G {o})"' for o in owners)
    out = mine(
        f'{RECORD_MARK} {" ".join(chain)} && {{ [ ! -d {target} ] || '
        f'find {target} -type d -user {user} -exec {RECORD_MARK} {{}} +; }}{groups}',
        None,
    )
    recorded, member = [], {}
    for line in out.splitlines():
        if line.startswith('groups '):
            _, owner, *gids = line.split()
            member[owner] = set(gids)
        elif found := re.fullmatch(r'(\d+) (\d+) ([^|]*)\|(.+)', line.strip()):
            recorded.append((found[1], found[2], found[3], found[4]))
    say(f'reclaim-foreign: {user}: recorded {len(recorded)} modes')
    if why := _unacceptable(recorded, member, owners, cluster):
        raise _Refused(why)
    names = sorted({name for _, _, name, _ in recorded})
    say(f'reclaim-foreign: {user}: every owner shares the group {", ".join(map(repr, names))}: group bits')
    record = ''.join(f'{mode} {path}\n' for mode, _, _, path in recorded)
    undo.append(functools.partial(_restore, mine, record=record, user=user, say=say))
    out = mine(
        f'chmod g+x {" ".join(chain)} && find {target} -type d -user {user} -exec chmod g+rwx {{}} + && echo opened',
        None,
    )
    say(f'reclaim-foreign: {user}: chmod g+x ancestors, g+rwx target dirs -- {out.strip()}')


def _unacceptable(
    recorded: list[tuple[str, str, str, str]], member: dict[str, set[str]], owners: list[str], cluster: str
) -> str:
    """Why no group may widen (``''``: every touched path's group is every owner's, and narrower than the site)."""
    if (site := SITE_WIDE_GROUPS.get(cluster)) is None:
        return f'cluster {cluster!r} declares no site-wide groups (SITE_WIDE_GROUPS), so no group is known narrow'
    if not all(gid in member.get(o, set()) for _, gid, _, _ in recorded for o in owners):
        return 'no group every owner shares, and the other bits never widen (user ruling 2026-11-24)'
    if wide := sorted({name for _, _, name, _ in recorded if name in site}):
        return f'the shared group {", ".join(map(repr, wide))} is site-wide on {cluster}'
    return ''


def _restore(mine: Runner, *, record: str, user: str, say: Callable[[str], None]) -> int:
    """Put every recorded mode back, then re-read it: 0 when each matches, 2 named otherwise."""
    try:
        out = mine(f'{RESTORE_MARK} "$mode" "$path"; done; echo restored', record)
        say(f'reclaim-foreign: {user}: restore -- {out.strip()}')
    except _FAILED as failed:
        say(f'reclaim-foreign: the restore failed -- {failed}')
    try:
        now = mine(f'{MODES_MARK} -c "%a $path" "$path"; done', record)
    except _FAILED as failed:
        say(f'reclaim-foreign: modes NOT verified -- the re-read failed: {failed}')
        return 2
    was = dict(line.split(' ', 1)[::-1] for line in record.splitlines())
    seen = dict(line.split(' ', 1)[::-1] for line in now.splitlines() if ' ' in line)
    if wrong := [f'{path}: {mode}, was {was[path]}' for path, mode in seen.items() if was.get(path) != mode]:
        say(f'reclaim-foreign: modes NOT restored: {"; ".join(wrong)} -- chmod them back by hand')
        return 2
    say(f'reclaim-foreign: modes restored and verified (stat: {len(seen)} paths as recorded)')
    return 0


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
    cluster = machine.grant(user).cluster
    return _apply(user, run=run, home=home, path=path, counts=counts, cluster=cluster, say=say)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``reclaim-foreign`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount reclaim-foreign', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='the account whose home holds the entries')
    parser.add_argument('path', help='home-relative path, e.g. ci/experiments/2026-10-13-branch-merge')
    parser.add_argument('--apply', action='store_true', help='grant, delete per owner, revoke (default: the plan)')
    args = parser.parse_args(list(argv or ()))
    connect = functools.partial(grant_runner, timeout=_TIMEOUT_S)
    return reclaim(args.account, args.path, apply=args.apply, connect=connect)
