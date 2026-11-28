"""MACHINE-FILE-IS-RENDERED: the machine file is written by its doors alone, never by hand.

User ruling 2026-11-15: every illegal modification is blocked, with enough feedback. The machine file
(:func:`lab_commons.config.config_path`) is a RENDER (:mod:`dev_lab.dev.devhost`) of three layers -- the family
file, the host file and the machine's local tables -- so a hand edit is either lost at the next render (a family or
host key) or unrecorded (a local key). Its doors: change the config source and re-render, or set one local key with
``devhost local set``. Two callers read this module:

* the shell deny row :mod:`dev_lab.dev._deny_machinefile_row` prefilters a shell write onto any ``.toml`` and asks
  :func:`main` (``--admit``), which matches :func:`shell_write_pattern` against THIS machine's file -- derived here at
  hook time, because the file's name is private to a machine and the row renders into tracked files (dev-lab #1000);
* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_write`.

A write the hooks cannot see (the user's own editor) is named by the next ``SessionStart`` drift notice, key by key
with the layer that owns it (:func:`dev_lab.dev.devhost.drift`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, Final, cast

from lab_commons.config import config_path
from lab_commons.home import home

from dev_lab.dev.disclosure import details_for

__all__ = [
    'HAZARD',
    'REMEDY',
    'RULE_ID',
    'judge',
    'machine_parts',
    'machine_tail',
    'main',
    'refuse_write',
    'shell_write_pattern',
]

RULE_ID: Final = 'MACHINE-FILE-IS-RENDERED'
HAZARD: Final = 'the machine file is a render: a hand edit is lost at the next render or changes a fact unrecorded.'
REMEDY: Final = (
    'family/host key: change family.toml or hosts/<machine>.toml by PR, then `{python} -m dev_lab.dev.devhost render '
    '--write`; local key: `{python} -m dev_lab.dev.devhost local set <table>.<key> <value>` (or local unset)'
)


def refuse_write(path: Path, *, machine: Path | None = None) -> str | None:
    """The refusal for an agent writing *path* when it is the machine file (*machine* overrides it); else ``None``."""
    target = os.path.normcase(Path(path).expanduser().resolve())
    if target != os.path.normcase((machine or config_path()).resolve()):
        return None
    from dev_lab.dev.venvpath import running_interpreter  # noqa: PLC0415 -- the remedy's interpreter, at refusal time

    remedy = REMEDY.replace('{python}', running_interpreter())
    return f'{RULE_ID}: {Path(path).as_posix()} -- {HAZARD} {remedy}\n{details_for(RULE_ID)}'


_ANY: Final = r'[^\n;&|]*'
_END: Final = r'\s*(?:$|[;&|)\n])'


def machine_parts(machine: Path | None = None) -> tuple[str, ...]:
    """*machine* (default the machine file) below home; an override outside home keeps its last two parts."""
    path = machine or config_path()
    try:
        return path.relative_to(home()).parts
    except ValueError:
        return path.parts[-2:]


def machine_tail(machine: Path | None = None) -> str:
    """The regex naming *machine* (default the machine file) by :func:`machine_parts`, any separator between."""
    parts = machine_parts(machine)
    return ''.join(r'[\\/]+' + re.escape(part) for part in parts)


def shell_write_pattern(tail: str) -> str:
    """A shell write (redirect, tee, sed -i, a PowerShell writer, a copy/move target) onto the file *tail* names."""
    file = tail + r'["\']?(?![^\s;&|])'
    return (
        rf'(?:>{_ANY}{file}'
        rf'|\btee\b{_ANY}{file}'
        rf'|\bsed\b(?=[^\n;&|]*\s-[a-zA-Z]*i){_ANY}{file}'
        rf'|(?:Set-Content|Out-File|Add-Content){_ANY}{file}'
        rf'|\b(?:cp|mv|Copy-Item|Move-Item)\b{_ANY}{file}{_END})'
    )


def judge(payload: Mapping[str, Any], *, machine: Path | None = None) -> str | None:
    """The refusal for the shell call in hook *payload* when it writes the machine file; else ``None``."""
    tool_input = cast('object', payload.get('tool_input'))
    command = cast('Mapping[str, object]', tool_input).get('command') if isinstance(tool_input, Mapping) else None
    if not isinstance(command, str) or not re.search(shell_write_pattern(machine_tail(machine)), command):
        return None
    from dev_lab.dev.venvpath import running_interpreter  # noqa: PLC0415 -- the remedy's interpreter, at refusal time

    remedy = REMEDY.replace('{python}', running_interpreter())
    return f'{RULE_ID}: {HAZARD}\n{remedy}\n{details_for(RULE_ID)}'


def main(argv: list[str] | None = None, *, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """``--admit``: judge the shell hook payload on stdin; exit 1 with the refusal on stdout, else 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.machineguard', description=main.__doc__)
    parser.add_argument('--admit', action='store_true', required=True)
    parser.parse_args(argv)
    try:
        payload = cast('object', json.loads((stdin or sys.stdin.buffer).read().decode('utf-8')))
    except ValueError:
        return 0
    reason = judge(cast('dict[str, Any]', payload)) if isinstance(payload, dict) else None
    if reason is None:
        return 0
    out = stdout or sys.stdout.buffer
    out.write(reason.encode('utf-8'))
    out.flush()
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
