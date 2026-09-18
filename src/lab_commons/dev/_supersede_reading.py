"""HOW A FILE IS READ -- the AST half of :mod:`lab_commons.dev.supersede`, at its own seam.

THE KIT IS READ AS SOURCE, NEVER IMPORTED. A census must judge a kit version that is not the one
installed here, and executing the thing under measurement is how a measurement acquires a side
effect. Everything in this file is that reading: a path in, an :mod:`ast` walk, a frozenset out.
Nothing here grades, so nothing here has to know what a grade is.

WHY IT IS A FILE OF ITS OWN, and the seam is the one the neighbour's first sentence draws. Next door
asks *has the family already expressed this?* and answers it in seven grades; that question cannot
be asked until a file has been turned into a surface and a set of import tokens, and turning it into
those is a different job with a different failure mode -- next door fails by grading wrongly, this
file fails by SEEING NOTHING, which reads exactly like a clean tree. Both halves lived in one module
until it sat on the 400-line band, and the band is what made the seam get drawn rather than argued.

THE IMPORT READING IS SPELLING-SHAPED, and that is this file's whole hazard. One module can be named
by more than one import statement, :data:`IMPORT_SPELLINGS` is the declared set of them, and a
spelling the reader does not resolve costs NO RED anywhere: the IMPORT detector simply never fires
for the files that use it, and *nothing corroborated the claim* is a legal grade. MEASURED TWICE on
the same defect -- ``1aa2738`` closed ``from lab_commons.dev.famtests import allowguard`` and left
``from lab_commons.dev.famtests.citedtests import take_scan`` open, because the round trip that
should have caught it was driven with the spellings the fix had just taught the reader.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ._provenance import SUPERSEDES, provenance_rows

#: A name that is an INVOCATION rather than a mechanism. Every runnable script has one, so counting it
#: as remainder floors every file's remainder for a reason that says nothing about the migration.
ENTRY_NAMES = frozenset({'main'})

#: EVERY ABSOLUTE SPELLING that names one kit module, as format templates over a module's dotted path
#: -- its ``parent``, its ``stem``, the whole ``dotted`` path, and a ``name`` it binds. This is the
#: DECLARATION :func:`imported_kit_modules` is held to: `test_dev_supersede.py` crosses it with every
#: module :func:`kit_modules` publishes, so the function's claim to read "every spelling" is a thing
#: a test drives rather than a sentence. A spelling arrives here FIRST and the reader is made to meet
#: it; the third row is the one that was live and unread from 2026-09-17 to 2026-09-18.
#:
#: Relative imports are deliberately absent: a consumer is another repo and cannot spell this package
#: relatively, and a relative import inside the kit is not a consumer adopting anything.
IMPORT_SPELLINGS = (
    'import {dotted}',
    'from {parent} import {stem}',
    'from {dotted} import {name}',
)

#: The suffixes an AST can be taken of. Everything else is a row this instrument cannot READ, which
#: is a different answer from a row it read and found nothing in.
PYTHON_SUFFIXES = frozenset({'.py', '.pyi'})

#: How a docstring spells a file. Suffix-matched, so a bare basename still reaches its row's path.
_FILE_TOKEN = re.compile(r'[\w./\\-]+\.(?:py|sh|ps1|toml|md)')


@dataclass(frozen=True)
class KitModule:
    """One upstream module: what it CLAIMS -- prose or registry -- and every name it defines.

    *subpackage* is the directory it lives in below the kit root, empty for a top-level module. It is
    the fact that keeps the import reading inside its bound -- see :func:`imported_kit_modules` -- and
    it is filled by :func:`kit_modules` rather than declared, because it is a property of where the
    file WAS FOUND and not a decision a caller makes.
    """

    name: str
    claims: frozenset[str]
    universe: frozenset[str]
    subpackage: str = ''


@dataclass(frozen=True)
class Row:
    """One roster row, read: its declared side, its public surface, and the kit modules it imports.

    *readable* is false for a row no AST can be taken of -- a shell script, a config file. Such a row
    is still a row: it is counted and it grades ``UNREADABLE``, rather than crashing the census or,
    worse, reading as ``UNTOUCHED``.
    """

    path: str
    side: str
    public: frozenset[str]
    imports: frozenset[str]
    readable: bool = True


def normalise(names: Iterable[str]) -> frozenset[str]:
    """Strip leading underscores on both sides -- see :mod:`lab_commons.dev.supersede` for the cost."""
    return frozenset(stripped for name in names if (stripped := name.lstrip('_')))


def defined_names(tree: ast.Module) -> frozenset[str]:
    """Every name bound at a module's top level, at any visibility. ``__all__`` is plumbing, not one."""
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            out.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return frozenset(out - {'__all__'})


def public_names(tree: ast.Module) -> frozenset[str]:
    """A module's own public surface, normalised, with :data:`ENTRY_NAMES` removed."""
    return normalise(name for name in defined_names(tree) if not name.startswith('_')) - ENTRY_NAMES


def named_paths(docstring: str | None) -> frozenset[str]:
    """Every file path a docstring SPELLS -- the provenance claim, read rather than believed."""
    return frozenset(token.replace('\\', '/') for token in _FILE_TOKEN.findall(docstring or ''))


def _module_tokens(below: tuple[str, ...], subpackages: frozenset[str]) -> tuple[str, ...]:
    """THE BOUND: two segments below the package, the second only under a published sub-package.

    One segment is too few -- it answers ``famtests`` for every module in that package, a token no
    published module is named by. Every segment is too many, and that is the repair that switches
    off the guard it repairs: under a *package* one level short of the kit, ``lab_commons.dev.bounded``
    reads as two segments below ``lab_commons``, the second of which IS a published module name, so
    :func:`~lab_commons.dev.supersede._refuse_mismatch` sees a match and the wrong depth stops being
    refusable. Gating the second segment on membership tells those two cases apart by the only fact
    that separates them: ``famtests`` is a directory in the kit and ``dev`` is not.
    """
    if below[1:] and below[0] in subpackages:
        return below[:2]
    return below[:1]


def imported_kit_modules(tree: ast.Module, *, package: str, subpackages: frozenset[str]) -> frozenset[str]:
    """Every kit-module token this file's imports could name, by EVERY spelling in :data:`IMPORT_SPELLINGS`.

    That sentence is the declaration, and it is checked: the arm crossing the spellings with what
    :func:`kit_modules` publishes is what makes it a claim rather than prose. It used to read "by
    either import form" while a third form went unresolved for a day.

    The result is a CANDIDATE set and may over-emit -- sub-package tokens and imported function names
    are in it. That is only safe because a caller intersects it with what the kit actually published.

    Args:
        tree: the consumer file, parsed.
        package: the kit directory's OWN dotted path. One level short turns every
            ``lab_commons.dev.x`` into ``'dev'``, matching no kit module, so the IMPORT detector never
            fires and :func:`~lab_commons.dev.supersede.take_census` REFUSES it. No default.
        subpackages: the directory names the kit publishes modules under, from
            :func:`kit_subpackages`. No default: it is read off the kit under measurement, and an
            empty set is the correct answer for a flat kit rather than a missing argument.

    Returns:
        Every token an import in *tree* could be naming a kit module by.

    """
    depth = len(package.split('.'))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == package:
                out.update(alias.name for alias in node.names)
            elif node.module.startswith(f'{package}.'):
                below = tuple(node.module.split('.')[depth:])
                out.update(_module_tokens(below, subpackages))
                if not below[1:]:
                    out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f'{package}.'):
                    out.update(_module_tokens(tuple(alias.name.split('.')[depth:]), subpackages))
    return frozenset(out)


def _published(directory: Path) -> tuple[Path, ...]:
    """Every ``.py`` under *directory* with no private part in its relative path, sorted."""
    found = (p for p in directory.rglob('*.py') if not any(q.startswith('_') for q in p.relative_to(directory).parts))
    return tuple(sorted(found))


def kit_subpackages(directory: Path) -> frozenset[str]:
    """The directory names *directory* publishes modules under -- the bound's other half.

    Derived from the same walk :func:`kit_modules` does, so a sub-package cannot be published to one
    half of the pair and unknown to the other. That divergence IS the defect this argument closes.
    """
    return frozenset(path.relative_to(directory).parts[0] for path in _published(directory) if path.parent != directory)


def kit_modules(directory: Path) -> tuple[KitModule, ...]:
    """Every public module under *directory* AND its public sub-packages: claims, and the universe.

    RECURSIVE, because a census that reads one directory cannot see a module published one level
    down and reports the row it supersedes as UNTOUCHED -- which is how ``famtests.rulespages`` was
    missed. Only a :data:`~lab_commons.dev._provenance.SUPERSEDES` row joins the claims; an
    ``ADOPTED_BY`` row is a fact about a consumer that DELEGATES, which is the one thing a provenance
    claim must not be read as.
    """
    rows = provenance_rows(directory)
    out: list[KitModule] = []
    for path in _published(directory):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        row = rows.get(path.stem, ())
        declared = frozenset(row[1:]) if row[:1] == (SUPERSEDES,) else frozenset()
        out.append(
            KitModule(
                name=path.stem,
                claims=named_paths(ast.get_docstring(tree)) | declared,
                universe=normalise(defined_names(tree)),
                subpackage='' if path.parent == directory else path.relative_to(directory).parts[0],
            )
        )
    return tuple(out)


def read_row(root: Path, path: str, side: str, *, package: str, subpackages: frozenset[str]) -> Row:
    """Read one roster row off disk, under *root*, resolving its imports against *package*.

    A row whose file is not Python is NOT an error and NOT something a caller has to anticipate: it
    comes back unreadable. MEASURED 2026-09-17 -- a consumer's two shell rows raised ``SyntaxError``
    out of :func:`ast.parse` and had to be filtered by hand, and one of them was that repo's only
    MOVES row, so the census was blind to it by construction. A ``.py`` that will not parse still
    RAISES: that is a broken file in the tree under measurement, not a file of another kind.
    """
    if (root / path).suffix not in PYTHON_SUFFIXES:
        return Row(path=path, side=side, public=frozenset(), imports=frozenset(), readable=False)
    tree = ast.parse((root / path).read_text(encoding='utf-8'))
    return Row(
        path=path,
        side=side,
        public=public_names(tree),
        imports=imported_kit_modules(tree, package=package, subpackages=subpackages),
    )
