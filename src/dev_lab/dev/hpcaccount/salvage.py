"""``python -m dev_lab.dev.hpcaccount salvage --account <user> <path> [--apply]`` -- an account's own git work, home.

User ruling 2026-11-25: an account is cleaned completely. Before its contents may go, every commit on no remote and
every uncommitted change in its checkouts must be on the workstation, and no door brought them: ``look ... inventory``
only REPORTS what is not pushed, ``archive`` tars a path to a run store (none was declared), and raw ssh is
forbidden. Measured that day: one research account held eleven checkouts NOT PUSHED under ``~/src`` alone (40
commits in one, dirty files and untracked notes in others).

This door finds every checkout under ``~/<path>`` (``.`` is the home) -- nested ones and worktrees included, by the
inventory's own discovery -- and for each brings back, through the grant's own Runner pinned to the declared login
host (:mod:`~dev_lab.dev.hpcaccount.salvageread`, nothing written on the account):

* ``commits.bundle`` -- ``git bundle`` of every commit no remote-tracking ref reaches
  (:data:`~dev_lab.dev.hpcaccount.inventory.UNPUSHED`, the inventory's definition); a checkout whose every commit is
  on a remote has no bundle, and says so;
* ``tracked.diff`` -- ``git diff HEAD --binary``: staged and unstaged tracked changes;
* ``untracked.tar`` -- the untracked, non-ignored files of at most :data:`CARRIED` bytes; a larger one is listed by
  name and size in the manifest, never carried (``--carried`` moves the limit).

They land under the INVOKING checkout's dated output (``<output>/<yy>/<mm>/<dd>/salvage/<user>/<checkout>/``, the
checkout's home-relative path), beside ``manifest.json`` (at ``salvage/<user>/<path>/``): each file's sha256 and
bytes, and per checkout its origin, remotes, branch, HEAD, shared git directory and counts. Without ``--apply`` the
plan is printed and nothing is written. A checkout git cannot read is refused by name with git's own words, the
others are still salvaged, and the door exits 2. ``salvage-fetch`` (:mod:`~dev_lab.dev.hpcaccount.salvagefetch`)
then fetches a salvaged bundle into a local repo; nothing here touches any repo.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import io
import json
import subprocess
import tarfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.log import emit

from dev_lab.dev import gitdirs
from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.hpcaccount import salvageread
from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target
from dev_lab.dev.hpcaccount.inventory import sized
from dev_lab.dev.hpcaccount.look import home_path
from dev_lab.dev.hpcaccount.storage import UNREACHABLE, Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['CARRIED', 'FILES', 'KIND', 'MANIFEST', 'TIMEOUT', 'main', 'plan_rows', 'salvage', 'salvage_path']

#: The largest untracked file carried as data, in bytes. Hand-made work -- sources, notes, tables, configs -- sits
#: far below it; above it sit build products and results (a compiled extension, a mesh, a field dump), which
#: regenerate or belong to ``hpcaccount archive``, and would cost 4/3 of their size on the Runner's stdout.
CARRIED: Final = 1 << 20
#: The dated output kind the salvage lands under.
KIND: Final = 'salvage'
#: The manifest's name.
MANIFEST: Final = 'manifest.json'
#: The file each section lands in.
FILES: Final = {'bundle': 'commits.bundle', 'diff': 'tracked.diff', 'untracked': 'untracked.tar'}
#: Seconds one account read may take: a checkout's data is one read.
TIMEOUT: Final = 3600.0
_GIT_S: Final = 120


class _Refused(Exception):
    """One checkout (or the whole door) is refused; the message names why and the door."""


def salvage_path(path: str) -> str:
    """*path* when it is ``.`` (the home) or a home-relative path of names (:func:`~.look.home_path`)."""
    return path if path == '.' else home_path(path)


def _runner(user: str, connect: Callable[..., Runner], pin: Pin) -> tuple[str, Runner]:
    grant = next(g for g in reached_machine([user]).grants if g.user == user)
    target = declared_target(grant, connect(grant))
    if isinstance(target, str):
        raise _Refused(target)
    return target.host, pin(grant, target.host)


def _files(listed: list[salvageread.Untracked]) -> str:
    return f'{len(listed)} ({sized(sum(u.bytes for u in listed))})'


def plan_rows(user: str, plan: salvageread.Plan, carried: int) -> list[str]:
    """The plan as lines a person reads: per checkout its origin, HEAD and what it holds of its own."""
    rows = [f'salvage: {plan.path} -- {len(plan.checkouts)} checkout(s), {len(plan.refused)} unreadable']
    for found in plan.checkouts:
        head = f'{found.branch or "detached"} {found.head[:10] or "(no commit)"}'
        bundle = (
            f'{found.unpushed} commit(s) on no remote, bundle {sized(found.bundle_bytes)}'
            if found.bundle_bytes
            else 'bundle empty: every commit is on a remote'
        )
        rows.append(f'  {found.path}: origin {found.origin or "(none)"}; {head}')
        rows.append(
            f'    {bundle}; stash {found.stash or "?"}; dirty {found.changed} path(s), diff {sized(found.diff_bytes)}; '
            f'untracked carried {_files(found.carried(carried))}, listed only {_files(found.listed(carried))}'
        )
        over = f'    listed only (over {sized(carried)}):'
        rows.extend(f'{over} {u.path} {sized(u.bytes)}' for u in found.listed(carried))
        if why := found.unread():
            rows.append(f'    UNREADABLE -- {why}')
    rows.extend(f'  {path}: REFUSED -- {_refusal(user, path, why)}' for path, why in plan.refused)
    rows.extend(f'salvage: unread line {line!r}' for line in plan.unread)
    return rows


def _refusal(user: str, path: str, why: str) -> str:
    """Why git-unreadable checkout *path* is refused, and its doors."""
    return (
        f'git cannot read it ({why}): nothing of it can be salvaged through git; read it with `python -m '
        f'dev_lab.dev.hpcaccount look --account {user} inventory {path}` and keep its files with `hpcaccount archive`'
    )


def _verified(
    name: str, data: bytes, found: salvageread.Checkout, carried: int, say: Callable[[str], None]
) -> list[str]:
    """What a section's bytes prove: the bundle's heads, the tar's members; raises when they prove nothing."""
    if name == 'untracked':
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            members = [m.name.removeprefix('./') for m in tar.getmembers()]
        if missing := sorted({u.path for u in found.carried(carried)} - set(members)):
            say(f'salvage: {found.path}: untracked file(s) gone since the plan, not carried: {", ".join(missing)}')
        return members
    if name == 'bundle':
        done = _door.run(
            ['git', 'bundle', 'list-heads', '-'], input=data, capture_output=True, check=False, timeout=_GIT_S
        )
        if done.returncode:
            msg = f'the bundle does not read as one: {done.stderr.decode("utf-8", "replace").strip()}'
            raise _Refused(msg)
        return done.stdout.decode('utf-8', 'replace').splitlines()
    return []


def _bring(
    run: Runner, found: salvageread.Checkout, carried: int, home: Path, say: Callable[[str], None]
) -> dict[str, Any]:
    """Fetch *found*'s sections and write them under *home*; its files' manifest entries."""
    if why := found.unread():
        raise _Refused(why)
    data, status, refused = salvageread.sections(run(salvageread.data_command(found.path, carried), None))
    if refused:
        raise _Refused('; '.join(refused))
    wanted = {'bundle': bool(found.bundle_bytes), 'diff': bool(found.head), 'untracked': True}
    failed = [f'{n} exited {status.get(n) or "no status"}' for n, w in wanted.items() if w and status.get(n) != '0']
    if failed:
        msg = f'{", ".join(failed)} on the account: re-run; if it repeats, read the checkout with `look ... inventory`'
        raise _Refused(msg)
    files: dict[str, Any] = {}
    target = home if found.path == '.' else home / found.path
    for name, blob in data.items():
        proof = _verified(name, blob, found, carried, say)
        if not blob or (name == 'untracked' and not proof):
            continue
        target.mkdir(parents=True, exist_ok=True)
        (target / FILES[name]).write_bytes(blob)
        files[FILES[name]] = {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(), 'holds': proof}
    if 'diff' in data and len(data['diff']) != found.diff_bytes:
        say(f'salvage: {found.path}: the diff changed since the plan ({found.diff_bytes} -> {len(data["diff"])} B)')
    return files


def _entry(found: salvageread.Checkout, carried: int) -> dict[str, Any]:
    return {
        'path': found.path, 'origin': found.origin, 'remotes': [list(r) for r in found.remotes],
        'branch': found.branch, 'head': found.head, 'git_common_dir': found.common, 'unpushed': found.unpushed,
        'stash': found.stash, 'changed': found.changed, 'diff_bytes': found.diff_bytes,
        'untracked_carried': [{'path': u.path, 'bytes': u.bytes} for u in found.carried(carried)],
        'untracked_listed': [{'path': u.path, 'bytes': u.bytes} for u in found.listed(carried)],
    }  # fmt: skip


def _applied(
    plan: salvageread.Plan, run: Runner, *, user: str, host: str, path: str, carried: int, out: Path,
    say: Callable[[str], None],
) -> tuple[Path, list[tuple[str, str]]]:  # fmt: skip
    """Bring every readable checkout home under *out*; the manifest written and the refusals."""
    home = out / user
    refused = list(plan.refused)
    entries = []
    for found in plan.checkouts:
        entry = _entry(found, carried)
        try:
            entry['files'] = _bring(run, found, carried, home, say)
        except (_Refused, tarfile.TarError, RuntimeError, OSError, subprocess.SubprocessError) as bad:
            refused.append((found.path, str(bad)))
            entry['refused'] = str(bad)
        landed = ', '.join(f'{name} {sized(f["bytes"])}' for name, f in entry.get('files', {}).items())
        say(f'salvage: {found.path}: {landed or entry.get("refused") or "nothing of its own: nothing written"}')
        entries.append(entry)
    manifest = home if path == '.' else home / path
    manifest.mkdir(parents=True, exist_ok=True)
    record = {
        'format': 1, 'account': user, 'host': host, 'path': path, 'carried_max_bytes': carried,
        'salvaged_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checkouts': entries,
        'refused': [{'path': p, 'why': w} for p, w in refused],
    }  # fmt: skip
    (manifest / MANIFEST).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return manifest / MANIFEST, refused


def salvage(
    user: str, path: str, *, apply: bool, out: Path | None = None, carried: int = CARRIED,
    connect: Callable[..., Runner] = grant_runner, pin: Pin = on_host, say: Callable[[str], None] = emit,
) -> int:  # fmt: skip
    """Plan (and with *apply* bring home under *out*) every checkout's own work under *user*'s ``~/<path>``.

    0 everything readable was planned or salvaged; 2 refused, or some checkout unreadable (named).
    """
    try:
        salvage_path(path)
        host, run = _runner(user, connect, pin)
        plan = salvageread.parse(run(salvageread.plan_command(path), None))
    except subprocess.TimeoutExpired as slow:
        say(f'salvage: {user}: refused -- the plan ran past {slow.timeout:.0f} s; raise --timeout or narrow the path')
        return 2
    except (_Refused, ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'salvage: {user}: refused -- {UNREACHABLE if isinstance(refused, Unreachable) else refused}')
        return 2
    if plan.absent:
        say(f'salvage: {user}: refused -- {plan.path} does not exist on the account; nothing to salvage')
        return 2
    for row in plan_rows(user, plan, carried):
        say(row)
    if not apply:
        say('salvage: dry run -- nothing written; --apply brings every readable checkout home')
        return 2 if plan.refused or any(c.unread() for c in plan.checkouts) else 0
    if out is None:
        say('salvage: refused -- no output directory to write into')
        return 2
    manifest, refused = _applied(plan, run, user=user, host=host, path=path, carried=carried, out=out, say=say)
    say(f'salvage: manifest {manifest}')
    for checkout, why in refused:
        say(f'salvage: {user}: {checkout} REFUSED -- {why}')
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``salvage`` and run it; the output lands under the invoking checkout's dated ``salvage`` kind."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount salvage', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('path', help='a home-relative path of names on the account, or . for the home')
    parser.add_argument('--apply', action='store_true', help='bring it home; default: print the plan, write nothing')
    parser.add_argument('--carried', type=int, default=CARRIED, help=f'largest untracked file carried ({CARRIED} B)')
    parser.add_argument('--timeout', type=float, default=TIMEOUT, help=f'seconds per account read ({TIMEOUT:g})')
    args = parser.parse_args(list(argv or ()))
    out = None
    if args.apply:
        here = gitdirs.checkout_of(Path.cwd())
        if here is None:
            emit('salvage: refused -- run it from a checkout: the salvage lands under its dated output')
            return 2
        out = output_dir(here, KIND)
    return salvage(
        args.account, args.path, apply=args.apply, out=out, carried=args.carried,
        connect=functools.partial(grant_runner, timeout=args.timeout),
        pin=functools.partial(on_host, timeout=args.timeout),
    )  # fmt: skip
