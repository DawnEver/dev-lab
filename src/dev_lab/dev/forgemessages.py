"""The merge decision's MESSAGE condition: a PR head's commit messages, judged by the repo's own hook row.

A repo declares the judge by running ``cz-push-range`` in a pre-push hook row; :mod:`dev_lab.dev.forgemerge` asks
:func:`message_wait` once per decision and notes :data:`MESSAGES_NOT_DECLARED` when no row is declared.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.githooks import PYTHON_ENV, bash_executable, hook_path
from dev_lab.dev.githooks.table import hook_table

if TYPE_CHECKING:
    from dev_lab.dev.githooks.table import Hook

__all__ = ['MESSAGES_NOT_DECLARED', 'MESSAGE_TIMEOUT_S', 'message_row', 'message_wait']


#: The shipped script judging commit messages over a range; the repo's pre-push row running it is the declaration.
_MESSAGE_SCRIPT: Final = 'cz-push-range'

#: Seconds the message row may run inside one merge decision before it is a named wait, never a hung tick.
MESSAGE_TIMEOUT_S: Final[float] = 300.0

#: What a decision notes when the repo declares no message row: nothing judged the messages.
MESSAGES_NOT_DECLARED: Final = 'messages: not declared'


def message_row(root: Path) -> Hook | None:
    """The repo's pre-push row running ``cz-push-range``, or ``None`` when it declares none."""
    return next((one for one in hook_table(root).get('pre-push', ()) if _MESSAGE_SCRIPT in one.run), None)


def message_wait(root: Path, base: str, head: str) -> str | None:
    """Why *head*'s commits over *base* fail the repo's declared message row, or ``None`` (passed, or none declared).

    The SAME script and env the pre-push row runs, handed git's pre-push line for ``<base sha>..<head>``.
    """
    row = message_row(root)
    if row is None:
        return None
    base_sha = _door.run(
        ['git', 'rev-parse', '--verify', '--quiet', base],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    if base_sha.returncode != 0:
        return f'{row.id}: {base} does not resolve in this checkout -- fetch origin, then judge again'
    line = f'refs/heads/pr {head} refs/heads/pr {base_sha.stdout.strip()}\n'
    try:
        done = _door.run(
            [bash_executable(), hook_path(_MESSAGE_SCRIPT).as_posix(), '--merge-decision'],
            cwd=str(root),
            input=line,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            env={**os.environ, PYTHON_ENV: sys.executable, **row.env},
            timeout=MESSAGE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f'{row.id} timed out after {MESSAGE_TIMEOUT_S} s over {base}..{head[:12]}'
    if done.returncode == 0:
        return None
    said = [one for one in (done.stdout + done.stderr).splitlines() if one.strip()]
    return f'{row.id} refuses a message over {base}..{head[:12]}: {said[-1] if said else done.returncode}'
