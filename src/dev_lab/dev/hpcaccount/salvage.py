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
import io
import json
import re
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

import lab_commons.launch as _door
from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.log import emit

from dev_lab.dev import gitdirs
from dev_lab.dev.datedlog import output_dir
from dev_lab.dev.harness import child_env
from dev_lab.dev.hpcaccount import salvageread
from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target
from dev_lab.dev.hpcaccount.inventory import sized
from dev_lab.dev.hpcaccount.look import home_path
from dev_lab.dev.hpcaccount.storage import UNREACHABLE, Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = [
    'BRANCH', 'CARRIED', 'FORMAT', 'KIND', 'TIMEOUT', 'WORKTREE', 'Where', 'branch_name', 'main', 'plan_rows',
    'read_record', 'repository_name', 'salvage', 'salvage_path', 'segment',
]  # fmt: skip

#: The largest untracked file carried as data, in bytes. Hand-made work -- sources, notes, tables, configs -- sits
#: far below it; above it sit build products and results (a compiled extension, a mesh, a field dump), which
#: regenerate or belong to ``hpcaccount archive``, and would cost 4/3 of their size on the Runner's stdout.
CARRIED: Final = 1 << 20
#: The dated output kind the salvage RECORD lands under: one ``.json`` per run, never the work itself.
KIND: Final = 'salvage'
#: The record's format; another is refused by :func:`read_record`.
FORMAT: Final = 2
#: The branch a salvaged ref lands on; ``<name>`` is :func:`branch_name`'s, never free text.
BRANCH: Final = 'salvage/{day}-{name}'
#: The ref name of the commit holding a checkout's uncommitted work (no ref git bundles is named so).
WORKTREE: Final = '@worktree'
#: Seconds one account read may take: a checkout's data is one read.
TIMEOUT: Final = 3600.0
_GIT_S: Final = 120


#: The home (``.``) as a segment, and what joins a path's names into one: neither is a ``look.REPO_NAME`` character.
_HOME: Final = '~'
_JOIN: Final = '+'
#: Any character a derived branch name never holds (git refuses most of them in a ref).
_UNSAFE: Final = re.compile(r'[^A-Za-z0-9._+@-]')


class _Refused(Exception):
    """One checkout (or the whole door) is refused; the message names why and the door."""


@dataclass(frozen=True)
class Where:
    """What every salvage branch and commit of one run is derived from."""

    day: str
    account: str
    host: str
    checkout: str
    reason: str


def salvage_path(path: str) -> str:
    """*path* when it is ``.`` (the home) or a home-relative path of names (:func:`~.look.home_path`)."""
    return path if path == '.' else home_path(path)


def segment(path: str) -> str:
    """Home-relative *path* as ONE name: ``.`` is ``~``, ``a/b`` is ``a+b`` (no name can hold either)."""
    return _HOME if path == '.' else path.replace('/', _JOIN)


def repository_name(url: str) -> str:
    """The repository NAME of *url* (https, ``host:path`` or a path): its last segment, ``.git`` stripped, folded."""
    tail = re.split(r'[/:\\]', url.rstrip('/\\'))[-1]
    return tail.removesuffix('.git').casefold()


def branch_name(day: str, account: str, checkout: str, ref: str) -> str:
    """``salvage/<day>-<account>-<checkout>-<ref>``: every part DERIVED, none free text.

    *checkout* is home-relative (``.`` is ``home``), its names joined by ``+`` with a leading dot dropped (a ref
    component cannot begin with one); *ref* loses ``refs/heads/`` (else ``refs/``) and its ``/`` become ``+``. Any
    other character outside ``[A-Za-z0-9._+@-]`` becomes ``-``; git still judges the result (``check-ref-format``).
    """
    if not re.fullmatch(r'[0-9]{8}', day):
        msg = f'salvage: day {day!r} is not yyyymmdd'
        raise ValueError(msg)
    where = 'home' if checkout == '.' else _JOIN.join(part.lstrip('.') for part in PurePosixPath(checkout).parts)
    name = ref.removeprefix('refs/heads/') if ref.startswith('refs/heads/') else ref.removeprefix('refs/')
    name = _JOIN.join(part.lstrip('.') for part in name.split('/'))
    return BRANCH.format(day=day, name=_UNSAFE.sub('-', f'{account}-{where}-{name}'))


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


def _git(repo: Path, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    done = _door.run(
        ['git', '-C', str(repo), *args], input=data, capture_output=True, check=False, timeout=_GIT_S,
        env=None if env is None else child_env(env),
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace').strip()


def _matched(repo: Path, checkout: str, origin: str) -> None:
    """Refuse unless *origin*'s repository name is one of *repo*'s fetch remotes' (the match rule)."""
    code, said = _git(repo, 'remote', '-v')
    if code:
        msg = f'{repo} is not a git repository git can read: {said}'
        raise _Refused(msg)
    remotes = sorted({line.split()[1] for line in said.splitlines() if line.endswith('(fetch)')})
    if not origin:
        msg = f'{checkout} had no remote on the account: no rule names its repo; nothing landed'
        raise _Refused(msg)
    if repository_name(origin) not in {repository_name(url) for url in remotes}:
        msg = (
            f'{checkout} (origin {origin}, repository {repository_name(origin)!r}) is not a checkout of {repo} '
            f'(remotes: {", ".join(remotes) or "none"}): the rule is the repository NAME of the origin; salvage it '
            f'--into the repo with a remote named {repository_name(origin)!r}; nothing landed'
        )
        raise _Refused(msg)


def _checked(repo: Path, branch: str) -> str:
    """*branch* when git accepts it as a branch name; else refused by name."""
    if _git(repo, 'check-ref-format', '--branch', branch)[0]:
        msg = f'{branch} is refused by git as a branch name'
        raise _Refused(msg)
    return branch


def _reached(repo: Path, sha: str) -> str:
    """The first ref of *repo* that reaches commit *sha*; ``''`` when none does (or *repo* lacks it)."""
    code, said = _git(repo, 'for-each-ref', '--contains', sha, '--count=1', '--format=%(refname)')
    return said.splitlines()[0] if code == 0 and said else ''


def _fetched(repo: Path, where: Where, bundle: bytes, say: Callable[[str], None]) -> list[dict[str, str]]:
    """Every ref of *bundle* no ref of *repo* reaches, fetched onto its salvage branch (the file is transient)."""
    with tempfile.TemporaryDirectory(prefix='salvage-') as tmp:
        held = Path(tmp) / 'commits.bundle'
        held.write_bytes(bundle)
        code, said = _git(repo, 'bundle', 'verify', str(held))
        if code:
            msg = (
                f'{repo} lacks commits the bundle of {where.checkout} builds on '
                f'({said.splitlines()[-1] if said else code}): fetch its origin first: '
                f'python -m dev_lab.dev.netverb -- git -C {repo} fetch origin'
            )
            raise _Refused(msg)
        _, said = _git(repo, 'bundle', 'list-heads', str(held))
        landed: list[dict[str, str]] = []
        specs: list[str] = []
        for line in said.splitlines():
            sha, _, ref = line.partition(' ')
            if reached := _reached(repo, sha):
                say(f'salvage: {where.checkout}: {ref} {sha[:10]} skipped -- {reached} already reaches it')
                continue
            branch = _checked(repo, branch_name(where.day, where.account, where.checkout, ref))
            specs.append(f'{ref}:refs/heads/{branch}')
            landed.append({'branch': branch, 'sha': sha, 'from': ref})
        if specs:
            code, said = _git(repo, 'fetch', '--no-tags', '--no-write-fetch-head', str(held), *specs)
            if code:
                msg = f'git fetch of {where.checkout} into {repo} failed: {said}'
                raise _Refused(msg)
    return landed


def _tree_entries(tar: bytes) -> list[tuple[str, str, bytes]]:
    """``(mode, path, blob)`` of every regular file and symlink the untracked tar carries."""
    entries: list[tuple[str, str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(tar)) as held:
        for member in held.getmembers():
            name = member.name.removeprefix('./')
            if member.issym():
                entries.append(('120000', name, member.linkname.encode('utf-8')))
            elif member.isfile() and (blob := held.extractfile(member)) is not None:
                entries.append(('100755' if member.mode & 0o111 else '100644', name, blob.read()))
    return entries


def _worktree_commit(
    repo: Path, where: Where, found: salvageread.Checkout, diff: bytes, untracked: list[tuple[str, str, bytes]]
) -> dict[str, str]:
    """The tracked diff and the untracked files as ONE commit on *found*'s HEAD, on the :data:`WORKTREE` branch."""
    if found.head and _git(repo, 'cat-file', '-e', f'{found.head}^{{commit}}')[0]:
        msg = (
            f'{repo} lacks HEAD {found.head[:10]} of {where.checkout}, which its uncommitted work sits on: fetch its '
            f'origin first: python -m dev_lab.dev.netverb -- git -C {repo} fetch origin'
        )
        raise _Refused(msg)
    branch = _checked(repo, branch_name(where.day, where.account, where.checkout, WORKTREE))
    who = f'{where.account}@{where.host}'
    with tempfile.TemporaryDirectory(prefix='salvage-') as tmp:
        env = {
            'GIT_INDEX_FILE': str(Path(tmp) / 'index'), 'GIT_AUTHOR_NAME': where.account, 'GIT_AUTHOR_EMAIL': who,
            'GIT_COMMITTER_NAME': where.account, 'GIT_COMMITTER_EMAIL': who,
        }  # fmt: skip
        steps: list[tuple[tuple[str, ...], bytes | None]] = [
            (('read-tree', found.head) if found.head else ('read-tree', '--empty'), None)
        ]
        if diff:
            steps.append((('apply', '--cached', '--binary', '-'), diff))
        for step, data in steps:
            code, said = _git(repo, *step, data=data, env=env)
            if code:
                msg = f'git {step[0]} of {where.checkout} failed in {repo}: {said}'
                raise _Refused(msg)
        for mode, path, blob in untracked:
            code, sha = _git(repo, 'hash-object', '-w', '--stdin', data=blob, env=env)
            if code or _git(repo, 'update-index', '--add', '--cacheinfo', f'{mode},{sha},{path}', env=env)[0]:
                msg = f'untracked {path} of {where.checkout} did not land in {repo}: {sha}'
                raise _Refused(msg)
        _, tree = _git(repo, 'write-tree', env=env)
        parents = ('-p', found.head) if found.head else ()
        message = f'salvage: {who}:~/{where.checkout} uncommitted work\n\n{where.reason}\n'
        code, sha = _git(repo, 'commit-tree', tree, *parents, data=message.encode('utf-8'), env=env)
    if code:
        msg = f'the worktree commit of {where.checkout} was not written in {repo}: {sha}'
        raise _Refused(msg)
    code, said = _git(repo, 'update-ref', f'refs/heads/{branch}', sha, '')
    if code:
        msg = f'{branch} was not created in {repo} (an existing branch is never moved): {said}'
        raise _Refused(msg)
    return {'branch': branch, 'sha': sha, 'from': WORKTREE}


def _land(
    run: Runner, found: salvageread.Checkout, carried: int, repo: Path, where: Where, *, say: Callable[[str], None]
) -> list[dict[str, str]]:
    """Read *found*'s work and land it in *repo* as salvage branches: each branch, its sha and what it came from."""
    if why := found.unread():
        raise _Refused(why)
    _matched(repo, found.path, found.origin)
    data, status, refused = salvageread.sections(run(salvageread.data_command(found.path, carried), None))
    if refused:
        raise _Refused('; '.join(refused))
    wanted = {'bundle': bool(found.bundle_bytes), 'diff': bool(found.head), 'untracked': True}
    failed = [f'{n} exited {status.get(n) or "no status"}' for n, w in wanted.items() if w and status.get(n) != '0']
    if failed:
        msg = f'{", ".join(failed)} on the account: re-run; if it repeats, read the checkout with `look ... inventory`'
        raise _Refused(msg)
    if 'diff' in data and len(data['diff']) != found.diff_bytes:
        say(f'salvage: {found.path}: the diff changed since the plan ({found.diff_bytes} -> {len(data["diff"])} B)')
    untracked = _tree_entries(data['untracked']) if data.get('untracked') else []
    if missing := sorted({u.path for u in found.carried(carried)} - {path for _, path, _ in untracked}):
        say(f'salvage: {found.path}: untracked file(s) gone since the plan, not carried: {", ".join(missing)}')
    landed = _fetched(repo, where, data['bundle'], say) if data.get('bundle') else []
    if data.get('diff') or untracked:
        landed.append(_worktree_commit(repo, where, found, data.get('diff', b''), untracked))
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
        except (_Refused, tarfile.TarError, RuntimeError, OSError, subprocess.SubprocessError) as bad:
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
    written = out / f'{time.strftime("%Y%m%dT%H%M%SZ", stamp)}-{where.account}{_JOIN}{segment(path)}.json'
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
    except (_Refused, ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(f'salvage: {user}: refused -- {UNREACHABLE if isinstance(refused, Unreachable) else refused}')
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
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount salvage', description=__doc__.splitlines()[0])
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
