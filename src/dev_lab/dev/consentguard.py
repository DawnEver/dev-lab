"""CONSENT-CODE-FROM-THE-USER: a consent code is the user's, and its credentials are written by the grant alone.

User ruling 2026-11-08 (it replaces the 2026-11-07 reading that only the user may type a code): the USER gives the
TOTP code, the AGENT runs ``dev_lab.ops.consent grant --code`` with it. A code the user did not give in this
conversation is never passed, and none is stored, logged or reused. What stays refused is the forgery no code
excuses: an agent writing under the consent state directory plants a credential no issuer signed. Two callers read
this module:

* the shell deny row :mod:`dev_lab.dev._deny_consent_row` spells a shell write there as a pattern;
* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_write`.

:func:`state_dir` is the ONE declaration of where a granted credential lives; the grant writes there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dev_lab.dev.disclosure import details_for

__all__ = ['HAZARD', 'REMEDY', 'RULE_ID', 'STATE_PARTS', 'refuse_write', 'state_dir']

RULE_ID: Final = 'CONSENT-CODE-FROM-THE-USER'
#: The consent state directory, below the home.
STATE_PARTS: Final = ('.motronics', 'state', 'consent')
HAZARD: Final = (
    'a consent credential is written by the grant from a code the USER gave; a planted one forges the consent.'
)
REMEDY: Final = (
    'Write the request JSON, ask the user for their Authenticator code, run '
    '`{python} -m dev_lab.ops.consent grant <request.json> --code <the code they gave>`, '
    'then read the credential it wrote.'
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
