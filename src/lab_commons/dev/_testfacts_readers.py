"""One test FILE's declared facts, read from its AST -- the READING half of :mod:`~lab_commons.dev.testfacts`.

WHY STATIC, AND IT IS NOT A PERFORMANCE ARGUMENT. The question "which tests need a live engine, and
which are slow for a reason somebody wrote down" cannot be answered by collecting the suite:
collection IMPORTS every test module, and a module that discovers a live engine at import time
starts one. Measured in motronics-studio 2026-08-21: ``_MATLAB_READY`` is evaluated at module scope
under ``tests/unit/laplace/adapters/matlab/``, so a census that collects starts MATLAB to find out
whether a test starts MATLAB. That is not an instrument. So everything here comes from the AST and
NOTHING under the scanned tree is imported -- which also means the reading is safe to take from a
lane whose working tree does not import cleanly at all.

WHAT IS UNIVERSAL HERE, and what deliberately is not. A ``pytest.mark.<name>`` spelling, a
``pytest.mark.timeout(N)`` literal and a ``test_``-prefixed function are facts about PYTEST; every
repo in this family has them and they mean the same thing in each. Which marks name a live vendor,
which paths a tier claims, and what a tier's per-test wall is are facts about ONE repo -- so they
arrive as PREDICATES the caller supplies (:data:`Predicate`), and nothing here learns a vendor name,
a directory prefix or a wall.

A READING IS A TUPLE AND NEVER A SET. A set answers WHICH and not HOW MANY, so a module holding one
waiver and one holding nine were a single value here -- and a per-file site COUNT is exactly what a
ceiling is: without one, a pinned module absorbs new waivers while the NAME set sits still.

PRIVATE, AND THE SURFACE IS :mod:`lab_commons.dev.testfacts`. This is a split by SUBJECT: reading
one file is a complete question with its own argument, and the corpus, the ledger and the census
built ON those readings are another. Nothing here knows that a population exists. Consumers import
from ``testfacts``, which re-exports every name below, so no caller moves -- four repos import that
surface and none of them should learn where the seam fell.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'FileFacts',
    'Predicate',
    'VacuousScanError',
    'call_names',
    'count_test_functions',
    'mark_names',
    'read_facts',
    'timeout_ceilings',
]


#: A caller's question about one file, asked over the facts this module read for it. Every
#: repo-shaped decision -- vendor names, tier prefixes, walls -- lives in one of these and nowhere
#: here.
Predicate = Callable[['FileFacts'], bool]


class VacuousScanError(AssertionError):
    """A scan reached fewer files than its floor, so its clean numbers prove nothing."""


@dataclass(frozen=True, slots=True)
class FileFacts:
    """Everything one test file DECLARES about itself, and nothing inferred from where it sits.

    ``name`` is the caller's identifier for the file -- a repo-relative forward-slash path in every
    use so far. It is carried rather than derived because a consumer's tables and pins are keyed by a
    repo-relative path, and this module does not know which root to make it relative to.

    ``parse_error`` is a fact and not a failure: a file that does not parse is REPORTED as unreadable
    rather than dropped, because dropping it would shrink every population it belongs to.
    ``mark_uses`` and ``call_uses`` are TUPLES in source order: a ceiling is read from multiplicity.
    """

    name: str
    tests: int
    mark_uses: tuple[str, ...]
    call_uses: tuple[str, ...]
    ceilings_s: tuple[int, ...]
    parse_error: bool = False

    @property
    def marks(self) -> frozenset[str]:
        """WHICH spellings, DERIVED: a second field is a second answer, free to disagree."""
        return frozenset(self.mark_uses)

    @property
    def calls(self) -> frozenset[str]:
        """WHICH imperative verbs, DERIVED from :attr:`call_uses` for the same reason."""
        return frozenset(self.call_uses)

    def sites(self, *names: str) -> int:
        """HOW MANY TIMES *names* appear, as a decoration or a call -- what a set cannot hold.

        SUMMED: neither reading reaches the other's form, so nothing is double-counted or missed.

        Raises:
            ValueError: no name was asked about -- ``0`` over every corpus agrees with every claim.

        """
        if not names:
            msg = 'sites() needs at least one name: a count over no names is 0 for every file alive.'
            raise ValueError(msg)
        wanted = frozenset(names)
        return sum(1 for use in (*self.mark_uses, *self.call_uses) if use in wanted)

    @property
    def max_ceiling_s(self) -> int:
        """The largest declared ``timeout`` literal, or ``0`` when the file declares none.

        ``0`` rather than ``None`` because every caller compares it against a wall, and "no ceiling
        declared" and "a ceiling below the wall" are the same answer to that comparison: this file
        states no measured cost.
        """
        return max(self.ceilings_s) if self.ceilings_s else 0

    @property
    def directory(self) -> str:
        """The directory part of :attr:`name`, or ``''`` for a file at the root of the scan."""
        head, sep, _ = self.name.rpartition('/')
        return head if sep else ''


def mark_names(tree: ast.AST) -> tuple[str, ...]:
    """Every ``pytest.mark.<name>`` / ``mark.<name>`` spelling anywhere inside *tree*.

    BOTH SPELLINGS, because both are idiomatic and a scan that reads only the qualified one
    understates every file that did ``from pytest import mark``. Decorators, ``pytestmark``
    assignments and ``parametrize`` bodies are all reached, since the walk does not care WHERE the
    attribute access sits -- a mark applied by any route is still a mark the file declares.
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        if (isinstance(owner, ast.Attribute) and owner.attr == 'mark') or (
            isinstance(owner, ast.Name) and owner.id == 'mark'
        ):
            names.append(node.attr)
    return tuple(names)


def call_names(tree: ast.AST) -> tuple[str, ...]:
    """Every IMPERATIVE ``pytest.<verb>(...)`` call anywhere inside *tree*, in walk order.

    THE HALF A DECORATOR SCAN CANNOT SEE, and no lesser half: a waiver raised in a test BODY is a
    statement rather than a decoration and waives just as completely, so a scan reading only
    :func:`mark_names` reports a module clean while it skips at run time. A BARE ``<verb>(...)`` is
    read only when the file imported that name FROM pytest, which the tree STATES. The DECORATOR form
    is excluded BY SHAPE: a ``pytest.mark.skip(...)`` callee is owned by ``pytest.mark``, not pytest.
    """
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == 'pytest'
        for alias in node.names
    }
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in imported:
            names.append(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'pytest':
            names.append(func.attr)
    return tuple(names)


def timeout_ceilings(tree: ast.AST) -> tuple[int, ...]:
    """Every literal ``N`` in a ``...timeout(N)`` call -- the per-test ceilings the file declares.

    LITERALS ONLY, and the omission is deliberate: a ceiling computed from an expression is not a
    number this file states, and guessing one would put a figure on record that no author wrote.
    """
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == 'timeout' and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, (int, float)):
                out.append(int(first.value))
    return tuple(out)


def count_test_functions(tree: ast.AST) -> int:
    """How many ``test_``-prefixed functions the file defines, sync or async."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_')
    )


def read_facts(path: Path, *, name: str | None = None) -> FileFacts:
    """Read one file's declared facts. The file is PARSED, never imported.

    A file that does not parse comes back with ``parse_error=True`` and zeroed readings, so a caller
    can see it in the population it belongs to instead of silently losing it.
    """
    label = name if name is not None else path.name
    source = path.read_text(encoding='utf-8', errors='replace')
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return FileFacts(name=label, tests=0, mark_uses=(), call_uses=(), ceilings_s=(), parse_error=True)
    return FileFacts(
        name=label,
        tests=count_test_functions(tree),
        mark_uses=mark_names(tree),
        call_uses=call_names(tree),
        ceilings_s=timeout_ceilings(tree),
    )
