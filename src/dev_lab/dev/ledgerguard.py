"""LEDGER-WRITES-THROUGH-ITS-DOOR: a task's ``TASK.md`` and ``JOURNAL.md`` are written by the ledger CLI alone.

Kept from the retired rem plugin's task guard (user ruling 2026-11-23), now dev-lab's: opening or closing a task is
the user's act and a journal is append-only, so an agent never writes either file directly -- not with a file tool,
not with a shell writer. The door is the global task ledger's CLI, ``python -m dev_lab.dev.task``, which holds the
ledger's location and its authority checks; this guard knows only the files' SHAPE, so it holds wherever a ledger
lives: ``tasks/<slug>/`` and a closed task's ``tasks/archive/<date>/<slug>/``.

It ALSO KNOWS THE LEDGER DIRECTORY (:func:`ledger_dir`, the path :func:`dev_lab.dev.taskledger.ledger` resolves;
folded in 2026-11-24 from the second ledger guard): nothing but the door creates, removes or moves anything in it.

Two halves:

* a Write/Edit/MultiEdit/NotebookEdit -- :func:`refuse_write`, called by the ``codeplace`` write hook: any path of
  the :data:`LEDGER_FILE` shape, and any path inside :func:`ledger_dir`;
* the deny row :mod:`dev_lab.dev._deny_ledger_row`: a shell redirect, ``tee``, ``cp``/``mv`` target, ``sed -i``,
  ``Set-Content``/``Add-Content``/``Out-File`` onto a ledger file, and a ``mkdir``/``rm``/``rmdir``/``mv`` (and their
  PowerShell spellings) naming the ledger directory (:data:`LEDGER_DIR_TAIL`).

Reading a ledger file stays allowed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from lab_commons.home import home, part

from dev_lab.dev.disclosure import details_for
from dev_lab.dev.taskledger import LEDGER_DIR
from dev_lab.dev.venvpath import running_interpreter

__all__ = ['DOOR', 'HAZARD', 'LEDGER_DIR_TAIL', 'LEDGER_FILE', 'REMEDY', 'RULE_ID', 'ledger_dir', 'refuse_write']

RULE_ID: Final = 'LEDGER-WRITES-THROUGH-ITS-DOOR'
DOOR: Final = '{python} -m dev_lab.dev.task'
#: A ledger file, as the tail of a path (either separator): ``tasks/[archive/<date>/]<slug>/(TASK|JOURNAL).md``.
LEDGER_FILE: Final = r'(?:^|[\\/])tasks[\\/](?:archive[\\/][^\\/\s]+[\\/])?[^\\/\s]+[\\/](?:TASK|JOURNAL)\.md'
HAZARD: Final = (
    'opening or closing a task is the user`s act and a journal is append-only: a direct write bypasses both.'
)
REMEDY: Final = (
    f'write through the ledger CLI, `{DOOR}` (its verbs: `{DOOR} --help`), or propose the change to the user'
)
_FILE: Final = re.compile(LEDGER_FILE + r'\Z')


def ledger_dir() -> Path:
    """The ledger directory, ``<machine home>/repos/tasks`` -- whether or not it is cloned yet."""
    return part('repos') / LEDGER_DIR


def _tail() -> str:
    """The ledger directory below the machine home as a regex (either separator), so no home name is in a pattern."""
    path = ledger_dir()
    try:
        parts = path.relative_to(home()).parts
    except ValueError:
        parts = path.parts[-2:]
    return ''.join(r'[\\/]+' + re.escape(one) for one in parts)


#: The ledger directory as the end of a shell word, or a path inside it.
LEDGER_DIR_TAIL: Final = _tail() + r"""(?:[\\/]|["']?(?=[\s;&|)]|$))"""


def _inside(path: Path, folder: Path) -> bool:
    target, root = (os.path.normcase(p.expanduser().resolve()) for p in (Path(path), folder))
    return target == root or target.startswith(root.rstrip(os.sep) + os.sep)


def refuse_write(path: Path) -> str | None:
    """The refusal for a file-tool write onto a ledger file or into the ledger directory; ``None`` otherwise."""
    if _FILE.search(path.as_posix()) is None and not _inside(path, ledger_dir()):
        return None
    remedy = REMEDY.replace('{python}', running_interpreter())
    return f'{RULE_ID}: {path} -- {HAZARD}\n{remedy}\n{details_for(RULE_ID)}'
