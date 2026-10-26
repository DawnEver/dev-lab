"""A REMEDY NAMES AN ABSOLUTE INTERPRETER -- the assertion every consumer runs over the remedies it prints.

THE INCIDENT, 2026-10-26. A refusal's exit read ``Use .venv/Scripts/python.exe ...``; the agent's shell sat in
another directory, the relative path failed, and the agent handed the user an absolute rewrite to run instead
of running it itself. A remedy is executed from wherever the reader's cwd happens to be, so the interpreter it
names is absolute (:func:`dev_lab.dev.venvpath.remedy_interpreter`) or the token a printer expands into one
(:data:`dev_lab.dev.venvpath.PYTHON_TOKEN`). A relative ``.venv`` interpreter, or a bare ``python -m``, is a
remedy that works from one directory.

THE POPULATION ARRIVES AS AN ARGUMENT: a mapping of *where* to the remedy text, so a red names the source. The
floor is on texts read, and :func:`assert_a_planted_relative_remedy_is_convicted` drives the real reader over
both directions, so a reader whose pattern stopped matching cannot pass as a clean tree.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from dev_lab.dev.floors import assert_floor
from dev_lab.dev.venvpath import PYTHON_TOKEN, venv_interpreter

__all__ = [
    'assert_a_planted_relative_remedy_is_convicted',
    'assert_remedies_name_absolute_interpreters',
    'relative_interpreters',
]

#: A ``.venv`` interpreter not preceded by a path segment (so ``C:/r/.venv/...`` and ``/home/u/r/.venv/...``
#: are spared), or a bare ``python``/``py`` interpreter word followed by ``-m`` or a script.
_RELATIVE: Final = re.compile(
    r'(?<![\w/\\:~-])(?:\.[/\\])?\.venv[/\\](?:Scripts|bin)[/\\]python'
    r'|(?:^|(?<=[\s`(\'"]))(?:python[\d.]*|py)(?:\.exe)?\s+-m\b',
)


def relative_interpreters(text: str) -> tuple[str, ...]:
    """Every line of *text* naming a relative venv interpreter or a bare ``python -m``."""
    return tuple(line for line in text.splitlines() if _RELATIVE.search(line))


def assert_remedies_name_absolute_interpreters(texts: Mapping[str, str], *, floor: int) -> None:
    """No remedy in *texts* (where -> text) names a relative or bare interpreter; at least *floor* texts read."""
    assert_floor(len(texts), floor=floor, what='remedy texts read')
    found = [f'  {where}: {line.strip()}' for where, text in texts.items() for line in relative_interpreters(text)]
    if found:
        msg = (
            f'{len(found)} remedy line(s) name an interpreter that runs from one directory only. Name it absolute '
            f'(venvpath.remedy_interpreter / running_interpreter) or carry {PYTHON_TOKEN} for the printer to '
            'expand:\n' + '\n'.join(found)
        )
        raise AssertionError(msg)


def assert_a_planted_relative_remedy_is_convicted() -> None:
    """PLANTED CONTROL: the shapes that shipped are convicted; absolute and tokenised spellings are spared."""
    nt, posix = venv_interpreter(os_name='nt'), venv_interpreter(os_name='posix')
    convicted = (f'Use {nt} -m x', f'./{posix} x.py', 'stop it: python -m dev_lab.dev.stoprun --pid 1')
    spared = (f'C:/r/{nt} -m x', f'/home/u/r/{posix} -m x', f'{PYTHON_TOKEN} -m x')
    missed = [line for line in convicted if not relative_interpreters(line)]
    wrong = [line for line in spared if relative_interpreters(line)]
    if missed or wrong:
        msg = f'the remedy reader is broken: missed {missed}, convicted {wrong}'
        raise AssertionError(msg)
