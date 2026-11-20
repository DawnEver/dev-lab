"""The corpus every architecture guard in this repo reads, and the floor each one binds.

WHY THIS FILE EXISTS RATHER THAN A GLOB IN EACH GUARD. A guard that walks the tree itself answers
"how many files did you read?" with a number nobody checks, and a scan that reached nothing is
indistinguishable from a tree with nothing wrong in it. Every guard here takes its file list from
this module and hands the count to :func:`assert_floor`, so the vacuous-green shape has exactly one
place to be refused instead of one per guard.

TRACKED RATHER THAN MERELY PRESENT, for the reason `dev_lab.dev.rules.tracked_files` gives: a
file that exists only in one working copy is not a file the fleet has, so a guarantee resting on it
is a guarantee nobody else can reproduce. A tracked path that is missing from the working tree is
DROPPED rather than read -- that is a fact about this checkout, not about the repo -- and the floor
is what keeps that drop from turning into an empty scan nobody notices.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Final

from dev_lab.dev.datedlog import declared_output
from dev_lab.dev.rules import tracked_files

#: The repo root: this file is ``<root>/tests/_arch_corpus.py``.
ROOT: Final = Path(__file__).resolve().parents[1]

#: Floors, MEASURED 2026-09-15 (22 tracked modules under ``src/``, 22 test modules). Set below the
#: measurement on purpose: a floor is a refusal of an UNREAD tree, not a second pin on the count --
#: pinning the exact number would red on every file added, which is how a floor gets deleted.
SOURCE_FLOOR: Final = 18
TEST_FLOOR: Final = 18

#: The memory tree's floor, and it is ONE on purpose. The other two floors sit under a measured
#: count; this one sits at the smallest number that still refuses the failure it exists for -- a
#: `.claude/memory/` that is empty or absent, where a shape guard passes because it read nothing.
#: The tree holds 1 entry (MEASURED 2026-09-15, the day it was created), so a floor above 1 would be
#: a pin on growth rather than a refusal of an unread tree.
MEMORY_FLOOR: Final = 1


class VacuousScan(AssertionError):
    """A scan reached fewer files than the floor, so finding nothing proves nothing."""


def assert_floor(reached: int, floor: int, what: str) -> None:
    """Refuse a scan that read fewer than *floor* files -- naming what it was scanning."""
    if reached < floor:
        msg = (
            f'the {what} scan reached only {reached} files, below the {floor} floor. Finding NOTHING '
            f'is vacuous rather than green: a clean tree and an unread one are the same empty result, '
            f'and only one of them means the guard held. Fix the corpus, do not lower the floor.'
        )
        raise VacuousScan(msg)


@lru_cache(maxsize=1)
def _tracked() -> tuple[str, ...]:
    return tuple(sorted(tracked_files(ROOT)))


def _existing(names: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(ROOT / name for name in names if (ROOT / name).is_file())


def source_modules() -> tuple[Path, ...]:
    """Every tracked ``.py`` under ``src/`` that is present in this working tree."""
    return _existing(tuple(n for n in _tracked() if n.startswith('src/') and n.endswith('.py')))


def suite_modules() -> tuple[Path, ...]:
    """Every tracked ``.py`` under ``tests/`` that is present in this working tree."""
    return _existing(tuple(n for n in _tracked() if n.startswith('tests/') and n.endswith('.py')))


def rules_pages() -> tuple[Path, ...]:
    """Every tracked markdown page under ``.claude/rules/`` -- this repo's always-loaded prose."""
    return _existing(tuple(n for n in _tracked() if n.startswith('.claude/rules/') and n.endswith('.md')))


def docs_pages() -> tuple[Path, ...]:
    """Every tracked markdown page under ``docs-src/`` -- the developer and user documentation."""
    return _existing(tuple(n for n in _tracked() if n.startswith('docs-src/') and n.endswith('.md')))


def memory_entries() -> tuple[Path, ...]:
    """Every tracked markdown entry under ``.claude/memory/`` -- this repo's durable findings.

    TRACKED rather than present, and here the distinction has teeth: the memory system writes
    device-local bookkeeping (a `_meta.json` per directory, a `__pycache__`) beside the records, and
    none of it reaches another checkout or a reader. Taking the corpus from git drops that debris
    without an exemption list, while a real fork -- an entry written outside a dated directory and
    committed -- is exactly what stays in scope.
    """
    return _existing(tuple(n for n in _tracked() if n.startswith('.claude/memory/') and n.endswith('.md')))


def rel(path: Path) -> str:
    """*path* as a repo-relative POSIX string -- the spelling every refusal message uses."""
    return path.relative_to(ROOT).as_posix()


def corpus_key(path: Path) -> str:
    """*path*'s key in a finding: :func:`rel` inside the checkout's code, the bare name for a planted file.

    A planted file lives in pytest's temp dir, which is under the checkout's declared output tree
    (``dev_lab.dev.testtemp``) -- program output, never code -- so that tree counts as outside.
    """
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) and not resolved.is_relative_to(ROOT / declared_output(ROOT)):
        return rel(resolved)
    return path.name


def parse(path: Path) -> ast.Module:
    """*path* as an AST. A file that does not parse is a failure, never a file that is skipped."""
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def bound_names(body: list[ast.stmt]) -> set[str]:
    """Every MODULE-LEVEL name a module binds -- by def, class, assignment or import.

    Module level rather than :func:`ast.walk`, because a local variable inside a function is not a
    name a consumer can import: counting one would let a lying ``__all__`` resolve against it.
    """
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update((a.asname or a.name).split('.')[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            # ``type Row = ...`` (PEP 695) binds a module-level name a consumer imports and
            # annotates with. MEASURED 2026-09-17 on ``dev.shards.Row``: omitting this convicted a
            # TRUE ``__all__`` entry. The blind spot ran in that direction only -- it manufactured a
            # lie where there was none, never the reverse -- so nothing already declared was wrong.
            names.add(node.name.id)
        elif isinstance(node, ast.If | ast.Try | ast.With):
            # A module-level ``with`` (an import guard, e.g. dep's commonsfloor) binds its body at module level.
            names |= bound_names(node.body)
            names |= bound_names(getattr(node, 'orelse', []))
            if isinstance(node, ast.Try):
                names |= bound_names(node.finalbody)
                for handler in node.handlers:
                    names |= bound_names(handler.body)
    return names


def module_names(module: ModuleType) -> set[str]:
    """Every name *module*'s SOURCE binds at module level -- how a test pins a deleted name absent.

    Read from the source, not the live namespace: ``vars(module)`` is reflection (NO-REFLECTION), and a
    deleted function is a fact about the file -- its ``def`` and its imports -- which the AST states directly.
    """
    if module.__file__ is None:
        msg = f'{module.__name__} has no source file, so its bound names cannot be read'
        raise AssertionError(msg)
    return bound_names(parse(Path(module.__file__)).body)
