"""Public-symbol coverage of one source tree against another, BY NAME. Knows no project.

Migrated 2026-09-17 from a consumer's ``scripts/repo/_symbol_coverage.py``. It moves whole: every
sentence below is about ``ast``, ``pathlib`` and arithmetic, and not one of them is about any
repository. What stays behind is the JUDGEMENT -- which two trees, which subpath of a checkout is
the library, how a tree divides into modules, and which absent names were never going to migrate.
Those are facts about one migration; walking two trees and counting which public definitions of the
first also exist in the second is true of any pair of Python trees.

NOTHING HERE NAMES A PACKAGE, A DIRECTORY OR A PRODUCT, and that is checked rather than asserted:
the arm at the end of this module's suite reads the SHIPPED file and refuses a project token in it,
with a length floor under the read so an empty file cannot pass as neutral. The original carried the
same claim as a sentence plus a note that an earlier draft had spelled two project names out in
order to disclaim them -- which is exactly why the claim needed a mechanism instead of a paragraph.

WHAT THE NUMBER MEANS, AND THE TWO WAYS IT CAN LIE TO ITS OWN AUTHOR. A match is a NAME appearing
anywhere under the target, so the reading is an upper bound on "this symbol is gone" and a lower
bound on "this symbol landed": a tree that renames on purpose undercounts, and a name that collides
with an unrelated definition overcounts. Neither is fixable here -- both are adjudications the
caller owns -- but they are the reason this module reports COUNTS AND NAMES rather than a percentage.

THE THREE IMPROVEMENTS OVER THE MIGRATED ORIGINAL, each because the original's own declaration went
further than its code:

* AN UNREADABLE FILE IS DATA. The original's :func:`read_module` counterpart wrote a line to
  ``stderr`` and returned ``None``, under a docstring saying such a file "IS REPORTED, never skipped
  in silence" -- and its survey then did ``continue``. So the denominator shrank anyway and the
  percentage rose, which is the one direction the docstring existed to forbid; a caller could not
  branch on a stream. :class:`Unreadable` is a value, both walks collect it, and
  :attr:`Coverage.complete` is what a caller reads. A warning on an unchanged success return is the
  forbidden shape, and the test is whether the caller can TELL.
* THE SAME HAZARD POINTS THE OTHER WAY ON THE TARGET SIDE and nothing named it: an unreadable file
  under the target shrinks the universe every name is looked up in, so symbols the tree really holds
  are reported ABSENT and the number reads as more work remaining. Both lists are carried.
* A BYTE THAT IS NOT UTF-8 IS NOT DECODED INTO SOMETHING ELSE. The prose scan read with
  ``errors='replace'``, which invents characters nobody wrote and then searches the invention. It is
  now an :class:`Unreadable` like any other.

WHERE THE FLOOR BELONGS, stated because putting it anywhere else is how this measurement went
vacuous before. :func:`symbols_under` and :func:`mentions` are READINGS: they answer what is there
and name what they could not read. :func:`survey` is the VERDICT, so it carries the floor -- and in
the original that floor lived in the CALLER, as an ``if not coverage.counted`` guard one caller
happened to write, which means any second caller reports ``0 of 0 = 100%`` over a tree that moved.
The floor is a REQUIRED KEYWORD with no default, because how many public symbols a tree ought to
hold is a fact about that tree and a default would hand every tree one tree's answer. A floor of
``0`` is REFUSED rather than honoured: it is the vacuity written down, not a decision to permit it.

An EMPTY TARGET is refused too, and it is a structural refusal rather than a threshold: every name
is absent against an empty universe, and that result says nothing about either tree.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lab_commons.dev.testfacts import VacuousScanError

__all__ = [
    'IGNORED_DIRECTORIES',
    'Coverage',
    'Mentions',
    'ModuleKey',
    'Symbols',
    'Unreadable',
    'definitions',
    'mentions',
    'python_files',
    'read_module',
    'survey',
    'symbols_under',
]

#: Directory names a Python source walk skips. A fact about PYTHON -- a ``__pycache__`` holds
#: generated mirrors of files already in the walk, so counting them doubles every symbol in the tree.
#: A caller may widen it for a vendored subtree, which is that caller's fact and arrives as an
#: argument rather than growing this set.
IGNORED_DIRECTORIES = frozenset({'__pycache__'})

#: How a source file is grouped for reporting. THE CALLER OWNS IT, because how a tree divides into
#: modules is a fact about that tree -- a top-level package name in one, a dated folder in another.
type ModuleKey = Callable[[Path], str]


@dataclass(frozen=True, slots=True)
class Unreadable:
    """One file the walk could not use, and why. A value, never a line on a stream."""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class Symbols:
    """Every public name defined under a tree, and what could not be read while finding them."""

    names: frozenset[str]
    unreadable: tuple[Unreadable, ...]

    @property
    def complete(self) -> bool:
        """Whether every file under the tree was read. An incomplete universe UNDER-reports matches."""
        return not self.unreadable


@dataclass(frozen=True, slots=True)
class Mentions:
    """Where each searched-for name is first written in a tree's TEXT, and what could not be read."""

    found: Mapping[str, str]
    unreadable: tuple[Unreadable, ...]

    @property
    def complete(self) -> bool:
        """Whether every file was searched. A name absent from an unread file is not absent."""
        return not self.unreadable


@dataclass(frozen=True, slots=True)
class Coverage:
    """Per-key counts, the names that did not match, and the floor the measurement cleared.

    FROZEN, because the original accumulated into a mutable counter the caller kept a handle on: a
    measurement a reader can still write to is not a measurement anyone downstream can cite.
    """

    total: Mapping[str, int]
    landed: Mapping[str, int]
    absent: Mapping[str, tuple[str, ...]]
    floor: int
    unreadable_source: tuple[Unreadable, ...] = field(default=())
    unreadable_target: tuple[Unreadable, ...] = field(default=())

    @property
    def counted(self) -> int:
        """The denominator: how many public source symbols were measured in all."""
        return sum(self.total.values())

    @property
    def matched(self) -> int:
        """The numerator: how many of them exist somewhere under the target."""
        return sum(self.landed.values())

    @property
    def complete(self) -> bool:
        """Whether BOTH trees were read whole. An incomplete survey's ratio is biased, not wrong-ish."""
        return not self.unreadable_source and not self.unreadable_target


def read_module(path: Path) -> ast.Module | Unreadable:
    """Parse *path*, or say why it could not be read.

    Strict UTF-8 on purpose: replacing undecodable bytes produces source nobody wrote, which then
    parses, and a reading of invented text is not a reading of the file.
    """
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        return Unreadable(path, f'{type(exc).__name__}: {exc}')
    try:
        return ast.parse(text)
    except SyntaxError as exc:
        return Unreadable(path, f'SyntaxError: {exc}')


def python_files(root: Path, *, ignore: frozenset[str] = IGNORED_DIRECTORIES) -> tuple[Path, ...]:
    """Every ``.py`` file under *root*, SORTED, with the ignored directory names pruned.

    Sorted because a walk whose order is the filesystem's makes "the first file that mentions it"
    a different answer on two machines holding identical trees.
    """
    return tuple(path for path in sorted(root.rglob('*.py')) if not ignore & set(path.parts))


def definitions(tree: ast.AST, *, top_level_only: bool) -> list[str]:
    """Every public class/function name in *tree*.

    *top_level_only* has NO DEFAULT because the two readings are the measurement's two sides and
    neither is the obvious one. ``True`` is the SOURCE side: a helper nested inside a function is
    not a public symbol anybody owes a migration for. ``False`` is the TARGET side: a migrated
    helper commonly lands as a method or a closure, and missing it undercounts the numerator while
    the denominator stays whole.
    """
    nodes = tree.body if top_level_only and isinstance(tree, ast.Module) else list(ast.walk(tree))
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return [node.name for node in nodes if isinstance(node, kinds) and not node.name.startswith('_')]


def symbols_under(root: Path, *, ignore: frozenset[str] = IGNORED_DIRECTORIES) -> Symbols:
    """Every public class/function name defined ANYWHERE under *root*, nested included."""
    names: set[str] = set()
    unreadable: list[Unreadable] = []
    for path in python_files(root, ignore=ignore):
        tree = read_module(path)
        if isinstance(tree, Unreadable):
            unreadable.append(tree)
            continue
        names.update(definitions(tree, top_level_only=False))
    return Symbols(frozenset(names), tuple(unreadable))


def survey(
    source: Path,
    target: Path,
    module_of: ModuleKey,
    *,
    floor: int,
    ignore: frozenset[str] = IGNORED_DIRECTORIES,
) -> Coverage:
    """Which public top-level symbols of *source* also exist somewhere under *target*.

    Args:
        source: the tree being measured; its module-level public definitions are the denominator.
        target: the tree a name must appear in, at any nesting depth, to count as present.
        module_of: groups a source file under a reporting key -- the caller's fact, not this one's.
        floor: the fewest public source symbols a real measurement finds. REQUIRED, and ``0`` is
            refused: a survey over a tree that moved must not answer a percentage about nothing.
        ignore: directory names pruned from both walks.

    Raises:
        VacuousScanError: the floor is not a floor, the source is below it, or the target defines no
            public names at all.

    """
    if floor < 1:
        msg = (
            f'a floor of {floor} is not a floor -- it is the vacuous result written down. State the '
            f'fewest public symbols this source tree holds when it is intact.'
        )
        raise VacuousScanError(msg)
    universe = symbols_under(target, ignore=ignore)
    if not universe.names:
        msg = (
            f'{target} defines no public names, so every source symbol would be reported absent and '
            f'the number would say nothing about either tree. This is a refusal, not 0 percent.'
        )
        raise VacuousScanError(msg)
    total: Counter[str] = Counter()
    landed: Counter[str] = Counter()
    absent: dict[str, list[str]] = {}
    unreadable: list[Unreadable] = []
    for path in python_files(source, ignore=ignore):
        tree = read_module(path)
        if isinstance(tree, Unreadable):
            unreadable.append(tree)
            continue
        key = module_of(path)
        for name in definitions(tree, top_level_only=True):
            total[key] += 1
            if name in universe.names:
                landed[key] += 1
            else:
                absent.setdefault(key, []).append(name)
    counted = sum(total.values())
    if counted < floor:
        msg = (
            f'{source} holds {counted} public top-level symbols, below the {floor} floor. Nothing '
            f'was measured, so there is no percentage to report -- check the tree, not the number.'
        )
        raise VacuousScanError(msg)
    return Coverage(
        total=dict(total),
        landed={key: landed[key] for key in total},
        absent={key: tuple(sorted(names)) for key, names in absent.items()},
        floor=floor,
        unreadable_source=tuple(unreadable),
        unreadable_target=universe.unreadable,
    )


def mentions(root: Path, names: frozenset[str], *, ignore: frozenset[str] = IGNORED_DIRECTORIES) -> Mentions:
    """The first file under *root* whose TEXT names each of *names*.

    NOT a definition scan -- :func:`symbols_under` answers that. This finds a name written in PROSE:
    a docstring recording where a module came from, a comment naming what it replaced, a test named
    after the thing it pins. A tree that talks about a symbol has said something about it, and that
    is the evidence a blanket "this was never going to migrate" has to survive.

    WHOLE-WORD MATCHING, so a short name cannot be dragged in by a longer one that contains it.

    Raises:
        VacuousScanError: *names* is empty. Asking about no names and being told none were found is
            a search that never happened, and it renders identically to a clean result.

    """
    if not names:
        msg = 'a mention scan over no names finds nothing and proves nothing; name what is being looked for.'
        raise VacuousScanError(msg)
    wanted = {name: re.compile(rf'\b{re.escape(name)}\b') for name in names}
    found: dict[str, str] = {}
    unreadable: list[Unreadable] = []
    for path in python_files(root, ignore=ignore):
        if not wanted:
            break
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(Unreadable(path, f'{type(exc).__name__}: {exc}'))
            continue
        for name in [name for name, pattern in wanted.items() if pattern.search(text)]:
            found[name] = path.as_posix()
            del wanted[name]
    return Mentions(found, tuple(unreadable))
