"""MACHINE-FILE-IS-RENDERED: the machine file is written by its doors alone, never by hand.

User ruling 2026-11-15: every illegal modification is blocked, with enough feedback. The machine file
(:func:`lab_commons.config.config_path`) is a RENDER (:mod:`dev_lab.dev.devhost`) of three layers -- the family
file, the host file and the machine's local tables -- so a hand edit is either lost at the next render (a family or
host key) or unrecorded (a local key). Its doors: change the config source and re-render, or set one local key with
``devhost local set``. Two callers read this module:

* the shell deny row :mod:`dev_lab.dev._deny_machinefile_row` spells a shell write onto the file as a pattern;
* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_write`.

A write the hooks cannot see (the user's own editor) is named by the next ``SessionStart`` drift notice, key by key
with the layer that owns it (:func:`dev_lab.dev.devhost.drift`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from lab_commons.config import config_path

from dev_lab.dev.disclosure import details_for

__all__ = ['HAZARD', 'REMEDY', 'RULE_ID', 'refuse_write']

RULE_ID: Final = 'MACHINE-FILE-IS-RENDERED'
HAZARD: Final = 'the machine file is a render: a hand edit is lost at the next render or changes a fact unrecorded.'
REMEDY: Final = (
    'A family or host key: change it in the config source (family.toml or hosts/<machine>.toml) through its pull '
    'request, then `{python} -m dev_lab.dev.devhost render --write`. A local key ([repos], [user]): '
    '`{python} -m dev_lab.dev.devhost local set <table>.<key> <value>` (or `local unset <table>.<key>`).'
)


def refuse_write(path: Path, *, machine: Path | None = None) -> str | None:
    """The refusal for an agent writing *path* when it is the machine file (*machine* overrides it); else ``None``."""
    target = os.path.normcase(Path(path).expanduser().resolve())
    if target != os.path.normcase((machine or config_path()).resolve()):
        return None
    from dev_lab.dev.venvpath import running_interpreter  # noqa: PLC0415 -- the remedy's interpreter, at refusal time

    remedy = REMEDY.replace('{python}', running_interpreter())
    return f'{RULE_ID}: {Path(path).as_posix()} -- {HAZARD} {remedy}\n{details_for(RULE_ID)}'
