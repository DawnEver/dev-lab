"""OUTPUT-HOLDS-NO-CODE, the Write/Edit half and the source scan (user ruling 2026-11-20).

The shell half is the deny row in :mod:`dev_lab.dev._deny_outputcode_row`, which owns :data:`CODE_SUFFIXES`,
the hazard and the remedy; both refusals here speak them, so the halves cannot drift.

* :func:`refuse_code_in_output` -- called by the ``codeplace`` ``PreToolUse`` hook on ``Write|Edit|MultiEdit``.
* :func:`code_doors_into_output` -- read by ``tests/test_dev_outputcode.py`` over ``src/``: a function that
  reaches an output root AND names a code suffix, ``worktree add`` or ``bundle create`` is a door writing code
  under ``output/`` (the retired worktree archive, ``moved/`` bundles, a consumer checkout made in output).
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from typing import Final

from dev_lab.dev._deny_outputcode_row import CODE_SUFFIXES, OUTPUT_HOLDS_NO_CODE

__all__ = ['code_doors_into_output', 'refuse_code_in_output']

#: Calls that resolve a path inside a checkout's output tree.
_OUTPUT_CALLS: Final = frozenset({'output_dir', 'output_path', 'checkout_output_path'})
#: git verbs that write a checkout or a bundle at the path they are given.
_CODE_VERBS: Final = (('worktree', 'add'), ('bundle', 'create'))


def refuse_code_in_output(path: Path) -> str | None:
    """The refusal for writing *path*, or ``None`` unless it is a code/bundle/patch file under ``output/``.

    ``output/`` is any path segment of that name below the nearest checkout (the nearest ancestor holding
    ``.git``, so a linked worktree is judged on its own); a path in no checkout is judged on its own segments.
    """
    target = Path(path).resolve()
    if target.suffix.lower() not in CODE_SUFFIXES:
        return None
    root = next((c for c in target.parents if (c / '.git').exists()), None)
    rel = target.relative_to(root) if root else target
    if 'output' not in rel.parts[:-1]:
        return None
    row = OUTPUT_HOLDS_NO_CODE
    return f'{row["id"]}: {rel.as_posix()} -- {row["hazard"]} {row["remedy"]}'


def _reaches_output(node: ast.AST, tainted: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
            if name in _OUTPUT_CALLS:
                return True
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
            sides = (sub.left, sub.right)
            if any(isinstance(s, ast.Constant) and s.value == 'output' for s in sides):
                return True
    return False


def _writes_code(node: ast.AST) -> bool:
    words = [s.value for s in ast.walk(node) if isinstance(s, ast.Constant) and isinstance(s.value, str)]
    if any(w.lower().endswith(CODE_SUFFIXES) for w in words):
        return True
    pairs = set(itertools.pairwise(words))
    return any(verb in pairs for verb in _CODE_VERBS)


#: The statements that hold a nested block of statements.
_BLOCK_STATEMENTS = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match,
)  # fmt: skip


def _simple_statements(function: ast.AST) -> list[ast.stmt]:
    """*function*'s statements that hold no nested block, in source order."""
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    found = [
        sub
        for sub in ast.walk(function)
        if isinstance(sub, ast.stmt) and not isinstance(sub, nested) and not isinstance(sub, _BLOCK_STATEMENTS)
    ]
    return sorted(found, key=lambda sub: (sub.lineno, sub.col_offset))


def _function_doors(function: ast.AST) -> list[int]:
    """Lines in *function* where ONE statement both reaches an output root and writes code there.

    A name assigned from an output-reaching expression carries the output root on (``tree = output_dir(..)``
    then ``git('worktree', 'add', str(tree))``); a statement making ``output/`` beside an unrelated ``code.py``
    is not a door.
    """
    tainted: set[str] = set()
    lines = []
    for stmt in _simple_statements(function):
        reaches = _reaches_output(stmt, tainted)
        if reaches and _writes_code(stmt):
            lines.append(stmt.lineno)
        if reaches and isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            tainted |= {t.id for target in targets for t in ast.walk(target) if isinstance(t, ast.Name)}
    return lines


def code_doors_into_output(source: str) -> list[int]:
    """Line numbers of the statements in *source* that write code, a bundle or a checkout under ``output/``."""
    return [
        line
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for line in _function_doors(node)
    ]
