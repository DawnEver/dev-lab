"""A TASK'S RECORD, READ: ``TASK.md`` frontmatter and the append-only ``JOURNAL.md`` grammar (user ruling 2026-11-23).

Pure reading, no writes: :mod:`dev_lab.dev.task` is the one writer. A journal line is
``- <YYYY-MM-DD> <tag>: <text>``, its tag one of ``opened``, ``progress``, ``handoff``, ``closed``, ``D<n>`` (a
decision) or ``O<n> open`` / ``O<n> closed`` (an item). Only ``D<n>`` and ``O<n> open`` MINT an id.

THE LEDGER IS MERGED BY UNION (``.gitattributes``: ``JOURNAL.md merge=union``), so two machines' journals can mint
one id twice. :func:`scan` reads TOLERANTLY -- every repeat recorded with its 1-based line and the next free id of
its kind, the FIRST ``O<n> open`` staying the item -- and is what current-task resolution and the renumbering amend
read, so the remedy can run. :func:`parse` is STRICT: a repeat is refused by :class:`RepeatedId`, naming the id, the
line and its door (:func:`amend_door`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

__all__ = [
    'LINE',
    'Item',
    'Journal',
    'Record',
    'RepeatedId',
    'amend_door',
    'frontmatter',
    'parse',
    'record',
    'scan',
]

#: THE grammar of one journal line.
LINE: Final = re.compile(r'^- (\d{4}-\d{2}-\d{2}) (opened|progress|handoff|closed|D(\d+)|O(\d+) (open|closed)): (.*)$')


@dataclass(frozen=True, slots=True)
class Item:
    """One open item ``O<n>``: its number, the date and text of its first ``open`` line, and whether it is open."""

    n: int
    date: str
    text: str
    open: bool


@dataclass(frozen=True, slots=True)
class Journal:
    """A journal read: decisions ``(n, date, text)``, items, each repeated mint ``(id, line)`` and the next free ids."""

    decisions: tuple[tuple[int, str, str], ...]
    items: tuple[Item, ...]
    repeats: tuple[tuple[str, int], ...]
    next_d: int
    next_o: int

    def next_free(self, kind: str) -> str:
        """The next free id of *kind* (``D`` or ``O``)."""
        return f'{kind}{self.next_d if kind == "D" else self.next_o}'


class RepeatedId(ValueError):
    """A journal mints one id twice (a union merge): any citation of it is ambiguous."""


def scan(text: str) -> Journal:
    """Every journal line of *text*, read WITHOUT judging: repeats are recorded, never raised."""
    decisions: list[tuple[int, str, str]] = []
    items: dict[int, dict[str, object]] = {}
    seen: set[str] = set()
    repeats: list[tuple[str, int]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if (m := LINE.match(line)) is None:
            continue
        minted = f'D{m[3]}' if m[3] else f'O{m[4]}' if m[5] == 'open' else None
        if minted is not None:
            if minted in seen:
                repeats.append((minted, number))
            seen.add(minted)
        if m[3]:
            decisions.append((int(m[3]), m[1], m[6]))
        elif m[4]:
            n = int(m[4])
            if m[5] == 'open':
                items.setdefault(n, {'date': m[1], 'text': m[6], 'open': True})
            elif n in items:
                items[n]['open'] = False
    return Journal(
        decisions=tuple(decisions),
        items=tuple(Item(n, str(i['date']), str(i['text']), bool(i['open'])) for n, i in items.items()),
        repeats=tuple(repeats),
        next_d=max((d[0] for d in decisions), default=0) + 1,
        next_o=max(items, default=0) + 1,
    )


def amend_door(line: int, free: str, repeated: str) -> str:
    """The one remedy for a repeated id at *line*: renumber it to the next free id *free*."""
    return (
        f'python -m dev_lab.dev.task amend --line {line} "<line {line} with {repeated} renumbered to {free}>" '
        f'--reason "duplicate {repeated} after a union merge"'
    )


def parse(text: str) -> Journal:
    """:func:`scan`, STRICT: the first repeated id is refused naming it, its line and :func:`amend_door`."""
    journal = scan(text)
    if journal.repeats:
        repeated, line = journal.repeats[0]
        free = journal.next_free(repeated[0])
        msg = (
            f"the journal mints {repeated} again at line {line} (a union merge of two machines' journals), so a "
            f'citation of {repeated} is ambiguous.\nDoor: {amend_door(line, free, repeated)}'
        )
        raise RepeatedId(msg)
    return journal


def frontmatter(text: str) -> dict[str, str]:
    """The ``key: value`` fields between the first two ``---`` lines of *text*; ``{}`` when there is none."""
    parts = text.split('---', 2)
    if len(parts) < 3:  # noqa: PLR2004 -- before, inside and after the frontmatter
        return {}
    return {k.strip(): v.strip() for k, _, v in (ln.partition(':') for ln in parts[1].splitlines()) if _}


@dataclass(frozen=True, slots=True)
class Record:
    """A task as its two files say it: TASK.md's fields and the journal read."""

    slug: str
    dir: Path
    fields: dict[str, str] = field(default_factory=dict)
    journal: Journal = field(default_factory=lambda: scan(''))

    @property
    def status(self) -> str:
        """``open`` or ``closed`` (``open`` when unstated)."""
        return self.fields.get('status') or 'open'

    @property
    def authority(self) -> str:
        """The authority id the user's open minted, ``''`` when none."""
        return self.fields.get('authority', '')

    @property
    def goal(self) -> str:
        """The one-line goal."""
        return self.fields.get('description', '').strip('"')

    @property
    def open_items(self) -> tuple[Item, ...]:
        """The items still open."""
        return tuple(i for i in self.journal.items if i.open)


def record(folder: Path, *, strict: bool = True) -> Record | None:
    """The task at *folder* (``TASK.md`` + ``JOURNAL.md``), or ``None`` with no TASK.md; *strict* refuses repeats."""
    try:
        head = (folder / 'TASK.md').read_text(encoding='utf-8')
    except OSError:
        return None
    try:
        text = (folder / 'JOURNAL.md').read_text(encoding='utf-8')
    except OSError:
        text = ''
    try:
        journal = parse(text) if strict else scan(text)
    except RepeatedId as repeated:
        msg = f'task {folder.name}: {repeated}'
        raise RepeatedId(msg) from None
    return Record(folder.name, folder, frontmatter(head), journal)
