"""THE TASK DOOR: the one writer of the machine's task ledger (user rulings 2026-11-23; rem's task CLI is retired).

``python -m dev_lab.dev.task <verb>`` -- ``help`` prints the verbs (:data:`VERBS`). The ledger is
:func:`dev_lab.dev.taskledger.ledger`, ``<machine home>/repos/tasks``, a git clone; EVERY write commits there (local
only; publishing the clone is ``git -C <ledger> push``). A task is ``<ledger>/<slug>/{TASK.md,JOURNAL.md}`` and its
identity the forge issue labeled ``task:<slug>`` in the clone's origin. The task a checkout works on is its branch's,
``pr/<slug>/<feature>`` (``--task <slug>`` names another). The journal grammar is :mod:`dev_lab.dev.taskjournal`;
opening and closing spend the user's authority (:mod:`dev_lab.dev.taskauthority`). Writing the ledger any other way
is refused by ``LEDGER-WRITES-THROUGH-ITS-DOOR`` (:mod:`dev_lab.dev.ledgerguard`).

THE STABLE PYTHON API (other tools rely on exactly these):

* :func:`ledger` -- the ledger directory (re-exported from :mod:`dev_lab.dev.taskledger`);
* :func:`current` ``(cwd) -> str | None`` -- the slug of the OPEN task *cwd*'s branch names (a tolerant read, so a
  journal holding a union-merge duplicate still resolves and its ``amend`` can run);
* :func:`read` ``(slug) -> Record | None`` -- the open task *slug* (:class:`~dev_lab.dev.taskjournal.Record`), its
  journal read STRICTLY (a duplicated id raises :class:`~dev_lab.dev.taskjournal.RepeatedId` naming its door);
* :func:`append` ``(slug, verb, text, *, item=None) -> str`` -- append ONE journal line and commit; *verb* is one of
  :data:`JOURNAL_VERBS` (``close-item`` takes *item*, the ``O<n>`` number); the line written is returned.

Every refusal is a :class:`TaskRefused` (or a ``LookupError`` from the ledger resolver) naming its cause and door.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.log import emit

from dev_lab.dev import taskauthority, taskjournal, taskpublish
from dev_lab.dev._task_distill import undistilled, undistilled_door
from dev_lab.dev._task_io import (
    Branches,
    Forge,
    ForgeIssues,
    TaskRefused,
    checkout_branches,
    commit,
    git,
    locked,
    today,
)
from dev_lab.dev._task_read import bound, listing, shown
from dev_lab.dev._task_record import (
    ARCHIVE,
    append_line,
    one_line,
    open_record,
    slug_of,
    task_head,
)
from dev_lab.dev.taskjournal import LINE
from dev_lab.dev.taskledger import ledger
from dev_lab.dev.taskmigrate import migrate

__all__ = [
    'JOURNAL_VERBS',
    'VERBS',
    'amend',
    'append',
    'close',
    'ledger',
    'main',
    'open_task',
]

#: ``open <slug> <goal>`` and ``request open|close <slug>`` both need at least two words.
_SLUG_AND_GOAL: Final = 2
#: The append verbs and the tag each writes.
JOURNAL_VERBS: Final = {
    'log': 'progress',
    'decide': 'D',
    'open-item': 'O',
    'close-item': 'closed',
    'handoff': 'handoff',
}
#: Every verb: ``(verb, who, arguments, what it does)``; ``help`` prints it.
VERBS: Final = (
    ('open', 'user', '<slug> "<goal>"', "open a task and its task:<slug> issue (spends the user's /task open grant)"),
    (
        'close',
        'user',
        '<slug> ["<reason>"] [--journal-only D<n>,...]',
        'refused while a pr/<slug>/* head is unmerged; close its issue, archive, commit, prune its merged heads',
    ),
    ('request', 'agent', '<open|close> <slug> ["<goal>"]', 'ask the user: they reply `approve <code>`'),
    ('log', 'branch', '"<progress>"', 'a progress line'),
    ('decide', 'branch', '"<decision>"', 'a decision, numbered D<n>'),
    ('open-item', 'branch', '"<text>"', 'an open item, numbered O<n>'),
    ('close-item', 'branch', 'O<n> ["<how>"]', 'close an open item'),
    ('handoff', 'branch', '"<text>"', 'what the next session picks up'),
    ('amend', 'branch', '--line <n> "<line>" --reason "<why>"', 'correct a wrong line; renumber a repeated id'),
    ('status', 'agent', '[<slug>]', 'the task in <= 2 KB'),
    ('list', 'agent', '', 'every open task: slug, open items, decisions, goal'),
    ('show', 'agent', '[<slug>]', 'TASK.md and the whole journal (an archived task too)'),
    ('migrate', 'owner', '<checkout>... [--dry-run]', 'the one-time move of retired stores; open tasks get issues'),
)


def append(
    slug: str, verb: str, text: str, *, item: int | None = None, date: str | None = None, dry_run: bool = False
) -> str:
    """Append ONE line of *verb* (:data:`JOURNAL_VERBS`) to *slug*'s journal and commit it; the line.

    *dry_run* validates and returns the line it would write, writing nothing.
    """
    if verb not in JOURNAL_VERBS:
        msg = f'{verb!r} is no journal verb; the verbs: {", ".join(JOURNAL_VERBS)}'
        raise TaskRefused(msg)
    root = ledger()
    one_line(text, 'a journal line')
    with locked(root):
        found = open_record(root, slug)
        journal = found.journal
        if verb == 'decide':
            label = journal.next_free('D')
        elif verb == 'open-item':
            label = f'{journal.next_free("O")} open'
        elif verb == 'close-item':
            if item is None or not any(i.n == item for i in found.open_items):
                msg = f'O{item} is not an open item of {slug} (open: {[f"O{i.n}" for i in found.open_items]})'
                raise TaskRefused(msg)
            label = f'O{item} closed'
        else:
            label = JOURNAL_VERBS[verb]
        line = append_line(found, label, text, date, dry_run=dry_run)
        if not dry_run:
            commit(root, f'chore(tasks): {slug} {label.split()[0]}', f'{slug}/JOURNAL.md')
    return line


def amend(
    slug: str, number: int, replacement: str, *, reason: str, date: str | None = None, dry_run: bool = False
) -> str:
    """Rewrite journal line *number* of *slug*: same prefix, or a REPEATED id renumbered to the next free one.

    One audit line records the reason and the old line's digest. A changed mind is a new decision, never an amend.
    """
    if not reason or re.search(r'[\r\n"]', reason):
        msg = 'an amendment names its reason (--reason), one line without "'
        raise TaskRefused(msg)
    one_line(replacement, 'the amended line')
    root = ledger()
    with locked(root):
        found = open_record(root, slug, strict=False)
        file = found.dir / 'JOURNAL.md'
        lines = file.read_text(encoding='utf-8').split('\n')
        if not 1 <= number <= len(lines) or (m := LINE.match(old := lines[number - 1].rstrip('\r'))) is None:
            msg = f'line {number} is not a journal line of {slug}'
            raise TaskRefused(msg)
        prefix = old[: len(old) - len(m[6])]
        repeat = next((rid for rid, at in found.journal.repeats if at == number), None)
        renumbered = repeat and re.sub(r'[DO]\d+', found.journal.next_free(repeat[0]), prefix, count=1)
        keeps = replacement.startswith(prefix) or (renumbered and replacement.startswith(renumbered))
        if not keeps or not LINE.match(replacement) or replacement == old:
            also = f' or renumber it to the next free id ("{renumbered}")' if renumbered else ''
            msg = f'the amendment must keep the prefix byte-identical ("{prefix}"){also} and change the line'
            raise TaskRefused(msg)
        digest = hashlib.sha256(old.encode('utf-8')).hexdigest()[:12]
        audit = f'line {number} amended: {reason} (was sha256:{digest})'
        if dry_run:
            return f'{replacement}\n' + append_line(found, 'progress', audit, date, dry_run=True)
        lines[number - 1] = replacement
        file.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
        line = append_line(found, 'progress', audit, date)
        commit(root, f'chore(tasks): {slug} amend line {number}', f'{slug}/JOURNAL.md')
    return line


def open_task(
    slug: str, goal: str, *, forge: Forge | None = None, date: str | None = None, dry_run: bool = False
) -> Path:
    """Open task *slug*: spend the user's grant, open its issue, write TASK.md and the opened line, commit.

    *dry_run* checks the slug, the goal and the grant, and reaches neither the forge nor the ledger.
    """
    root, day = ledger(), date or today()
    slug_of(slug)
    one_line(goal, 'the task goal')
    if '"' in goal:
        msg = 'the task goal holds no double quote'
        raise TaskRefused(msg)
    with locked(root):
        if (root / slug).exists():
            msg = f'task {slug} exists in the ledger {root.as_posix()}; a closed one is under {ARCHIVE}/'
            raise TaskRefused(msg)
        if dry_run:
            taskauthority.consume(root, 'open', slug, dry_run=True)
            return root / slug
        identity = forge or ForgeIssues(root)  # the forge is reached BEFORE the grant is spent
        authority = taskauthority.consume(root, 'open', slug)
        issue = identity.open(slug, goal)
        (root / slug).mkdir()
        (root / slug / 'TASK.md').write_text(task_head(slug, goal, authority, issue, day), encoding='utf-8')
        found = open_record(root, slug)
        append_line(found, 'opened', f'{goal} (authority {authority})', day)
        commit(root, f'chore(tasks): open {slug}', slug)
    return root / slug


def close(
    slug: str, reason: str = '', *, cwd: Path, journal_only: Sequence[int] = (), forge: Forge | None = None,
    date: str | None = None, branches: Branches | None = None, say: Callable[[str], None] = emit, dry_run: bool = False,
) -> Path:  # fmt: skip
    """Close task *slug*: EVERYTHING is validated before the first write, then archive it, commit, prune its branches.

    An unmerged ``pr/<slug>/*`` head (local or on origin) refuses the close, each named with its doors (user ruling
    2026-11-24); once closed, every merged head is deleted through LOSSLESS-DELETE, each deletion *say*-ed.
    *dry_run* runs every check (the grant included) and returns the archive path, writing and pruning nothing.
    """
    root, day = ledger(), date or today()
    with locked(root):
        found = open_record(root, slug)
        if found.open_items:
            msg = f'{", ".join(f"O{i.n}" for i in found.open_items)} still open: close or carry each item first'
            raise TaskRefused(msg)
        heads = branches or checkout_branches(cwd)
        if unmerged := heads.unmerged(slug):
            from dev_lab.dev.branchdelete import DOOR, TASK_HEAD_DOORS  # noqa: PLC0415

            listed = '\n'.join(f'  {line}' for line in unmerged)
            msg = f'{len(unmerged)} pr/{slug}/* branch(es) not merged:\n{listed}\n{TASK_HEAD_DOORS.format(door=DOOR)}'
            raise TaskRefused(msg)
        if missing := undistilled(cwd, slug, (n for n, _, _ in found.journal.decisions), journal_only):
            raise TaskRefused(undistilled_door(slug, missing))
        kept = (
            f' (kept in the journal only: {", ".join(f"D{n}" for n in sorted(journal_only))})' if journal_only else ''
        )
        line = one_line(f'{reason or "closed by the user"}{kept}', 'the close reason')
        rel = f'{ARCHIVE}/{day}/{slug}'
        if (root / rel).exists():
            msg = f'{(root / rel).as_posix()} exists: the task stays open'
            raise TaskRefused(msg)
        if dry_run:
            taskauthority.consume(root, 'close', slug, dry_run=True)
            return root / rel
        issue = found.fields.get('issue', '')
        identity = (forge or ForgeIssues(root)) if issue else None
        authority = taskauthority.consume(root, 'close', slug)
        if identity is not None:
            identity.close(issue)
        append_line(found, 'closed', f'{line} (authority {authority})', day)
        head = found.dir / 'TASK.md'
        head.write_text(re.sub(r'(?m)^status: .*$', 'status: closed', head.read_text(encoding='utf-8')), 'utf-8')
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        if git(root, 'mv', slug, rel)[0] != 0:
            shutil.move(found.dir, root / rel)
        commit(root, f'chore(tasks): close {slug}', slug, rel)
    for line in heads.prune(slug):
        say(line)
    return root / rel


def _usage(verb: str) -> TaskRefused:
    args = next(a for v, _, a, _ in VERBS if v == verb)
    return TaskRefused(f'usage: python -m dev_lab.dev.task {verb} {args}')


def _help() -> str:
    width = max(len(f'{v} {a}'.strip()) for v, _, a, _ in VERBS)
    rows = [f'  {f"{v} {a}".strip():<{width}}  [{who}] {does}' for v, who, a, does in VERBS]
    head = (
        'python -m dev_lab.dev.task <verb> [--dry-run: a writing verb validates and writes nothing] -- branch: the '
        'task pr/<slug>/<feature> names'
    )
    return '\n'.join([head, *rows])


def _dry(said: str, *, dry: bool) -> str:
    """*said*, marked as a dry run when nothing was written."""
    return f'[task] dry-run, nothing written:\n{said}' if dry else said


def _run(args: argparse.Namespace, cwd: Path) -> str:  # noqa: C901, PLR0911, PLR0912 -- one branch per verb
    verb, words, dry = args.verb, args.words, args.dry_run
    if verb in JOURNAL_VERBS:
        slug = bound(cwd, args.task)
        if verb == 'close-item':
            if not words or not re.fullmatch(r'O?\d+', words[0]):
                raise _usage(verb)
            line = append(slug, verb, ' '.join(words[1:]) or 'done', item=int(words[0].lstrip('O')), dry_run=dry)
            return _dry(line, dry=dry)
        return _dry(append(slug, verb, ' '.join(words), dry_run=dry), dry=dry)
    if verb == 'amend':
        if args.line is None or len(words) != 1 or not args.reason:
            raise _usage(verb)
        return _dry(amend(bound(cwd, args.task), args.line, words[0], reason=args.reason, dry_run=dry), dry=dry)
    if verb == 'open':
        if len(words) < _SLUG_AND_GOAL:
            raise _usage(verb)
        where = open_task(words[0], ' '.join(words[1:]), dry_run=dry)
        if dry:
            return _dry(f'[task] would open {words[0]} at {where.as_posix()} (the grant is live)', dry=dry)
        return f'[task] opened {words[0]} at {where.as_posix()}; work on it on a branch pr/{words[0]}/<feature>'
    if verb == 'close':
        if not words:
            raise _usage(verb)
        only = [int(n.strip().lstrip('D')) for n in (args.journal_only or '').split(',') if n.strip()]
        where = close(words[0], ' '.join(words[1:]), cwd=cwd, journal_only=only, dry_run=dry)
        if dry:
            return _dry(f'[task] would close {words[0]} and archive it to {where.as_posix()}', dry=dry)
        return f'[task] closed {words[0]}; archived to {where.as_posix()}'
    if verb == 'request':
        if len(words) < _SLUG_AND_GOAL or words[0] not in {'open', 'close'}:
            raise _usage(verb)
        if dry:
            return _dry(f'[task] would record a request to {words[0]} {slug_of(words[1])}', dry=dry)
        code = taskauthority.request(ledger(), words[0], slug_of(words[1]), ' '.join(words[2:]))
        return (
            f'[task] ask the user to reply `approve {code}`; then run python -m dev_lab.dev.task {words[0]} {words[1]}'
        )
    if verb == 'list':
        return listing()
    if verb in {'status', 'show'}:
        return shown(verb, slug_of(words[0]) if words else bound(cwd, args.task))
    if verb == 'migrate':
        if not words:
            raise _usage(verb)
        return migrate(*map(Path, words), dry_run=args.dry_run)
    return _help()


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """The CLI: one verb (:data:`VERBS`); a refusal is one stderr block naming its door, exit 1."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.task', add_help=False)
    parser.add_argument('verb', choices=[*(v for v, _, _, _ in VERBS), 'help'])
    parser.add_argument('words', nargs='*')
    parser.add_argument('--task')
    parser.add_argument('--line', type=int)
    parser.add_argument('--reason')
    parser.add_argument('--journal-only')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        said = _run(args, cwd or Path.cwd())
    except (TaskRefused, taskjournal.RepeatedId, taskauthority.AuthorityRefused, LookupError) as refused:
        emit(f'[task] {refused}', err=True)
        _warn_ahead()
        return 1
    if said:
        emit(said)
    _warn_ahead()
    return 0


def _warn_ahead() -> None:
    """Name a ledger clone ahead of its origin (v1 FAM-15); silent when in sync or when no ledger resolves."""
    try:
        root = ledger()
    except LookupError:
        return
    if said := taskpublish.ahead_warning(root):
        emit(said, err=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
