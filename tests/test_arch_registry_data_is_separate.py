"""REGISTRY-OWNS-THE-DECISION: the table and the machinery that reads it are different files.

`_rule_rows.py` is DATA and `rules.py` is the machinery. The seam is not tidiness -- a table edited
through the module that checks it drifts away from what it describes, because the same edit that
adds a row can relax the check that would have refused it, and the diff looks like one change.

TWO THINGS ARE REFUSED HERE, and both are the seam being crossed rather than a style:

* a rule ID spelled as a literal in the MACHINERY. The registry owns which rules exist; a branch in
  `rules.py` on a particular ID is a decision moved out of the table into code nobody greps.
* the DATA module growing an import of the machinery, or any logic at all. Data that computes is a
  table with a code path in it, and a code path is where a row can be conditional.

The exemption is the module's own docstring and `__all__`-style plumbing -- prose may NAME a rule,
because a docstring that cannot quote its subject is a docstring nobody will keep accurate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import ROOT, parse

from lab_commons.dev.rules import RULES

DATA_MODULE = ROOT / 'src' / 'lab_commons' / 'dev' / '_rule_rows.py'
MACHINERY_MODULE = ROOT / 'src' / 'lab_commons' / 'dev' / 'rules.py'


def ids_hardcoded_in(path: Path, known: frozenset[str]) -> tuple[str, ...]:
    """Every rule ID appearing as a string LITERAL in *path*'s code -- docstrings excluded."""
    tree = parse(path)
    docstrings = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and _is_str(node.value)}
    return tuple(
        sorted(
            {
                node.value
                for node in ast.walk(tree)
                if _is_str(node) and id(node) not in docstrings and node.value in known
            }
        )
    )


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def test_the_machinery_branches_on_no_particular_rule() -> None:
    """THE CHECK. Which rules exist is the table's decision, and it stays there."""
    known = frozenset(rule.id for rule in RULES)
    assert known, 'the registry read empty -- an unread registry is not a clean one'
    hardcoded = ids_hardcoded_in(MACHINERY_MODULE, known)
    assert hardcoded == (), (
        f'rules.py names particular rules in code: {list(hardcoded)}. The registry owns which rules '
        f'exist; a branch on one ID is that decision moved into a file nobody greps for it.'
    )


def test_the_data_half_imports_no_machinery() -> None:
    """A table that computes is a table with a code path in it."""
    imported = {
        alias.name
        for node in ast.walk(parse(DATA_MODULE))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if (node.module or '').startswith('lab_commons')
    }
    assert imported == set(), f'_rule_rows.py imports machinery: {sorted(imported)}'
    functions = [n.name for n in parse(DATA_MODULE).body if isinstance(n, ast.FunctionDef | ast.ClassDef)]
    assert functions == [], f'_rule_rows.py defines logic: {functions}. It is DATA; the reader is rules.py.'


def test_a_planted_hardcoded_id_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, through the REAL scanner, with the docstring exemption exercised."""
    planted = tmp_path / 'planted.py'
    planted.write_text(
        '"""Prose may name DECLARATION-LIES and even quote \'DOCS-SPLIT\'."""\n\n\n'
        "def f(rule_id: str) -> bool:\n    return rule_id == 'DOCS-SPLIT'\n",
        encoding='utf-8',
    )
    known = frozenset({'DECLARATION-LIES', 'DOCS-SPLIT'})
    assert ids_hardcoded_in(planted, known) == ('DOCS-SPLIT',)
