"""TYPED-VALUES-ARE-SHOWN, over every family repo's tracked code: no intake reads what a person types hidden.

User ruling D94 (2026-11-20): every typed value comes through :mod:`dev_lab.dev.ask`, shown as typed. dev-lab's
own test refused ``getpass`` in dev-lab only; on 2026-11-24 a sibling repo (ai-lab's key intake) still read a key
through it, and no family check could see that. This body runs in EVERY repo installing dev-lab, as an always-on
row (:mod:`dev_lab.dev.famtests.alwayson`), over the forms a hidden prompt takes in each language the family
writes: Python's ``getpass`` and ``msvcrt`` key loops, a shell's silent ``read`` and echo switched off, PowerShell's
secure string and intercepted key, and a JavaScript prompt hiding its echo.

ONE ``git grep -P`` over tracked code files; ``attic/``, ``archived/`` and ``.claude/memory/`` are records, not
intakes. The floor: ``git ls-files`` lists at least one file, so an unreadable corpus never reads as clean.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

from lab_commons.launch import run

from dev_lab.dev.ask import RULE_ID
from dev_lab.dev.rules import tracked_files

__all__ = ['FORMS', 'check', 'hits']

#: Each hidden-intake form as a PCRE, joined into one pattern (the near-misses: ``getpass.getuser``, ``read -r``).
FORMS: Final = (
    r'\bgetpass\.getpass\b',
    r'\bmsvcrt\.getw?ch\b',
    r'\bread\s+-[A-Za-z]*s',
    r'\bstty\s+-echo\b',
    r'-AsSecure[S]tring\b',
    r'ReadKey\(\s*\$true',
    r'\bhideEchoBack\b',
)
_CODE: Final = ('*.py', '*.sh', '*.bash', '*.ps1', '*.psm1', '*.js', '*.mjs', '*.cjs', '*.ts')
_EXEMPT: Final = (':(exclude,glob)attic/**', ':(exclude,glob)archived/**', ':(exclude,glob).claude/memory/**')
_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 60


def hits(root: Path) -> tuple[tuple[str, int], ...]:
    """``(path, line)`` of every tracked code line under *root* holding a hidden-intake form; raises when git fails."""
    out = run(
        [_GIT, '-c', 'core.quotepath=off', 'grep', '-I', '-n', '-P', '|'.join(FORMS), '--', *_CODE, *_EXEMPT],
        cwd=root, capture_output=True, check=False, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip
    if out.returncode not in (0, 1):  # 1 means no match
        msg = f'git grep failed in {root}: {out.stderr.decode("utf-8", "replace").strip()}'
        raise AssertionError(msg)
    found = []
    for line in out.stdout.decode('utf-8', 'replace').splitlines():
        path, number, _text = line.split(':', 2)
        found.append((path, int(number)))
    return tuple(found)


def check(root: Path) -> None:
    """Raise naming every hidden intake under *root* and the one door, ``dev_lab.dev.ask``."""
    if not tracked_files(root):
        msg = f'{RULE_ID}: git ls-files listed no file in {root}, so a clean result would mean nothing'
        raise AssertionError(msg)
    found = hits(root)
    if found:
        lines = [f'{path}:{number}' for path, number in found]
        head = (
            f'{RULE_ID}: a typed value is read hidden; read it through dev_lab.dev.ask.value()/code() (shown as '
            'typed, checked before it is spent):'
        )
        msg = '\n  '.join((head, *lines))
        raise AssertionError(msg)
