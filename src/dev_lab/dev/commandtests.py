"""A COMMAND-PART repo's test command, read from its ONE declaration and cut down to a selection.

A repo whose tests are not pytest declares its suite once, as its producer (:mod:`dev_lab.dev.commandpart`)::

    [tool.lab_commons.tests]
    produce = ["-m", "dev_lab.dev.commandpart", "{part}", "--", "node", "--test", "tests/*.test.mjs"]

:func:`declared_command` reads the command after ``--`` back off that line -- the producer's matrix
(:func:`dev_lab.dev.jobparts.command_part`) and a targeted verify both derive from it, so no second declaration
exists. :func:`selected_command` keeps the command's program and options and swaps its own test globs for the
paths a verify run selected; ``npm test`` / ``npm run <script>`` is first expanded to the ``package.json``
script it names, because npm appends arguments rather than replacing the script's globs.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Final

from lab_commons.hpc.declared import kit_tables

__all__ = ['MODULE', 'SCRIPT_SUFFIXES', 'declared_command', 'script_paths', 'selected_command']

#: The producer module of a repo whose suite is one command.
MODULE: Final = 'dev_lab.dev.commandpart'

#: The suffixes by which a selected path names a test the declared command runs, not a pytest file.
SCRIPT_SUFFIXES: Final = ('.mjs', '.cjs', '.js')

#: ``npm <verb>`` that runs the ``test`` script; ``npm run <script>`` names its own.
_NPM_SCRIPT: Final = {('test',): ('test',), ('t',): ('test',)}
_NPM_RUN: Final = {('run',), ('run-script',)}


def declared_command(text: str) -> tuple[str, ...] | None:
    """The test command pyproject *text* declares through :data:`MODULE`, else ``None`` (not a command-part repo)."""
    produce = kit_tables(text).get('tests', {}).get('produce')
    if not isinstance(produce, list) or MODULE not in produce:
        return None
    rest = [str(word) for word in produce[produce.index(MODULE) + 1 :]]
    return tuple(rest[rest.index('--') + 1 :]) if '--' in rest else None


def script_paths(root: Path, arguments: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(pytest arguments, selected script tests)``: an existing path with a script suffix is the latter."""
    scripts = tuple(
        arg for arg in arguments if not arg.startswith('-') and arg.endswith(SCRIPT_SUFFIXES) and (root / arg).is_file()
    )
    return tuple(arg for arg in arguments if arg not in scripts), scripts


def selected_command(root: Path, command: tuple[str, ...], paths: tuple[str, ...]) -> tuple[str, ...] | str:
    """*command* running exactly *paths*: its program and options, its positional globs replaced; else why not.

    The ``str`` answer is the refusal's cause (an npm script ``package.json`` does not hold), never a guess.
    """
    if command[:1] == ('npm',):
        name = _NPM_SCRIPT.get(command[1:2]) or (command[2:3] if command[1:2] in _NPM_RUN else ())
        if not name:
            return f'{shlex.join(command)} names no npm script this can cut to a selection'
        try:
            scripts = json.loads((root / 'package.json').read_text(encoding='utf-8')).get('scripts', {})
        except (OSError, ValueError) as cause:
            return f'package.json is unreadable ({cause}), so the npm script behind {shlex.join(command)} is unknown'
        script = scripts.get(name[0])
        if not isinstance(script, str) or not script.strip():
            return f'package.json declares no {name[0]!r} script for {shlex.join(command)}'
        command = tuple(shlex.split(script))
    program, *rest = command
    options = [word for word in rest if word.startswith('-')]
    if Path(program).stem == 'node' and '--test' not in options:
        # A runner script (`node run-tests.mjs`) loses its positional; plain `node p1 p2` would run p1 alone and
        # hand p2 to it as argv, so p2 would pass unrun. `--test` runs every selected file.
        options.insert(0, '--test')
    return (program, *options, *paths)
