"""NO CONSUMER KEEPS ITS OWN PUSH-ADMISSION RULE -- it delegates to :mod:`lab_commons.dev.admission`.

THE DEFECT THIS REFUSES, measured 2026-10-04. Each repo carried its own citation body, its own
admitted-result table and its own reader of the verdict grammar, and they had drifted: one read the
FIRST verdict line and another the LAST, one admitted PASS and FAIL where the ruling of the day
admitted all three. A ruling that changes the table ("INCONCLUSIVE may be pushed") then lands in one
repo and not the others, which is the drift a single source exists to make impossible.

WHAT IS READ, by AST so a comment or docstring naming the old functions does not convict:

* a FUNCTION DEFINITION under one of :data:`REIMPLEMENTED` -- the names the local copies carried;
* a module- or class-level ASSIGNMENT of a literal tuple/set/frozenset holding both ``'PASS'`` and
  ``'FAIL'`` -- the shape of a local admission table;
* a ``re.compile`` whose pattern literal contains :data:`lab_commons.dev.admission.VERDICT_STAMP`'s
  ``tier=`` grammar -- a local reader of the verdict line.

WHAT THIS DOES NOT PROVE. A renamed function holding the same body, or a table built at runtime,
passes. The offender set is a lower bound, so the floor counts FILES READ.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

__all__ = [
    'REIMPLEMENTED',
    'AdmissionScan',
    'LocalAdmission',
    'assert_no_local_admission',
    'assert_the_scanner_still_convicts',
    'offenders_in',
    'take_scan',
]

#: The function names the local copies carried; defining one is keeping the copy.
REIMPLEMENTED: Final = frozenset(
    {
        'gate_citation',
        'lane_citation',
        'heavy_pass',
        'require_citable_pass',
        '_citable_pass_for_tier',
        'gate_verdict_decides',
        'parse_verdict_line',
    }
)

_PLANTED: Final = '''import re

_A_JUDGED_TREE = ('PASS', 'FAIL')
_LINE = re.compile(r'\\[verdict tree=(\\S+) env=(\\S+) tier=(\\S+)')


def lane_citation(root):
    """Named in prose: require_citable_pass -- prose never convicts."""
    return None


def honest(results=('PASS',)):
    words = ('PASS', 'FAIL')
    return words
'''

#: What the control requires the scanner to name in :data:`_PLANTED`, by line, and nothing else.
_PLANTED_LINES: Final = (3, 4, 7)


class LocalAdmission(AssertionError):
    """A consumer keeps its own admission table, citation body or verdict-line reader."""


@dataclass(frozen=True)
class AdmissionScan:
    """One walk: how many files were READ (the floor's number) and what was found."""

    files_read: int
    offenders: tuple[str, ...]


def _is_table(node: ast.expr) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'frozenset', 'set', 'tuple'}:
        node = node.args[0] if node.args else node
    if not isinstance(node, (ast.Tuple, ast.Set, ast.List)):
        return False
    words = {e.value for e in node.elts if isinstance(e, ast.Constant)}
    return {'PASS', 'FAIL'} <= words


def _is_reader(node: ast.Call) -> bool:
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == 'compile'):
        return False
    return any(
        isinstance(sub, ast.Constant) and isinstance(sub.value, str) and 'tier=' in sub.value
        for arg in node.args
        for sub in ast.walk(arg)
    )


def offenders_in(source: str) -> tuple[int, ...]:
    """The line numbers in *source* that keep a local admission rule."""
    tree = ast.parse(source)
    found: set[int] = set()
    scopes: list[ast.Module | ast.ClassDef] = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]
    for scope in scopes:
        for stmt in scope.body:
            value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
            if value is not None and _is_table(value):
                found.add(stmt.lineno)
    for node in ast.walk(tree):
        defines = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in REIMPLEMENTED
        if defines or (isinstance(node, ast.Call) and _is_reader(node)):
            found.add(node.lineno)
    return tuple(sorted(found))


def take_scan(root: Path, *, roots: Collection[tuple[str, str]], exempt: Collection[str] = ()) -> AdmissionScan:
    """Walk ``(directory, glob)`` pairs under *root*; *exempt* is root-relative posix paths."""
    read = 0
    offenders: list[str] = []
    for directory, pattern in roots:
        for path in sorted((root / directory).rglob(pattern)):
            rel = path.relative_to(root).as_posix()
            if rel in exempt or not path.is_file():
                continue
            read += 1
            offenders += [f'{rel}:{line}' for line in offenders_in(path.read_text(encoding='utf-8', errors='replace'))]
    return AdmissionScan(files_read=read, offenders=tuple(offenders))


def assert_no_local_admission(scan: AdmissionScan, *, floor: int) -> None:
    """THE CHECK, floor first so a walk that read nothing cannot read as clean."""
    floors.assert_floor(scan.files_read, floor=floor, what='local-admission')
    if scan.offenders:
        msg = (
            'push admission has ONE implementation, lab_commons.dev.admission (library and CLI '
            '`python -m lab_commons.dev.admission`). Delete the local copy and delegate:\n  '
            + '\n  '.join(scan.offenders)
        )
        raise LocalAdmission(msg)


def assert_the_scanner_still_convicts() -> None:
    """THE PLANTED CONTROL: the table, the reader and the body convict; prose and a lone PASS do not."""
    named = offenders_in(_PLANTED)
    if named != _PLANTED_LINES:
        msg = f'the scanner named lines {named} of the planted source, not {_PLANTED_LINES}'
        raise AssertionError(msg)
