"""THE TASK DOOR: the one writer of the machine's task ledger (user rulings 2026-11-23; rem's task CLI is retired).

``python -m dev_lab.dev.task <verb>`` -- ``help`` prints the verbs (:data:`VERBS`). The ledger is
:func:`dev_lab.dev.taskledger.ledger`, ``<machine home>/repos/tasks``, a git clone; EVERY write commits there (local
only; publishing the clone is ``git -C <ledger> push``). A task is ``<ledger>/<slug>/{TASK.md,JOURNAL.md}`` and its
identity the forge issue labelled ``task:<slug>`` in the clone's origin. The task a checkout works on is its branch's,
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
import contextlib
import datetime as dt
import hashlib
import re
import shutil
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final, Protocol

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import taskauthority, taskjournal, taskledger
from dev_lab.dev.cjk import find_cjk
from dev_lab.dev.taskjournal import LINE, Record
from dev_lab.dev.taskledger import ledger

__all__ = [
    'ARCHIVE',
    'JOURNAL_VERBS',
    'VERBS',
    'Forge',
    'TaskRefused',
    'amend',
    'append',
    'close',
    'current',
    'ledger',
    'main',
    'open_task',
    'read',
]

#: The reserved directory closed tasks move under: ``archive/<YYYY-MM-DD>/<slug>/``.
#: ``open <slug> <goal>`` and ``request open|close <slug>`` both need at least two words.
_SLUG_AND_GOAL: Final = 2
ARCHIVE: Final = 'archive'
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
    ('close', 'user', '<slug> ["<reason>"] [--journal-only D<n>,...]', 'close its issue, archive it, commit'),
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
    ('migrate', 'owner', '<checkout>... [--dry-run]', "the one-time move of checkouts' retired stores"),
)
_SLUG: Final = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
_GIT: Final = shutil.which('git') or 'git'
_LOCK_WAIT_S: Final = 30.0
_STATUS_BYTES: Final = 2048
_CITE: Final = 'tasks/{slug}/JOURNAL.md#D'
_DISTILL_HOMES: Final = (('.claude', 'memory'), ('.claude', 'rules'), ('docs-src',))


class TaskRefused(ValueError):
    """A task verb refused: the message names the cause and the door."""


class Forge(Protocol):
    """A task's identity on the forge: one issue labelled ``task:<slug>`` in the ledger's origin."""

    def open(self, slug: str, goal: str) -> str:
        """Open the issue; its URL."""
        ...

    def close(self, url: str) -> None:
        """Close the issue at *url*."""
        ...


class _ForgeIssues:
    """The default :class:`Forge`: dev-lab's forge client for the ledger clone's origin."""

    def __init__(self, root: Path) -> None:
        from dev_lab.dev.forgeclient import client_for  # noqa: PLC0415 -- the network client, only for open/close

        self._client = client_for(root)

    def open(self, slug: str, goal: str) -> str:
        from dev_lab.dev.issuekind import create  # noqa: PLC0415

        body = f"The identity of task `{slug}`: the tasks repo's {slug}/ journals it and links here.\n\nGoal: {goal}"
        return create(self._client, f'task: {slug} -- {goal}', body, 'need', [f'task:{slug}']).url

    def close(self, url: str) -> None:
        if (number := re.search(r'/issues/(\d+)/?$', url)) is not None:
            self._client.issue_close(int(number[1]))


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def _git(root: Path, *args: str) -> tuple[int, str]:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.returncode, (done.stderr or done.stdout).strip()


def _commit(root: Path, message: str, *paths: str) -> None:
    # A path already moved by `git mv` is on neither disk nor index: `add` would refuse it; `commit` records it.
    present = [p for p in paths if (root / p).exists()]
    status, said = _git(root, 'add', '-A', '--', *present) if present else (0, '')
    if status == 0:
        status, said = _git(root, 'commit', '-q', '-m', message, '--', *paths)
    if status != 0:
        msg = (
            f'the ledger write landed but its commit failed ({said.splitlines()[-1] if said else status}).\n'
            f'Door: git -C {root.as_posix()} commit -m "{message}" -- {" ".join(paths)}'
        )
        raise TaskRefused(msg)


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[None]:
    from dev_lab.dev.servelock import held  # noqa: PLC0415

    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        with held(root / '.git' / 'task.lock') as mine:
            if mine:
                yield
                return
        if time.monotonic() > deadline:
            msg = f'the task ledger {root.as_posix()} stayed locked {_LOCK_WAIT_S:g} s by another task verb; retry'
            raise TaskRefused(msg)
        time.sleep(0.02)


def _slug(slug: str) -> str:
    if not _SLUG.fullmatch(slug or '') or slug == ARCHIVE:
        msg = f'a task slug is kebab-case and never "{ARCHIVE}" (the closed tasks), got {slug!r}'
        raise TaskRefused(msg)
    return slug


def _one_line(text: str, what: str) -> str:
    if not text or re.search(r'[\r\n]', text):
        msg = f'{what} is one non-empty line of text'
        raise TaskRefused(msg)
    if found := find_cjk(text):
        msg = f'{what} holds non-English script ({"".join(c for _, _, c in found[:8])}): write it in English'
        raise TaskRefused(msg)
    return text


def current(cwd: Path) -> str | None:
    """The slug of the OPEN task the branch at *cwd* names, else ``None`` (a tolerant read)."""
    slug = taskledger.slug_on(taskledger.branch_of(cwd))
    if slug is None:
        return None
    taskledger.refuse_retired_store(cwd)
    found = taskjournal.record(ledger() / slug, strict=False)
    return slug if found is not None and found.status == 'open' else None


def read(slug: str) -> Record | None:
    """The OPEN task *slug*, its journal read strictly; ``None`` when no such task is open."""
    found = taskjournal.record(ledger() / _slug(slug))
    return found if found is not None and found.status == 'open' else None


def _open_record(root: Path, slug: str, *, strict: bool = True) -> Record:
    found = taskjournal.record(root / _slug(slug), strict=strict)
    if found is None or found.status != 'open':
        msg = f'no open task {slug} in the ledger {root.as_posix()}; its journal is final once closed'
        raise TaskRefused(msg)
    return found


def _append_line(found: Record, label: str, text: str, date: str | None) -> str:
    line = f'- {date or _today()} {label}: {text}'
    if not LINE.match(line):
        msg = f'bad journal line {line!r}'
        raise TaskRefused(msg)
    with (found.dir / 'JOURNAL.md').open('a', encoding='utf-8', newline='\n') as out:
        out.write(line + '\n')
    return line


def append(slug: str, verb: str, text: str, *, item: int | None = None, date: str | None = None) -> str:
    """Append ONE line of *verb* (:data:`JOURNAL_VERBS`) to *slug*'s journal and commit it; the line."""
    if verb not in JOURNAL_VERBS:
        msg = f'{verb!r} is no journal verb; the verbs: {", ".join(JOURNAL_VERBS)}'
        raise TaskRefused(msg)
    root = ledger()
    _one_line(text, 'a journal line')
    with _locked(root):
        found = _open_record(root, slug)
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
        line = _append_line(found, label, text, date)
        _commit(root, f'chore(tasks): {slug} {label.split()[0]}', f'{slug}/JOURNAL.md')
    return line


def amend(slug: str, number: int, replacement: str, *, reason: str, date: str | None = None) -> str:
    """Rewrite journal line *number* of *slug*: same prefix, or a REPEATED id renumbered to the next free one.

    One audit line records the reason and the old line's digest. A changed mind is a new decision, never an amend.
    """
    if not reason or re.search(r'[\r\n"]', reason):
        msg = 'an amendment names its reason (--reason), one line without "'
        raise TaskRefused(msg)
    _one_line(replacement, 'the amended line')
    root = ledger()
    with _locked(root):
        found = _open_record(root, slug, strict=False)
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
        lines[number - 1] = replacement
        file.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
        digest = hashlib.sha256(old.encode('utf-8')).hexdigest()[:12]
        line = _append_line(found, 'progress', f'line {number} amended: {reason} (was sha256:{digest})', date)
        _commit(root, f'chore(tasks): {slug} amend line {number}', f'{slug}/JOURNAL.md')
    return line


def _task_head(slug: str, goal: str, authority: str, issue: str, date: str) -> str:
    return '\n'.join((
        '---', f'name: {slug}', f'description: "{goal}"', 'kind: task', 'opened_by: user', f'authority: {authority}',
        f'issue: {issue}', f'created: {date}', 'status: open', '---', '', f'# {slug}', '', f'Goal: {goal}', '',
        f'Identity: {issue} -- this directory journals that one issue.', '',
        'Progress, decisions (Dn), open items (On) and handoffs are in JOURNAL.md (append-only).', '',
    ))  # fmt: skip


def open_task(slug: str, goal: str, *, forge: Forge | None = None, date: str | None = None) -> Path:
    """Open task *slug*: spend the user's grant, open its issue, write TASK.md and the opened line, commit."""
    root, day = ledger(), date or _today()
    _slug(slug)
    _one_line(goal, 'the task goal')
    if '"' in goal:
        msg = 'the task goal holds no double quote'
        raise TaskRefused(msg)
    with _locked(root):
        if (root / slug).exists():
            msg = f'task {slug} exists in the ledger {root.as_posix()}; a closed one is under {ARCHIVE}/'
            raise TaskRefused(msg)
        identity = forge or _ForgeIssues(root)  # the forge is reached BEFORE the grant is spent
        authority = taskauthority.consume(root, 'open', slug)
        issue = identity.open(slug, goal)
        (root / slug).mkdir()
        (root / slug / 'TASK.md').write_text(_task_head(slug, goal, authority, issue, day), encoding='utf-8')
        found = _open_record(root, slug)
        _append_line(found, 'opened', f'{goal} (authority {authority})', day)
        _commit(root, f'chore(tasks): open {slug}', slug)
    return root / slug


def _cited(cwd: Path, slug: str) -> set[int]:
    tops = [p for p in (Path(cwd).resolve(), *Path(cwd).resolve().parents) if (p / '.git').exists()][:1]
    cite = re.compile(re.escape(_CITE.format(slug=slug)) + r'(\d+)\b')
    found: set[int] = set()
    for top in tops:
        for home in _DISTILL_HOMES:
            for doc in top.joinpath(*home).rglob('*.md'):
                with contextlib.suppress(OSError):
                    found.update(int(n) for n in cite.findall(doc.read_text(encoding='utf-8').replace('\\', '/')))
    return found


def close(
    slug: str, reason: str = '', *, cwd: Path, journal_only: Sequence[int] = (), forge: Forge | None = None,
    date: str | None = None,
) -> Path:  # fmt: skip
    """Close task *slug*: EVERYTHING is validated before the first write, then archive it and commit."""
    root, day = ledger(), date or _today()
    with _locked(root):
        found = _open_record(root, slug)
        if found.open_items:
            msg = f'{", ".join(f"O{i.n}" for i in found.open_items)} still open: close or carry each item first'
            raise TaskRefused(msg)
        missing = [n for n, _, _ in found.journal.decisions if n not in _cited(cwd, slug) and n not in journal_only]
        if missing:
            msg = (
                f'{", ".join(f"D{n}" for n in missing)} not distilled.\nDoor: cite {_CITE.format(slug=slug)}<n> from a '
                'memory entry, a rule or a doc of this checkout, or keep it in the journal only (--journal-only D<n>)'
            )
            raise TaskRefused(msg)
        kept = (
            f' (kept in the journal only: {", ".join(f"D{n}" for n in sorted(journal_only))})' if journal_only else ''
        )
        line = _one_line(f'{reason or "closed by the user"}{kept}', 'the close reason')
        rel = f'{ARCHIVE}/{day}/{slug}'
        if (root / rel).exists():
            msg = f'{(root / rel).as_posix()} exists: the task stays open'
            raise TaskRefused(msg)
        issue = found.fields.get('issue', '')
        identity = (forge or _ForgeIssues(root)) if issue else None
        authority = taskauthority.consume(root, 'close', slug)
        if identity is not None:
            identity.close(issue)
        _append_line(found, 'closed', f'{line} (authority {authority})', day)
        head = found.dir / 'TASK.md'
        head.write_text(re.sub(r'(?m)^status: .*$', 'status: closed', head.read_text(encoding='utf-8')), 'utf-8')
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        if _git(root, 'mv', slug, rel)[0] != 0:
            shutil.move(found.dir, root / rel)
        _commit(root, f'chore(tasks): close {slug}', slug, rel)
    return root / rel


def _archived(slug: str) -> Path | None:
    days = sorted((ledger() / ARCHIVE).glob(f'*/{_slug(slug)}/TASK.md'), reverse=True)
    return days[0].parent if days else None


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else f'{text[: n - 3]}...'


def _status(found: Record) -> str:
    journal = found.journal
    handoffs = [ln for ln in (found.dir / 'JOURNAL.md').read_text(encoding='utf-8').splitlines() if ' handoff: ' in ln]
    head = [f'task {found.slug} ({found.status}, authority {found.authority or "none"}): {_clip(found.goal, 300)}']
    if issue := found.fields.get('issue'):
        head.append(f'identity: {issue}')
    if found.authority and (said := taskauthority.problem(ledger(), found.slug, found.authority)):
        head.append(f'authority {said[0]}: {said[1]}')
    items = [f'  O{i.n} {_clip(i.text, 100)}' for i in found.open_items]
    tail = [
        f'decisions: {len(journal.decisions)}',
        *(f'  D{n} ({d}) {_clip(t, 100)}' for n, d, t in journal.decisions[-3:]),
    ]
    tail += [f'last handoff: {_clip(handoffs[-1], 160)}'] if handoffs else []
    tail.append(f'whole record: python -m dev_lab.dev.task show {found.slug}')
    shown = len(items)
    while True:
        more = [f'  +{len(items) - shown} more'] if shown < len(items) else []
        text = '\n'.join([*head, f'open items: {len(items)}', *items[:shown], *more, *tail])
        if shown == 0 or len(text.encode('utf-8')) <= _STATUS_BYTES:
            return text
        shown -= 1


def _bound(cwd: Path, named: str | None) -> str:
    if named:
        return _slug(named)
    if (slug := current(cwd)) is not None:
        return slug
    branch = taskledger.branch_of(cwd)
    msg = (
        f'the branch {branch or "(detached HEAD)"} names no open task.\nDoor: {taskledger.DOOR} (or pass --task <slug>)'
    )
    raise TaskRefused(msg)


def _usage(verb: str) -> TaskRefused:
    args = next(a for v, _, a, _ in VERBS if v == verb)
    return TaskRefused(f'usage: python -m dev_lab.dev.task {verb} {args}')


def _help() -> str:
    width = max(len(f'{v} {a}'.strip()) for v, _, a, _ in VERBS)
    rows = [f'  {f"{v} {a}".strip():<{width}}  [{who}] {does}' for v, who, a, does in VERBS]
    return '\n'.join(['python -m dev_lab.dev.task <verb> -- branch: the task pr/<slug>/<feature> names', *rows])


def _run(args: argparse.Namespace, cwd: Path) -> str:  # noqa: C901, PLR0911, PLR0912 -- one branch per verb
    verb, words = args.verb, args.words
    if verb in JOURNAL_VERBS:
        slug = _bound(cwd, args.task)
        if verb == 'close-item':
            if not words or not re.fullmatch(r'O?\d+', words[0]):
                raise _usage(verb)
            return append(slug, verb, ' '.join(words[1:]) or 'done', item=int(words[0].lstrip('O')))
        return append(slug, verb, ' '.join(words))
    if verb == 'amend':
        if args.line is None or len(words) != 1 or not args.reason:
            raise _usage(verb)
        return amend(_bound(cwd, args.task), args.line, words[0], reason=args.reason)
    if verb == 'open':
        if len(words) < _SLUG_AND_GOAL:
            raise _usage(verb)
        where = open_task(words[0], ' '.join(words[1:]))
        return f'[task] opened {words[0]} at {where.as_posix()}; work on it on a branch pr/{words[0]}/<feature>'
    if verb == 'close':
        if not words:
            raise _usage(verb)
        only = [int(n.strip().lstrip('D')) for n in (args.journal_only or '').split(',') if n.strip()]
        where = close(words[0], ' '.join(words[1:]), cwd=cwd, journal_only=only)
        return f'[task] closed {words[0]}; archived to {where.as_posix()}'
    if verb == 'request':
        if len(words) < _SLUG_AND_GOAL or words[0] not in {'open', 'close'}:
            raise _usage(verb)
        code = taskauthority.request(ledger(), words[0], _slug(words[1]), ' '.join(words[2:]))
        return (
            f'[task] ask the user to reply `approve {code}`; then run python -m dev_lab.dev.task {words[0]} {words[1]}'
        )
    if verb == 'list':
        root = ledger()
        found = [taskjournal.record(d, strict=False) for d in sorted(root.iterdir()) if d.is_dir()
                 and not d.name.startswith('.') and d.name != ARCHIVE]  # fmt: skip
        return '\n'.join(
            f'{r.slug}\t{r.status}\t{len(r.open_items)} open\t{len(r.journal.decisions)} decisions\t{r.goal}'
            for r in found
            if r is not None
        )
    if verb in {'status', 'show'}:
        slug = _slug(words[0]) if words else _bound(cwd, args.task)
        folder = ledger() / slug if (ledger() / slug / 'TASK.md').is_file() else _archived(slug)
        if folder is None:
            msg = f'no task {slug} in the ledger or its archive.\nDoor: python -m dev_lab.dev.task list'
            raise TaskRefused(msg)
        if verb == 'show':
            journal = folder / 'JOURNAL.md'
            return (
                (folder / 'TASK.md').read_text(encoding='utf-8')
                + '\n'
                + (journal.read_text(encoding='utf-8') if journal.is_file() else '')
            )
        return _status(taskjournal.record(folder))  # type: ignore[arg-type]
    if verb == 'migrate':
        from dev_lab.dev.taskmigrate import migrate  # noqa: PLC0415

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
        return 1
    if said:
        emit(said)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
