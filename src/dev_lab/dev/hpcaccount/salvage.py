"""``python -m dev_lab.dev.hpcaccount salvage --account <user> <path> [--into <repo> --reason <why> --apply]``.

An account's own git work, home AS GIT OBJECTS. User ruling 2026-11-25: an account is cleaned completely. Before its
contents may go, every commit on no remote and every uncommitted change in its checkouts must be on the workstation,
and no door brought them: ``look ... inventory`` only REPORTS what is not pushed, ``archive`` tars a path to a run
store (none was declared), and raw ssh is forbidden. Measured that day: one research account held eleven checkouts
NOT PUSHED in one home directory alone (40 commits in one, dirty files and untracked notes in others).

User ruling A, 2026-11-27 (dev-lab #1039): salvaged work is never a file under ``output/`` (OUTPUT-HOLDS-NO-CODE,
NO-BACKUP-COPIES). It becomes branches of a local repo, which the CALLER pushes through the network door; the dated
``salvage`` kind keeps only a JSON record of what landed where, and why.

This door finds every checkout under ``~/<path>`` (``.`` is the home) -- nested ones and worktrees included, by the
inventory's own discovery -- and for each reads, through the grant's own Runner pinned to the declared login host
(:mod:`~dev_lab.dev.hpcaccount.salvageread`, nothing written on the account), the commits no remote-tracking ref
reaches (:data:`~dev_lab.dev.hpcaccount.inventory.UNPUSHED`) as a bundle, ``git diff HEAD --binary``, and the
untracked, non-ignored files of at most :data:`CARRIED` bytes (a larger one is listed by name and size, never
carried; ``--carried`` moves the limit). With ``--apply`` they land in ``--into <repo>``, touching no working tree,
no index and no other ref:

* THE MATCH RULE: the checkout belongs in *repo* when the REPOSITORY NAME of its ``origin`` -- the url's last path
  segment, ``.git`` stripped, case folded -- is the name of one of *repo*'s fetch remotes (one repository is served
  by several forges under different owners). A checkout with no origin, or another repository's, is refused by name.
* Every bundle ref is fetched (never forced) onto ``salvage/<yyyymmdd>-<name>`` (:func:`branch_name`): the name is
  DERIVED from the account, the checkout's home-relative path and the ref, never typed. A ref whose commit a ref of
  *repo* already reaches is skipped, naming that ref.
* The tracked diff and the carried untracked files become ONE commit on the checkout's HEAD (through a private
  index), on the branch of ref :data:`WORKTREE`.

The record -- per checkout its origin, remotes, branch, HEAD and each salvage branch with its sha -- lands as one
``.json`` under the invoking checkout's dated ``salvage`` output (:func:`read_record` reads it back). Without
``--apply`` the plan is printed and nothing is written. A checkout git cannot read is refused by name with git's own
words, the others are still salvaged, and the door exits 2. Nothing here pushes: the door prints the
``netverb -- git push`` line that takes the branches to the forge.
"""

from __future__ import annotations

import argparse
import functools
import json
import subprocess
import tarfile
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, cast

from lab_commons.hpc.cluster import Runner
from lab_commons.log import emit

from dev_lab.dev import gitdirs
from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.hpcaccount import salvageread
from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target
from dev_lab.dev.hpcaccount.inventory import sized
from dev_lab.dev.hpcaccount.look import home_path
from dev_lab.dev.hpcaccount.salvagerepo import JOIN, Refused, Where, fetched, matched, tree_entries, worktree_commit
from dev_lab.dev.hpcaccount.storage import Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = [
    'CARRIED', 'FORMAT', 'KIND', 'TIMEOUT', 'main', 'plan_rows', 'read_record', 'salvage', 'salvage_path', 'segment',
]  # fmt: skip

#: The largest untracked file carried as data, in bytes. Hand-made work -- sources, notes, tables, configs -- sits
#: far below it; above it sit build products and results (a compiled extension, a mesh, a field dump), which
#: regenerate or belong to ``hpcaccount archive``, and would cost 4/3 of their size on the Runner's stdout.
CARRIED: Final = 1 << 20
#: The dated output kind the salvage RECORD lands under: one ``.json`` per run, never the work itself.
KIND: Final = 'salvage'
#: The record's format; another is refused by :func:`read_record`.
FORMAT: Final = 2
#: Seconds one account read may take: a checkout's data is one read.
TIMEOUT: Final = 3600.0

#: The home (``.``) as a segment: not a ``look.REPO_NAME`` character.
_HOME: Final = '~'


def salvage_path(path: str) -> str:
    """*path* when it is ``.`` (the home) or a home-relative path of names (:func:`~.look.home_path`)."""
    return path if path == '.' else home_path(path)


def segment(path: str) -> str:
    """Home-relative *path* as ONE name: ``.`` is ``~``, ``a/b`` is ``a+b`` (no name can hold either)."""
    return _HOME if path == '.' else path.replace('/', JOIN)


def read_record(path: Path) -> dict[str, Any]:
    """The salvage record at *path*; one of another format is refused by name (a format migrates once)."""
    record: object = json.loads(path.read_text(encoding='utf-8'))
    said = cast('dict[str, Any]', record).get('format') if isinstance(record, dict) else type(record).__name__
    if not isinstance(record, dict) or said != FORMAT:
        msg = (
            f'{path} is not a salvage record of format {FORMAT} (it says {said!r}): a record before dev-lab #1039 '
            f'listed files under output/; re-run hpcaccount salvage --apply --into <repo> to land the work as branches'
        )
        raise ValueError(msg)
    return cast('dict[str, Any]', record)


def _runner(user: str, connect: Callable[..., Runner], pin: Pin) -> tuple[str, Runner]:
    grant = next(g for g in reached_machine([user]).grants if g.user == user)
    target = declared_target(grant, connect(grant))
    if isinstance(target, str):
        raise Refused(target)
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


def _land(
    run: Runner, found: salvageread.Checkout, carried: int, repo: Path, where: Where, *, say: Callable[[str], None]
) -> list[dict[str, str]]:
    """Read *found*'s work and land it in *repo* as salvage branches: each branch, its sha and what it came from."""
    if why := found.unread():
        raise Refused(why)
    matched(repo, found.path, found.origin)
    data, status, refused = salvageread.sections(run(salvageread.data_command(found.path, carried), None))
    if refused:
        raise Refused('; '.join(refused))
    wanted = {'bundle': bool(found.bundle_bytes), 'diff': bool(found.head), 'untracked': True}
    failed = [f'{n} exited {status.get(n) or "no status"}' for n, w in wanted.items() if w and status.get(n) != '0']
    if failed:
        msg = f'{", ".join(failed)} on the account: re-run; if it repeats, read the checkout with `look ... inventory`'
        raise Refused(msg)
    if 'diff' in data and len(data['diff']) != found.diff_bytes:
        say(f'salvage: {found.path}: the diff changed since the plan ({found.diff_bytes} -> {len(data["diff"])} B)')
    untracked = tree_entries(data['untracked']) if data.get('untracked') else []
    if missing := sorted({u.path for u in found.carried(carried)} - {path for _, path, _ in untracked}):
        say(f'salvage: {found.path}: untracked file(s) gone since the plan, not carried: {", ".join(missing)}')
    landed = fetched(repo, where, data['bundle'], say) if data.get('bundle') else []
    if data.get('diff') or untracked:
        landed.append(worktree_commit(repo, where, found, data.get('diff', b''), untracked))
    return landed


def _entry(found: salvageread.Checkout, carried: int) -> dict[str, Any]:
    return {
        'path': found.path, 'origin': found.origin, 'remotes': [list(r) for r in found.remotes],
        'branch': found.branch, 'head': found.head, 'git_common_dir': found.common, 'unpushed': found.unpushed,
        'stash': found.stash, 'changed': found.changed, 'diff_bytes': found.diff_bytes,
        'untracked_carried': [{'path': u.path, 'bytes': u.bytes} for u in found.carried(carried)],
        'untracked_listed': [{'path': u.path, 'bytes': u.bytes} for u in found.listed(carried)],
    }  # fmt: skip


def _applied(
    plan: salvageread.Plan, run: Runner, *, where: Where, path: str, carried: int, repo: Path, out: Path,
    say: Callable[[str], None],
) -> tuple[Path, list[str], list[tuple[str, str]]]:  # fmt: skip
    """Land every readable checkout in *repo*; the record written under *out*, the branches and the refusals."""
    refused = list(plan.refused)
    entries: list[dict[str, Any]] = []
    branches: list[str] = []
    for found in plan.checkouts:
        entry = _entry(found, carried)
        try:
            entry['branches'] = _land(run, found, carried, repo, replace(where, checkout=found.path), say=say)
        except (Refused, tarfile.TarError, RuntimeError, OSError, subprocess.SubprocessError) as bad:
            refused.append((found.path, str(bad)))
            entry['refused'] = str(bad)
        branches.extend(b['branch'] for b in entry.get('branches', []))
        landed = ', '.join(f'{b["branch"]} {b["sha"][:10]}' for b in entry.get('branches', []))
        say(f'salvage: {found.path}: {landed or entry.get("refused") or "nothing of its own: nothing landed"}')
        entries.append(entry)
    stamp = time.gmtime()
    record = {
        'format': FORMAT, 'account': where.account, 'host': where.host, 'path': path, 'repo': str(repo),
        'reason': where.reason, 'carried_max_bytes': carried,
        'salvaged_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', stamp), 'checkouts': entries,
        'refused': [{'path': p, 'why': w} for p, w in refused],
    }  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    written = out / f'{time.strftime("%Y%m%dT%H%M%SZ", stamp)}-{where.account}{JOIN}{segment(path)}.json'
    written.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return written, branches, refused


def salvage(
    user: str, path: str, *, apply: bool, repo: Path | None = None, reason: str = '', out: Path | None = None,
    carried: int = CARRIED, day: str | None = None, connect: Callable[..., Runner] = grant_runner,
    pin: Pin = on_host, say: Callable[[str], None] = emit,
) -> int:  # fmt: skip
    """Plan (and with *apply* land in *repo*, recorded under *out*) every checkout's own work under ``~/<path>``.

    0 everything readable was planned or salvaged; 2 refused, or some checkout unreadable (named).
    """
    try:
        salvage_path(path)
        host, run = _runner(user, connect, pin)
        plan = salvageread.parse(run(salvageread.plan_command(path), None))
    except subprocess.TimeoutExpired as slow:
        say(f'salvage: {user}: refused -- the plan ran past {slow.timeout:.0f} s; raise --timeout or narrow the path')
        return 2
    except (Refused, ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'salvage: {user}: refused -- {refused}')
        return 2
    if plan.absent:
        say(f'salvage: {user}: refused -- {plan.path} does not exist on the account; nothing to salvage')
        return 2
    for row in plan_rows(user, plan, carried):
        say(row)
    if not apply:
        say('salvage: dry run -- nothing written; --apply --into <repo> --reason <why> lands it as salvage branches')
        return 2 if plan.refused or any(c.unread() for c in plan.checkouts) else 0
    if out is None or repo is None or not reason.strip():
        say(
            'salvage: refused -- --apply needs --into <repo> (where the branches land), --reason <why> (recorded) '
            'and a checkout to record under; nothing landed'
        )
        return 2
    where = Where(day or time.strftime('%Y%m%d', time.gmtime()), user, host, '', reason.strip())
    record, branches, refused = _applied(
        plan, run, where=where, path=path, carried=carried, repo=repo, out=out, say=say
    )  # fmt: skip
    say(f'salvage: record {record}')
    if branches:
        say(f'salvage: push them: python -m dev_lab.dev.netverb -- git -C {repo} push origin {" ".join(branches)}')
    for checkout, why in refused:
        say(f'salvage: {user}: {checkout} REFUSED -- {why}')
    return 2 if refused else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``salvage`` and run it; the record lands under the invoking checkout's dated ``salvage`` kind."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount salvage', description=(__doc__ or '').splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('path', help='a home-relative path of names on the account, or . for the home')
    parser.add_argument('--into', type=Path, help='the local repo the salvage branches land in (its origin matched)')
    parser.add_argument('--reason', default='', help='why it is salvaged: recorded, and in the worktree commit')
    parser.add_argument('--apply', action='store_true', help='land it; default: print the plan, write nothing')
    parser.add_argument('--carried', type=int, default=CARRIED, help=f'largest untracked file carried ({CARRIED} B)')
    parser.add_argument('--timeout', type=float, default=TIMEOUT, help=f'seconds per account read ({TIMEOUT:g})')
    args = parser.parse_args(list(argv or ()))
    out = None
    if args.apply:
        here = gitdirs.checkout_of(Path.cwd())
        if here is None:
            emit('salvage: refused -- run it from a checkout: the salvage record lands under its dated output')
            return 2
        out = output_dir(here, KIND)
    return salvage(
        args.account, args.path, apply=args.apply, repo=args.into, reason=args.reason, out=out, carried=args.carried,
        connect=functools.partial(grant_runner, timeout=args.timeout),
        pin=functools.partial(on_host, timeout=args.timeout),
    )  # fmt: skip
