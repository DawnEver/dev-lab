"""HAS THE FAMILY ALREADY EXPRESSED THIS? -- the question a placement roster does not ask.

A roster row's side comes from a DENSITY bar, which answers *is this file mostly generic?*. That is
a good question and a DIFFERENT one from *has this already landed upstream?*, and nothing read a
roster against what :mod:`lab_commons.dev` publishes. MEASURED 2026-09-17 across three tranches of
motronics-studio's roster: **17 rows declared MOVES, 7 were real** -- the rest were 5 SPLITS and 5
rows whose subject was already in the kit. The error ran one way every time, because a row goes
stale silently: nothing re-reads it after its subject lands.

THE WORST SHAPE, and the one this module is built for: ``scripts/repo/worktree_debris.py`` imports
NOTHING and holds its own ``registered_worktrees``/``orphan_directories``/``stale_branches`` while
:mod:`lab_commons.dev.checkout` publishes a superset. A row reading "should move" and a row reading
"is a duplicate running today" were indistinguishable.

TWO DETECTORS OPEN A CASE, AND NAME OVERLAP IS NOT ONE OF THEM. That restraint is the design:

* PROVENANCE -- the kit module's own docstring NAMES the consumer path. It is a statement by the
  side that would know, and it caught every already-done row in the validation below. It is prose
  and can go stale, which is why it only OPENS a case rather than closing one.
* IMPORT -- the consumer file imports the kit module. Direct evidence of delegation, and blind to a
  live fork that imports nothing, so it cannot stand alone either.

:func:`coverage` is a RULER, never a detector. Two files may share a name and mean different things
-- this family measured 89% DIFFERENT content under one shared filename -- so a surface overlap with
no directional claim behind it is a name-matcher wearing a census's clothes. MEASURED here:
``scripts/repo/_symbol_coverage.py`` exports ``survey``, and so does :mod:`lab_commons.dev.checkout`,
which has nothing to do with it. Overlap GRADES a claim the two detectors have already opened.

THE ANSWER IS NOT A BOOLEAN, because PARTLY is the common case -- every SPLIT is in that shape. Six
grades, and the two that exist to REFUSE a verdict matter most:

* :data:`SUPERSEDED` -- provenance, and the kit covers the file's whole remaining surface.
* :data:`PARTIAL` -- provenance plus corroboration, and a REMAINDER that is named. The remainder IS
  the local half of the split, so a caller gets the seam rather than a percentage.
* :data:`NAMED_ONLY` -- the kit's prose names the file and NOTHING corroborates it: no shared name,
  no import. Added after MEASURING a false positive (``scripts/gate/runner.py``, named by
  :mod:`lab_commons.dev.verify`'s docstring as the tree it was carved from, sharing 0 of 51 names
  and importing it not at all). Stated as a correction rather than folded in, because a grade
  introduced after seeing the row it excludes has to say so.
* :data:`CONSULTS` -- imports the kit and no kit module claims it. Adoption, not supersession.
* :data:`UNTOUCHED` -- neither detector fires. The row is what it says it is.
* :data:`UNMEASURABLE` -- provenance fired and the file has NO public surface to rule, so there is
  nothing to grade. A file like that is decided by reading, and saying so beats scoring it zero.

EVERY REPO-SHAPED FACT ARRIVES AS AN ARGUMENT WITH NO DEFAULT -- which paths, which kit modules,
which floor. A default here would hand all four repos one repo's answer, which is the failure mode
``LAB_CZ_BASE_REF`` is the family's worked example of.

A LEADING UNDERSCORE IS NORMALISED AWAY ON BOTH SIDES, and this is a deliberate widener: a migration
routinely demotes a consumer's public helper to a kit private, and MEASURED on
``scripts/gate/_box.py`` -> ``bounded._available_gb`` that one character was the whole difference
between a full supersession and a false remainder. It widens the RULER, never the detectors.

THE FLOOR IS REQUIRED AND ZERO IS REFUSED. A census that read no rows, or no kit modules, reports
exactly what a fully migrated tree reports.

THE KIT IS READ AS SOURCE, NEVER IMPORTED. A census must be able to judge a kit version that is not
the one installed in the caller's environment, and executing the thing under measurement is how a
measurement acquires a side effect.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'CONSULTS',
    'ENTRY_NAMES',
    'FLAGGED',
    'IMPORT',
    'NAMED_ONLY',
    'PARTIAL',
    'PROVENANCE',
    'SUPERSEDED',
    'UNMEASURABLE',
    'UNTOUCHED',
    'Census',
    'Claim',
    'KitModule',
    'Row',
    'VacuousCensus',
    'coverage',
    'defined_names',
    'grade_row',
    'imported_kit_modules',
    'kit_modules',
    'named_paths',
    'public_names',
    'read_row',
    'take_census',
]

#: A name that is an INVOCATION rather than a mechanism. Every runnable script has one, so counting
#: it as un-superseded remainder would put a floor under every file's remainder for a reason that
#: says nothing about the migration. It is one entry, and widening it needs the same argument again.
ENTRY_NAMES = frozenset({'main'})

#: The two detectors, spelled once so a caller can branch on the EVIDENCE rather than on the grade.
PROVENANCE = 'provenance'
IMPORT = 'import'

SUPERSEDED = 'superseded'
PARTIAL = 'partial'
NAMED_ONLY = 'named_only'
CONSULTS = 'consults'
UNTOUCHED = 'untouched'
UNMEASURABLE = 'unmeasurable'

#: The grades that say the kit already holds this row's subject, in whole or in part. The two that
#: refuse a verdict and the two that say "still local" are deliberately NOT in here.
FLAGGED = frozenset({SUPERSEDED, PARTIAL})

#: How a docstring spells a file. Suffix-matched against a row's path, so a bare basename in the
#: kit's prose still reaches ``scripts/gate/bounded.py`` without matching an unrelated directory.
_FILE_TOKEN = re.compile(r'[\w./\\-]+\.(?:py|sh|ps1|toml|md)')

#: Strongest first. A row claimed by two kit modules is reported under the strongest claim, and the
#: order is data here so that adding a grade cannot silently reorder the two that refuse a verdict.
_STRENGTH = (SUPERSEDED, PARTIAL, UNMEASURABLE, NAMED_ONLY)


class VacuousCensus(AssertionError):
    """A census read fewer rows or kit modules than its floor, so finding nothing proves nothing."""


@dataclass(frozen=True)
class KitModule:
    """One upstream module: what its prose CLAIMS, and every name it defines at any visibility."""

    name: str
    claims: frozenset[str]
    universe: frozenset[str]


@dataclass(frozen=True)
class Row:
    """One roster row, read: its declared side, its public surface, and the kit modules it imports."""

    path: str
    side: str
    public: frozenset[str]
    imports: frozenset[str]


@dataclass(frozen=True)
class Claim:
    """What one row is, against the kit: the grade, the evidence for it, and the remainder."""

    path: str
    side: str
    kit_module: str | None
    detectors: tuple[str, ...]
    covered: tuple[str, ...]
    remainder: tuple[str, ...]
    grade: str

    @property
    def flagged(self) -> bool:
        """The row's subject is upstream, whole or in part -- so its declared side is stale."""
        return self.grade in FLAGGED


@dataclass(frozen=True)
class Census:
    """Every row judged, plus what the scan actually reached -- the two numbers the floor guards."""

    claims: tuple[Claim, ...]
    rows_read: int
    modules_read: int

    @property
    def flagged(self) -> tuple[Claim, ...]:
        """Only the rows whose subject the kit already holds."""
        return tuple(claim for claim in self.claims if claim.flagged)


def _normalise(names: Iterable[str]) -> frozenset[str]:
    """Strip leading underscores on both sides -- see the module docstring for why, and for the cost."""
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
    return _normalise(name for name in defined_names(tree) if not name.startswith('_')) - ENTRY_NAMES


def named_paths(docstring: str | None) -> frozenset[str]:
    """Every file path a docstring SPELLS -- the provenance claim, read rather than believed."""
    return frozenset(token.replace('\\', '/') for token in _FILE_TOKEN.findall(docstring or ''))


def imported_kit_modules(tree: ast.Module, *, package: str) -> frozenset[str]:
    """Which submodules of *package* this file imports, by either import form."""
    depth = len(package.split('.'))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == package:
                out.update(alias.name for alias in node.names)
            elif node.module.startswith(f'{package}.'):
                out.add(node.module.split('.')[depth])
        elif isinstance(node, ast.Import):
            out.update(a.name.split('.')[depth] for a in node.names if a.name.startswith(f'{package}.'))
    return frozenset(out)


def kit_modules(directory: Path) -> tuple[KitModule, ...]:
    """Read every public module under *directory* -- its prose claims and its defined universe."""
    out: list[KitModule] = []
    for path in sorted(directory.glob('*.py')):
        if path.name.startswith('_'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        out.append(
            KitModule(
                name=path.stem,
                claims=named_paths(ast.get_docstring(tree)),
                universe=_normalise(defined_names(tree)),
            )
        )
    return tuple(out)


def read_row(root: Path, path: str, side: str, *, package: str) -> Row:
    """Read one roster row off disk, under *root*, resolving its imports against *package*."""
    tree = ast.parse((root / path).read_text(encoding='utf-8'))
    return Row(path=path, side=side, public=public_names(tree), imports=imported_kit_modules(tree, package=package))


def coverage(row: Row, module: KitModule) -> tuple[frozenset[str], frozenset[str]]:
    """The ruler: which of the row's public names the kit module holds, and which it does not."""
    return row.public & module.universe, row.public - module.universe


def _claims_path(module: KitModule, path: str) -> bool:
    return any(path == t or path.endswith(f'/{t}') or path.rsplit('/', 1)[-1] == t for t in module.claims)


def grade_row(row: Row, modules: Iterable[KitModule]) -> Claim:
    """Judge one row against the kit -- pure over its arguments, so a planted control drives THIS."""
    best: Claim | None = None
    for module in modules:
        if not _claims_path(module, row.path):
            continue
        covered, remainder = coverage(row, module)
        detectors = (PROVENANCE, IMPORT) if module.name in row.imports else (PROVENANCE,)
        if not row.public:
            grade = UNMEASURABLE
        elif not remainder:
            grade = SUPERSEDED
        elif covered or IMPORT in detectors:
            grade = PARTIAL
        else:
            grade = NAMED_ONLY
        claim = Claim(
            path=row.path,
            side=row.side,
            kit_module=module.name,
            detectors=detectors,
            covered=tuple(sorted(covered)),
            remainder=tuple(sorted(remainder)),
            grade=grade,
        )
        if best is None or _STRENGTH.index(grade) < _STRENGTH.index(best.grade):
            best = claim
    if best is not None:
        return best
    consulted = sorted(row.imports & {module.name for module in modules})
    if consulted:
        return Claim(row.path, row.side, consulted[0], (IMPORT,), (), (), CONSULTS)
    return Claim(row.path, row.side, None, (), (), (), UNTOUCHED)


def _refuse_floor(floor: int, what: str) -> None:
    if floor <= 0:
        msg = f'a {what} floor of {floor} refuses nothing -- a floor of zero is the vacuity written down.'
        raise VacuousCensus(msg)


def take_census(
    rows: Mapping[str, str],
    modules: Iterable[KitModule],
    *,
    root: Path,
    package: str,
    row_floor: int,
    module_floor: int,
) -> Census:
    """Judge a whole roster. Every repo-shaped fact is an argument here, and no floor has a default.

    *rows* maps a repo-relative path to the side the roster declares for it. Both floors are refused
    at zero: a floor of zero is the vacuity written down, not a decision to permit it.
    """
    held = tuple(modules)
    _refuse_floor(row_floor, 'row')
    _refuse_floor(module_floor, 'kit module')
    if len(held) < module_floor:
        msg = (
            f'the census read {len(held)} kit modules, below the {module_floor} floor. Every row '
            f'reads UNTOUCHED against a kit nobody read, which is the answer a finished migration '
            f'gives. Fix the directory, do not lower the floor.'
        )
        raise VacuousCensus(msg)
    if len(rows) < row_floor:
        msg = (
            f'the census read {len(rows)} rows, below the {row_floor} floor. An empty roster and a '
            f'roster with nothing stale are the same empty result, and only one of them means the '
            f'census held. Fix the roster source, do not lower the floor.'
        )
        raise VacuousCensus(msg)
    claims = tuple(grade_row(read_row(root, path, side, package=package), held) for path, side in sorted(rows.items()))
    return Census(claims=claims, rows_read=len(claims), modules_read=len(held))
