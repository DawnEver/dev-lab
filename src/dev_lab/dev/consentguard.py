"""CONSENT-CODE-NEVER-TYPED: the user's consent is typed by the user, and its credentials are written by the grant.

User-approved design 2026-11-07 (:mod:`dev_lab.ops.consent`). An agent that types a TOTP code into a consent,
break-glass or TOTP command -- as an argument, through a pipe, a here-string or a heredoc -- or writes under the
consent state directory forges the consent it asks for. Two callers read this module:

* the shell deny row :mod:`dev_lab.dev._deny_consent_row` spells those shapes as a pattern;
* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_write`.

:func:`state_dir` is the ONE declaration of where a granted credential lives; the grant writes there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dev_lab.dev.disclosure import details_for

__all__ = ['HAZARD', 'REMEDY', 'RULE_ID', 'STATE_PARTS', 'refuse_write', 'state_dir']

RULE_ID: Final = 'CONSENT-CODE-NEVER-TYPED'
#: The consent state directory, below the home.
STATE_PARTS: Final = ('.motronics', 'state', 'consent')
HAZARD: Final = "a consent code is the USER's word: an agent typing, piping or planting one forges the consent."
REMEDY: Final = (
    'Write the request JSON, hand the user `{python} -m dev_lab.ops.consent grant <request.json>` to run in their own '
    'terminal, then read the credential it wrote.'
)


def state_dir(home: Path | None = None) -> Path:
    """Where granted credentials live: ``~/.motronics/state/consent``."""
    return (Path.home() if home is None else home).joinpath(*STATE_PARTS)


def refuse_write(path: Path, *, home: Path | None = None) -> str | None:
    """The refusal for an agent writing *path* under :func:`state_dir`; ``None`` elsewhere."""
    target = Path(os.path.normcase(Path(path).resolve()))
    base = Path(os.path.normcase(state_dir(home).resolve()))
    if target == base or base in target.parents:
        where = f'{Path(path).as_posix()} is under the consent state directory'
        return f'{RULE_ID}: {where} -- {HAZARD} {REMEDY}\n{details_for(RULE_ID)}'
    return None
