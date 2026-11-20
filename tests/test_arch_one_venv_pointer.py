"""``.venv`` IS THE ONE POINTER TO THE CURRENT ENVIRONMENT (user ruling 2026-11-20); ``.venv-current`` is retired.

The retired file is spelled once, ``venvpointer.RETIRED_POINTER``, which only the migration and the stray report
use. Code is scanned, never prose: every string literal of ``src/`` Python that is not a docstring, and every
non-comment line of the shipped JS and shell.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

SRC: Final = Path(__file__).resolve().parents[1] / 'src'
SPELLING: Final = re.compile(r'\.venv-current')
#: The one module that spells it: it defines RETIRED_POINTER.
SPELLER: Final = 'dev_lab/dev/venvpointer.py'


def _literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    ]


def _code_lines(path: Path) -> list[str]:
    comment = '#' if path.suffix == '.sh' else '//'
    lines = path.read_text(encoding='utf-8').splitlines()
    return [line for line in lines if not line.lstrip().startswith((comment, '*'))]


def spelled(root: Path) -> dict[str, list[str]]:
    """Each file under *root* whose code spells ``.venv-current``, with the spellings."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob('*')):
        if path.suffix == '.py':
            texts = _literals(path)
        elif path.suffix in {'.js', '.sh'}:
            texts = _code_lines(path)
        else:
            continue
        if hits := [text for text in texts if SPELLING.search(text)]:
            found[path.relative_to(root).as_posix()] = hits
    return found


def test_only_the_migration_constant_spells_the_retired_pointer() -> None:
    found = spelled(SRC)
    assert set(found) == {SPELLER}, f'the retired .venv-current in code: use venvpointer.POINTER (.venv) -- {found}'


def test_planted_the_retired_spelling_is_caught_and_prose_is_not(tmp_path: Path) -> None:
    """PLANTED CONTROL: the retired file in a literal, a JS line and a shell line; prose and ``.venv`` pass."""
    (tmp_path / 'a.py').write_text('"""Prose: .venv-current is retired."""\nP = ".venv-current"\nQ = ".venv"\n',
                                   encoding='utf-8')  # fmt: skip
    (tmp_path / 'b.js').write_text("// .venv-current\nconst p = '.venv-current';\n", encoding='utf-8')
    (tmp_path / 'c.sh').write_text('# .venv-current\nhead -n 1 "$1/.venv-current"\n', encoding='utf-8')
    assert spelled(tmp_path) == {
        'a.py': ['.venv-current'],
        'b.js': ["const p = '.venv-current';"],
        'c.sh': ['head -n 1 "$1/.venv-current"'],
    }
