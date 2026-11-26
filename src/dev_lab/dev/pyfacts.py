"""Per-file static facts of a checkout's Python, read in one pass and cached by stat: what a file uses and forwards.

OWNER-DAG (:mod:`dev_lab.dev.ownerdag`) needs every dotted name a file uses; NO-DETOUR (:mod:`dev_lab.dev.passthrough`)
needs whether a module only forwards, and to what. Both are functions of the file's CONTENT alone, so one
:func:`dev_lab.dev.importedges.read` per file answers both, and :func:`facts` keeps them in a journal in the
checkout's own git dir (``dev-lab/pyfacts.json``) keyed by each file's size and mtime and by :data:`VERSION`: a
changed file is re-read, and a journal that cannot be read or written costs a full read, never a verdict. Measured
2026-11-25 over dev-lab's 1366 tracked files, both checks: 42 s with two walks per file and no journal; 7.6 s cold
and 1.0 s warm with one walk and the journal (a cached file is one ``stat``).

A FORWARD (:func:`forwards`) is an undecorated top-level public function whose body (docstring aside) is one
``return f(...)`` or ``f(...)`` (``await`` allowed), ``f`` an imported name or an attribute of one, passing exactly
the function's own parameters unchanged (positionally in order or by keyword, ``*args``/``**kwargs`` through). A
module ONLY forwards when it has at least one public function, each is a forward, and nothing else is public -- a
public class or assignment, or any statement but imports, a docstring and a ``TYPE_CHECKING`` block, adds something.
A file that does not parse is a fact too (:attr:`Facts.error`): its imports cannot be judged, so it is never clean.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev_lab.dev import gitdirs, importedges

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['VERSION', 'Facts', 'facts', 'forwards']

#: Bump when what a fact means changes: every journaled fact of an older version is re-read.
VERSION: Final = 2  # 2: a builtin read and never bound is a use, builtins.<name>
_JOURNAL: Final = ('dev-lab', 'pyfacts.json')


@dataclass(frozen=True, slots=True)
class Facts:
    """One file: every dotted name it uses, what it only forwards to (``None``: it adds something), a parse error."""

    uses: frozenset[str]
    forwards: tuple[tuple[str, str], ...] | None
    error: str | None = None


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _is_type_checking(stmt: ast.stmt) -> bool:
    test = stmt.test if isinstance(stmt, ast.If) else None
    return (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
        isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'
    )


def _callee(func: ast.expr, bound: dict[str, str]) -> str | None:
    chain: list[str] = []
    while isinstance(func, ast.Attribute):
        chain.append(func.attr)
        func = func.value
    return '.'.join([bound[func.id], *reversed(chain)]) if isinstance(func, ast.Name) and func.id in bound else None


def _same_args(fn: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call) -> bool:
    """Whether *call* passes exactly *fn*'s parameters, each unchanged and once."""
    a = fn.args
    positional = [p.arg for p in (*a.posonlyargs, *a.args)]
    plain = [x for x in call.args if not isinstance(x, ast.Starred)]
    if call.args[: len(plain)] != plain or not all(isinstance(x, ast.Name) for x in plain):
        return False
    if [x.id for x in plain if isinstance(x, ast.Name)] != positional[: len(plain)]:
        return False
    starred = call.args[len(plain) :]
    stars = [s.value.id if isinstance(s, ast.Starred) and isinstance(s.value, ast.Name) else None for s in starred]
    if stars != ([a.vararg.arg] if a.vararg else []):
        return False
    named, spread = [], []
    for kw in call.keywords:
        if not isinstance(kw.value, ast.Name) or (kw.arg is not None and kw.arg != kw.value.id):
            return False
        (named if kw.arg is not None else spread).append(kw.value.id)
    wanted = positional[len(plain) :] + [p.arg for p in a.kwonlyargs]
    return sorted(named) == sorted(wanted) and spread == ([a.kwarg.arg] if a.kwarg else [])


def _forward(fn: ast.FunctionDef | ast.AsyncFunctionDef, bound: dict[str, str]) -> str | None:
    """The absolute name *fn* only forwards to, else ``None``."""
    body = fn.body[1:] if fn.body and _is_docstring(fn.body[0]) else fn.body
    if fn.decorator_list or len(body) != 1 or not isinstance(body[0], ast.Return | ast.Expr):
        return None
    value = body[0].value
    value = value.value if isinstance(value, ast.Await) else value
    return _callee(value.func, bound) if isinstance(value, ast.Call) and _same_args(fn, value) else None


def _private_assignment(stmt: ast.stmt) -> bool:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
    names = [t.id for t in targets if isinstance(t, ast.Name)]
    return bool(names) and len(names) == len(targets) and all(n.startswith('_') for n in names)


def forwards(tree: ast.Module, bound: dict[str, str]) -> tuple[tuple[str, str], ...] | None:
    """``(public function, what it forwards to)`` for a module that ONLY forwards, else ``None``."""
    out: list[tuple[str, str]] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Import | ast.ImportFrom) or _is_docstring(stmt) or _is_type_checking(stmt):
            continue
        if _private_assignment(stmt):
            continue
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and stmt.name.startswith('_'):
            continue
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and (target := _forward(stmt, bound)):
            out.append((stmt.name, target))
            continue
        return None
    return tuple(out) or None


def _read(root: Path, rel: str) -> Facts:
    path = root / rel
    try:
        reading = importedges.read(
            path.read_text(encoding='utf-8'), importedges.module_name(root, path), is_package=path.name == '__init__.py'
        )
    except (SyntaxError, ValueError, ImportError) as exc:
        return Facts(frozenset(), None, f'{type(exc).__name__}: {exc}')
    return Facts(reading.uses, forwards(reading.tree, reading.bound))


def _encode(one: Facts) -> list[object]:
    return [sorted(one.uses), [list(f) for f in one.forwards] if one.forwards is not None else None, one.error]


def _decode(raw: list) -> Facts:
    uses, fwd, error = raw
    return Facts(frozenset(uses), tuple((str(a), str(b)) for a, b in fwd) if fwd is not None else None, error)


def facts(root: Path, rels: Iterable[str]) -> dict[str, Facts]:
    """:class:`Facts` of each repo-relative ``.py`` file of *rels* under *root*, from the journal where unchanged."""
    own = gitdirs.git_dir(root) if (root / '.git').exists() else None  # only a checkout root keeps a journal
    journal = None if own is None else own.joinpath(*_JOURNAL)
    try:
        data = json.loads(journal.read_text(encoding='utf-8')) if journal is not None else {}
    except (OSError, ValueError):
        data = {}
    before = data.get('files', {}) if isinstance(data, dict) and data.get('version') == VERSION else {}
    out: dict[str, Facts] = {}
    after: dict[str, list] = {}
    for rel in rels:
        try:
            stat = (root / rel).stat()
        except OSError:
            continue
        key = [stat.st_size, stat.st_mtime_ns]
        cached = before.get(rel)
        one = _decode(cached[1]) if isinstance(cached, list) and cached[0] == key else _read(root, rel)
        out[rel], after[rel] = one, [key, _encode(one)]
    if journal is not None and after != before:
        try:
            journal.parent.mkdir(parents=True, exist_ok=True)
            tmp = journal.with_suffix('.tmp')
            tmp.write_text(json.dumps({'version': VERSION, 'files': after}), encoding='utf-8')
            tmp.replace(journal)
        except OSError:
            pass  # a journal is a cache: an unwritable one costs the next judgment a full read, never a verdict
    return out
