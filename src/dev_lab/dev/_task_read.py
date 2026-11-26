"""THE TASK LEDGER READ: which task a checkout is bound to, and the ``list``, ``status`` and ``show`` answers.

Split out of :mod:`dev_lab.dev.task` (2026-11-26, MODULE-SIZE-ALARM): that module writes the ledger; this one only
reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import taskjournal, taskledger
from dev_lab.dev._task_io import TaskRefused
from dev_lab.dev._task_record import ARCHIVE, archived, current, slug_of, status
from dev_lab.dev.taskledger import ledger

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['bound', 'listing', 'shown']


def bound(cwd: Path, named: str | None) -> str:
    """The task *named* (``--task``), else the one *cwd*'s branch names; refused naming the door when neither."""
    if named:
        return slug_of(named)
    if (slug := current(cwd)) is not None:
        return slug
    branch = taskledger.branch_of(cwd)
    msg = (
        f'the branch {branch or "(detached HEAD)"} names no open task.\nDoor: {taskledger.DOOR} (or pass --task <slug>)'
    )
    raise TaskRefused(msg)


def listing() -> str:
    """One line per task in the ledger: slug, status, open items, decisions, goal."""
    root = ledger()
    found = [taskjournal.record(d, strict=False) for d in sorted(root.iterdir()) if d.is_dir()
             and not d.name.startswith('.') and d.name != ARCHIVE]  # fmt: skip
    return '\n'.join(
        f'{r.slug}\t{r.status}\t{len(r.open_items)} open\t{len(r.journal.decisions)} decisions\t{r.goal}'
        for r in found
        if r is not None
    )


def shown(verb: str, slug: str) -> str:
    """``status`` (the derived summary) or ``show`` (TASK.md and the journal) of task *slug*, open or archived."""
    folder = ledger() / slug if (ledger() / slug / 'TASK.md').is_file() else archived(slug)
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
    return status(taskjournal.record(folder))  # type: ignore[arg-type]
