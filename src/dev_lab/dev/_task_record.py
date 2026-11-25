"""A task's RECORD, for :mod:`dev_lab.dev.task`: its slug checked, one journal line written, its status read.

Split out of :mod:`dev_lab.dev.task` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module is the verbs
and the CLI; this one is what they read and write in ONE task folder of the ledger.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev import taskauthority, taskjournal, taskledger
from dev_lab.dev._task_io import TaskRefused, today
from dev_lab.dev.cjk import find_cjk
from dev_lab.dev.taskjournal import LINE
from dev_lab.dev.taskledger import ledger

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.taskjournal import Record

__all__ = [
    'ARCHIVE',
    'STATUS_BYTES',
    'append_line',
    'archived',
    'clip',
    'current',
    'one_line',
    'open_record',
    'read',
    'slug_of',
    'status',
    'task_head',
]

#: The reserved directory closed tasks move under: ``archive/<YYYY-MM-DD>/<slug>/``.
ARCHIVE: Final = 'archive'
SLUG: Final = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
#: The status a verb prints stays under this many bytes.
STATUS_BYTES: Final = 2048


def slug_of(slug: str) -> str:
    if not SLUG.fullmatch(slug or '') or slug == ARCHIVE:
        msg = f'a task slug is kebab-case and never "{ARCHIVE}" (the closed tasks), got {slug!r}'
        raise TaskRefused(msg)
    return slug


def one_line(text: str, what: str) -> str:
    if not text or re.search(r'[\r\n]', text):
        msg = f'{what} is one non-empty line of text'
        raise TaskRefused(msg)
    if found := find_cjk(text):
        msg = f'{what} holds non-English script ({"".join(c for _, _, c in found[:8])}): write it in English'
        raise TaskRefused(msg)
    return text


def open_record(root: Path, slug: str, *, strict: bool = True) -> Record:
    found = taskjournal.record(root / slug_of(slug), strict=strict)
    if found is None or found.status != 'open':
        msg = f'no open task {slug} in the ledger {root.as_posix()}; its journal is final once closed'
        raise TaskRefused(msg)
    return found


def append_line(found: Record, label: str, text: str, date: str | None) -> str:
    line = f'- {date or today()} {label}: {text}'
    if not LINE.match(line):
        msg = f'bad journal line {line!r}'
        raise TaskRefused(msg)
    with (found.dir / 'JOURNAL.md').open('a', encoding='utf-8', newline='\n') as out:
        out.write(line + '\n')
    return line


def archived(slug: str) -> Path | None:
    days = sorted((ledger() / ARCHIVE).glob(f'*/{slug_of(slug)}/TASK.md'), reverse=True)
    return days[0].parent if days else None


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else f'{text[: n - 3]}...'


def status(found: Record) -> str:
    journal = found.journal
    handoffs = [ln for ln in (found.dir / 'JOURNAL.md').read_text(encoding='utf-8').splitlines() if ' handoff: ' in ln]
    head = [f'task {found.slug} ({found.status}, authority {found.authority or "none"}): {clip(found.goal, 300)}']
    if issue := found.fields.get('issue'):
        head.append(f'identity: {issue}')
    if found.authority and (said := taskauthority.problem(ledger(), found.slug, found.authority)):
        head.append(f'authority {said[0]}: {said[1]}')
    items = [f'  O{i.n} {clip(i.text, 100)}' for i in found.open_items]
    tail = [
        f'decisions: {len(journal.decisions)}',
        *(f'  D{n} ({d}) {clip(t, 100)}' for n, d, t in journal.decisions[-3:]),
    ]
    tail += [f'last handoff: {clip(handoffs[-1], 160)}'] if handoffs else []
    tail.append(f'whole record: python -m dev_lab.dev.task show {found.slug}')
    shown = len(items)
    while True:
        more = [f'  +{len(items) - shown} more'] if shown < len(items) else []
        text = '\n'.join([*head, f'open items: {len(items)}', *items[:shown], *more, *tail])
        if shown == 0 or len(text.encode('utf-8')) <= STATUS_BYTES:
            return text
        shown -= 1


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
    found = taskjournal.record(ledger() / slug_of(slug))
    return found if found is not None and found.status == 'open' else None


def task_head(slug: str, goal: str, authority: str, issue: str, date: str) -> str:
    return '\n'.join((
        '---', f'name: {slug}', f'description: "{goal}"', 'kind: task', 'opened_by: user', f'authority: {authority}',
        f'issue: {issue}', f'created: {date}', 'status: open', '---', '', f'# {slug}', '', f'Goal: {goal}', '',
        f'Identity: {issue} -- this directory journals that one issue.', '',
        'Progress, decisions (Dn), open items (On) and handoffs are in JOURNAL.md (append-only).', '',
    ))  # fmt: skip
