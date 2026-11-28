"""BARE-PYTHON in prose: a command an always-loaded page hands an agent names its interpreter (W8, dev-lab#646).

The guard hints a bare ``python``/``py`` at run time (``BARE-PYTHON``), but a rule page that SPELLS one is copied
verbatim every turn: the page teaches the wall. This body reads every inline code span of the pages a consumer
names and refuses one whose first word is a bare interpreter. ``python.exe`` under a venv, ``{python}`` and
``<venv python>`` name the interpreter and pass.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['REMEDY', 'assert_no_bare_interpreter', 'bare_interpreter_spans']

#: The remedy every refusal prints.
REMEDY = "spell the interpreter the guard teaches (the checkout's venv python, or '<venv python>'), never a bare one"

_SPAN = re.compile(r'`([^`\n]+)`')
_BARE = re.compile(r'(?:python3?|py)(?:\s|$)')


def bare_interpreter_spans(text: str) -> list[str]:
    """The inline code spans of *text* whose command word is a bare ``python``, ``python3`` or ``py``."""
    return [span for span in _SPAN.findall(text) if _BARE.match(span.strip())]


def assert_no_bare_interpreter(pages: Iterable[Path], *, root: Path) -> None:
    """No page in *pages* hands an agent a bare interpreter; each refusal names ``page: span``, then the remedy.

    Raises:
        AssertionError: a span is bare, or *pages* is empty (a scan over nothing would read green).

    """
    read = list(pages)
    found = [
        f'{page.relative_to(root).as_posix()}: `{span}`'
        for page in read
        for span in bare_interpreter_spans(page.read_text(encoding='utf-8'))
    ]
    message = (
        f'no rule page under {root}: a scan over nothing cannot say no'
        if not read
        else 'a rule page spells a bare interpreter:\n' + '\n'.join(found) + f'\n{REMEDY}'
    )
    if found or not read:
        raise AssertionError(message)
