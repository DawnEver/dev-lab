"""THE TASK LEDGER IS NO CHECKOUT'S (user ruling 2026-11-23): no source names the retired in-checkout ledger.

The ledger is ONE per machine -- the checkout of the family ``tasks`` repo, resolved only by
:func:`dev_lab.dev.taskledger.ledger`. The retired spelling (:data:`RETIRED`, the ``.claude`` directory's ``tasks``
child of a repository) survives longest as a path literal or a path join, so both shapes are refused in ``src/``:
the joined text, and the two pieces adjacent in one call or ``/`` chain. This file is the one place it is spelled
(RETIRED-NAMES-REGISTERED); the successor is :func:`~dev_lab.dev.taskledger.ledger`.
"""

from __future__ import annotations

import ast
from typing import Final

from _arch_corpus import SOURCE_FLOOR, assert_floor, rel, source_modules

#: The retired spelling and its successor.
RETIRED: Final = '.claude/tasks'
SUCCESSOR: Final = 'dev_lab.dev.taskledger.ledger() -- the global tasks repo checkout ([tasks] repo -> [repos].<repo>)'
_PIECES: Final = tuple(RETIRED.split('/'))


def _strings(node: ast.AST) -> list[str]:
    found = [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return [n.value for n in sorted(found, key=lambda n: (n.lineno, n.col_offset))]  # source order, not BFS


def _adjacent(values: list[str]) -> bool:
    return any(values[i : i + 2] == list(_PIECES) for i in range(len(values) - 1))


def offenses(source: str) -> list[str]:
    """Each place *source* spells the retired ledger: a literal holding it, or its two pieces adjacent."""
    found: list[str] = [f'line {line}' for line, text in enumerate(source.splitlines(), 1) if RETIRED in text]
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _adjacent([a.value for a in node.args if isinstance(a, ast.Constant)]):
            found.append(f'line {node.lineno}: a join of {_PIECES}')
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _adjacent(_strings(node)):
            found.append(f'line {node.lineno}: a path chain of {_PIECES}')
    return found


def test_no_source_spells_the_retired_checkout_ledger() -> None:
    modules = source_modules()
    assert_floor(len(modules), SOURCE_FLOOR, 'retired checkout ledger')
    found = {rel(path): hits for path in modules if (hits := offenses(path.read_text(encoding='utf-8')))}
    assert found == {}, f'the retired in-checkout ledger, spelled in src (use {SUCCESSOR}): {found}'


def test_planted_violations_are_found() -> None:
    """PLANTED CONTROL: each retired shape is found; the successor's spelling and an unrelated join are not."""
    literal = f"ROOT = '{RETIRED}/'\n"
    joined = f"from pathlib import Path\nx = Path('{_PIECES[0]}', '{_PIECES[1]}')\n"
    chain = f"from pathlib import Path\nx = Path('r') / '{_PIECES[0]}' / '{_PIECES[1]}' / 'slug'\n"
    for planted in (literal, joined, chain):
        assert offenses(planted), planted
    assert offenses("x = ledger() / 'slug'\ny = Path('.claude', 'memory')\n") == []
