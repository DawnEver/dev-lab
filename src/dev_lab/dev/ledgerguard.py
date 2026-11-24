"""LEDGER-WRITES-THROUGH-ITS-DOOR: a task's ``TASK.md`` and ``JOURNAL.md`` are written by the ledger CLI alone.

Kept from the retired rem plugin's task guard (user ruling 2026-11-23), now dev-lab's: opening or closing a task is
the user's act and a journal is append-only, so an agent never writes either file directly -- not with a file tool,
not with a shell writer. The door is the global task ledger's CLI, ``python -m dev_lab.dev.task``, which holds the
ledger's location and its authority checks; this guard knows only the files' SHAPE, so it holds wherever a ledger
lives: ``tasks/<slug>/`` and a closed task's ``tasks/archive/<date>/<slug>/``.

Two halves, one shape (:data:`LEDGER_FILE`):

* a Write/Edit/MultiEdit/NotebookEdit -- :func:`refuse_write`, called by the ``codeplace`` write hook;
* a shell redirect, ``tee``, ``cp``/``mv`` target, ``sed -i``, ``Set-Content``/``Add-Content``/``Out-File`` onto
  one -- the deny row :mod:`dev_lab.dev._deny_ledger_row`.

Reading a ledger file stays allowed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from dev_lab.dev.disclosure import details_for

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['DOOR', 'HAZARD', 'LEDGER_FILE', 'REMEDY', 'RULE_ID', 'refuse_write']

RULE_ID: Final = 'LEDGER-WRITES-THROUGH-ITS-DOOR'
DOOR: Final = 'python -m dev_lab.dev.task'
#: A ledger file, as the tail of a path (either separator): ``tasks/[archive/<date>/]<slug>/(TASK|JOURNAL).md``.
LEDGER_FILE: Final = r'(?:^|[\\/])tasks[\\/](?:archive[\\/][^\\/\s]+[\\/])?[^\\/\s]+[\\/](?:TASK|JOURNAL)\.md'
HAZARD: Final = (
    'a task file is the user`s and the ledger`s: opening or closing a task is the user`s act and a journal is '
    'append-only, so a direct write bypasses both.'
)
REMEDY: Final = (
    f'write through the ledger CLI, `{DOOR}` (its verbs: `{DOOR} --help`), or propose the change to the user'
)
_FILE: Final = re.compile(LEDGER_FILE + r'\Z')


def refuse_write(path: Path) -> str | None:
    """The refusal for a file-tool write onto a ledger file; ``None`` for any other path."""
    if _FILE.search(path.as_posix()) is None:
        return None
    return f'{RULE_ID}: {path} -- {HAZARD}\n{REMEDY}\n{details_for(RULE_ID)}'
