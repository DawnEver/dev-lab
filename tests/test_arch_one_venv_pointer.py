"""``.venv-current`` IS THE ONE STATEMENT OF THE CURRENT ENVIRONMENT (user ruling 2026-11-20).

No code reads or writes a ``.venv`` path: the retired spelling is named once, ``venvpointer.RETIRED_ALIAS``, and
only the migration and the stray report use it. Code is scanned, never prose: every string literal of ``src/``
Python that is not a docstring, and every non-comment line of the shipped JS and shell.

A FEW MODULES MATCH THE SPELLING rather than use it as a path -- a permission row admitting an interpreter
spelling, a refusal recognising a relative one. Each is a NAMED entry with its reason; an entry that no longer
holds the spelling fails, so the set only shrinks.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

SRC: Final = Path(__file__).resolve().parents[1] / 'src'
#: A ``.venv`` path segment: not ``.venvs``, not ``.venv-current``, not a longer word.
SPELLING: Final = re.compile(r'(?<![\w.-])\.venv(?![\w-])')
#: Modules that MATCH the spelling (a pattern, a permission row), with why; never a reader or writer of the path.
MATCHERS: Final = {
    'dev_lab/dev/venvpointer.py': 'names RETIRED_ALIAS, the one spelling',
    'dev_lab/dev/venvpath.py': 'VENV_LAYOUTS: the interpreter spellings permission rows and refusals match',
    'dev_lab/dev/famtests/remedypaths.py': 'recognises a relative .venv interpreter in a remedy',
    'dev_lab/dev/famtests/venvspelling.py': 'recognises a platform-bound .venv interpreter spelling',
    'dev_lab/dev/codeplace.py': 'directories a code-place walk never enters',
    'dev_lab/dev/_famconfig_rows.py': "the family's ignore rows",
    'dev_lab/dev/ruffwaivers.py': 'the machine excludes of every repo',
}


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
    return [
        line for line in path.read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith((comment, '*'))
    ]


def spelled(root: Path) -> dict[str, list[str]]:
    """Each file under *root* whose code spells a ``.venv`` path, with the spellings."""
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


def test_no_code_reads_or_writes_a_venv_path() -> None:
    found = spelled(SRC)
    rogue = {name: hits for name, hits in found.items() if name not in MATCHERS}
    assert not rogue, f'a .venv path in code: name the env through venvpointer.current or RETIRED_ALIAS -- {rogue}'


def test_every_named_matcher_still_holds_the_spelling() -> None:
    found = spelled(SRC)
    assert not [name for name in MATCHERS if name not in found], 'drop a matcher that no longer spells .venv'


def test_planted_a_venv_interpreter_path_is_caught(tmp_path: Path) -> None:
    """PLANTED CONTROL: the spelling the ruling retired, in a literal, a JS line and a shell line."""
    (tmp_path / 'a.py').write_text('"""Docstring prose: .venv/bin/python is fine."""\nP = ".venv/bin/python"\n',
                                   encoding='utf-8')  # fmt: skip
    (tmp_path / 'b.js').write_text("// .venv/bin/python\nconst p = '.venv/bin/python';\n", encoding='utf-8')
    (tmp_path / 'c.sh').write_text('# .venv/bin/python\npy=./.venv/bin/python\n', encoding='utf-8')
    (tmp_path / 'd.py').write_text("P = '.venvs/x/bin/python'\nQ = '.venv-current'\n", encoding='utf-8')
    found = spelled(tmp_path)
    assert found == {
        'a.py': ['.venv/bin/python'],
        'b.js': ["const p = '.venv/bin/python';"],
        'c.sh': ['py=./.venv/bin/python'],
    }, 'prose, .venvs and the pointer are no .venv path'
