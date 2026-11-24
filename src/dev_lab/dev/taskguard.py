"""LEDGER-WRITTEN-BY-ITS-DOOR: the machine's task ledger is written only through ``python -m dev_lab.dev.task``.

The ledger (:func:`dev_lab.dev.taskledger.ledger`) is append-only history behind the user's authority: a journal line
rewritten by hand loses its ids' meaning, a hand-written ``TASK.md`` forges an authority, and a hand edit skips the
commit every door write makes. Two callers read this module (rem's ``task-guard`` hook, ported):

* the shell deny row :mod:`dev_lab.dev._deny_ledger_row` spells a shell write into the ledger as a pattern;
* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_write`.

Reading the ledger (``cat``, ``git -C <ledger> log``, a ``cp`` FROM it) stays free. A write the hooks cannot see is
detected: every door write is a commit, so ``git -C <ledger> status`` shows a hand edit.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from lab_commons.home import part

from dev_lab.dev.disclosure import details_for
from dev_lab.dev.taskledger import LEDGER_DIR

__all__ = ['HAZARD', 'REMEDY', 'RULE_ID', 'refuse_write']

RULE_ID: Final = 'LEDGER-WRITTEN-BY-ITS-DOOR'
HAZARD: Final = (
    "the task ledger is append-only history behind the user's authority: a hand write rewrites a journal or forges "
    'a TASK.md, and skips the commit every door write makes.'
)
REMEDY: Final = (
    'python -m dev_lab.dev.task log|decide|open-item|close-item|handoff appends to the task the branch '
    'pr/<slug>/<feature> names, amend corrects a line (help lists every verb); opening or closing a task is the '
    "user's `/task open|close <slug>` -- propose it to the user"
)


def refuse_write(path: Path, *, ledger: Path | None = None) -> str | None:
    """The refusal for an agent writing *path* inside the task ledger (*ledger* overrides it); else ``None``."""
    target = Path(os.path.normcase(Path(path).expanduser().resolve()))
    base = Path(os.path.normcase((ledger or part('repos') / LEDGER_DIR).resolve()))
    if target != base and base not in target.parents:
        return None
    return f'{RULE_ID}: {Path(path).as_posix()} is in the task ledger -- {HAZARD} {REMEDY}\n{details_for(RULE_ID)}'
