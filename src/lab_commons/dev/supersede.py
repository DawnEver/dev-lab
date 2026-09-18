"""HAS THE FAMILY ALREADY EXPRESSED THIS? -- the question a placement roster does not ask.

A roster row's side comes from a DENSITY bar, which answers *is this file mostly generic?*. That is
a good question and a DIFFERENT one from *has this already landed upstream?*, and nothing read a
roster against what :mod:`lab_commons.dev` publishes. MEASURED 2026-09-17 across three tranches of
motronics-studio's roster: **17 rows declared MOVES, 7 were real** -- the rest were 5 SPLITS and 5
rows whose subject was already in the kit. The error ran one way every time, because a row goes
stale silently: nothing re-reads it after its subject lands.

THE WORST SHAPE, and the one this module is built for: ``scripts/repo/worktree_debris.py`` imports
NOTHING and forks ``registered_worktrees``/``orphan_directories``/``stale_branches`` while
:mod:`lab_commons.dev.checkout` publishes a superset. "Should move" and "is a duplicate running
today" were indistinguishable.

TWO DETECTORS OPEN A CASE, AND NAME OVERLAP IS NOT ONE OF THEM. That restraint is the design:

* PROVENANCE -- the kit side NAMES the consumer path, in its docstring or in the
  :mod:`lab_commons.dev._provenance` registry, which is the half a module cannot silently forget.
  It is a statement by the side that would know, and only OPENS a case: prose goes stale.
* IMPORT -- the consumer file imports the kit module. Direct evidence of delegation, and blind to a
  live fork that imports nothing, so it cannot stand alone either.

:func:`coverage` is a RULER, never a detector, and the refusal survived being re-examined on the one
row that beat both detectors. Overlap convicts ``scripts/repo/_symbol_coverage.py`` (``survey``, also
:mod:`lab_commons.dev.checkout`'s, unrelated) and would still have MISSED that row, which shares 1 of
6 names with the module superseding it. Overlap GRADES a claim a detector has already opened.

THE ANSWER IS NOT A BOOLEAN, because PARTLY is the common case -- every SPLIT is in that shape.
Seven grades, and the three that exist to REFUSE a verdict matter most:

* :data:`SUPERSEDED` -- provenance, and the kit covers the file's whole remaining surface.
* :data:`PARTIAL` -- provenance plus corroboration, and a REMAINDER that is named. The remainder IS
  the local half of the split, so a caller gets the seam rather than a percentage.
* :data:`NAMED_ONLY` -- the kit names the file and NOTHING corroborates it: no shared name, no
  import. Added after MEASURING a false positive (``scripts/gate/runner.py``, named by
  :mod:`lab_commons.dev.verify` as the tree it was carved from, sharing 0 of 51 names).
* :data:`CONSULTS` -- imports the kit and no kit module claims it. Adoption, not supersession.
* :data:`UNTOUCHED` -- neither detector fires. The row is what it says it is.
* :data:`UNMEASURABLE` -- provenance fired and the file has NO public surface to rule, so there is
  nothing to grade. A file like that is decided by reading, and saying so beats scoring it zero.
* :data:`UNREADABLE` -- not a Python file, so no detector can see it. A shell row is a row; refusing
  a grade for it is the answer, and crashing on it or calling it UNTOUCHED are both worse.

EVERY REPO-SHAPED FACT ARRIVES AS AN ARGUMENT WITH NO DEFAULT -- which paths, which kit modules,
which floor -- since a default hands four repos one repo's answer (``LAB_CZ_BASE_REF``).
A LEADING UNDERSCORE IS NORMALISED AWAY ON BOTH SIDES: on ``_box.py`` -> ``bounded._available_gb``
that one character was a false remainder. It widens the RULER, never a detector. THE FLOOR IS
REQUIRED AND ZERO IS REFUSED: no rows, or no kit modules, reports what a finished migration reports.
So does a *package* that resolves onto nothing, and that is refused too.

THE KIT IS READ AS SOURCE, NEVER IMPORTED, and the READING is next door. A census must judge a kit
version that is not the one installed here, and executing the thing under measurement is how a
measurement acquires a side effect. :mod:`lab_commons.dev._supersede_reading` holds every AST walk
this module grades over -- :func:`kit_modules`, :func:`read_row`, :func:`imported_kit_modules` and
:data:`IMPORT_SPELLINGS`, re-exported here because the census IS the surface. The seam is that the
reading fails by SEEING NOTHING and the grading fails by judging wrongly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ._provenance import ADOPTED_BY, ORIGINAL, PROVENANCE_ROWS, SUPERSEDES, provenance_rows, undeclared_modules
from ._supersede_reading import (
    ENTRY_NAMES,
    IMPORT_SPELLINGS,
    KitModule,
    Row,
    defined_names,
    imported_kit_modules,
    kit_modules,
    kit_subpackages,
    named_paths,
    package_modules,
    public_names,
    read_row,
)

__all__ = [
    'ADOPTED_BY',
    'CONSULTS',
    'ENTRY_NAMES',
    'FLAGGED',
    'IMPORT',
    'IMPORT_SPELLINGS',
    'NAMED_ONLY',
    'ORIGINAL',
    'PARTIAL',
    'PROVENANCE',
    'PROVENANCE_ROWS',
    'SUPERSEDED',
    'SUPERSEDES',
    'UNMEASURABLE',
    'UNREADABLE',
    'UNTOUCHED',
    'Census',
    'Claim',
    'KitModule',
    'PackageMismatch',
    'Row',
    'VacuousCensus',
    'coverage',
    'defined_names',
    'grade_row',
    'imported_kit_modules',
    'kit_modules',
    'kit_subpackages',
    'named_paths',
    'package_modules',
    'provenance_rows',
    'public_names',
    'read_row',
    'take_census',
    'undeclared_modules',
]

#: The two detectors, spelled once so a caller branches on the EVIDENCE rather than on the grade.
PROVENANCE = 'provenance'
IMPORT = 'import'

SUPERSEDED = 'superseded'
PARTIAL = 'partial'
NAMED_ONLY = 'named_only'
CONSULTS = 'consults'
UNTOUCHED = 'untouched'
UNMEASURABLE = 'unmeasurable'
UNREADABLE = 'unreadable'

#: The grades saying the kit already holds this row's subject. The ones that refuse a verdict and the
#: ones that say "still local" are deliberately NOT in here.
FLAGGED = frozenset({SUPERSEDED, PARTIAL})

#: Strongest first, as data: a row claimed twice is reported under the strongest claim, and adding a
#: grade cannot silently reorder the ones that refuse a verdict.
_STRENGTH = (SUPERSEDED, PARTIAL, UNMEASURABLE, NAMED_ONLY)


class VacuousCensus(AssertionError):
    """A census read fewer rows or kit modules than its floor, so finding nothing proves nothing."""


class PackageMismatch(AssertionError):
    """Every import resolved to a token no kit module answers to, so the IMPORT detector was blind."""


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


def coverage(row: Row, module: KitModule) -> tuple[frozenset[str], frozenset[str]]:
    """The ruler: which of the row's public names the kit module holds, and which it does not."""
    return row.public & module.universe, row.public - module.universe


def _claims_path(module: KitModule, path: str) -> bool:
    return any(path == t or path.endswith(f'/{t}') or path.rsplit('/', 1)[-1] == t for t in module.claims)


def grade_row(row: Row, modules: Iterable[KitModule]) -> Claim:
    """Judge one row against the kit -- pure over its arguments, so a planted control drives THIS."""
    if not row.readable:
        return Claim(row.path, row.side, None, (), (), (), UNREADABLE)
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


def _refuse_mismatch(rows: tuple[Row, ...], names: frozenset[str], package: str) -> None:
    """A census whose imports NAME NOTHING in the kit is answering about the wrong package.

    THE FAIL-QUIET THIS CLOSES, this family's dominant defect inside the instrument built to find
    it: a wrong *package* does not raise, it reports zero CONSULTS, and that is exactly what a
    roster of live forks reports. MEASURED 2026-09-17, on this module's first consumer's first run.
    The test is ANY match, not every match -- a roster may legitimately import a private module or a
    sub-PACKAGE that :func:`kit_modules` publishes no row for. What cannot happen under a correct
    *package* is NOT ONE import landing on a kit module while imports exist.
    """
    seen = frozenset().union(*(row.imports for row in rows)) if rows else frozenset()
    if seen and not seen & names:
        msg = (
            f'the census resolved every kit import to {sorted(seen)}, and no module read from the kit '
            f'answers to any of those. `package={package!r}` is resolving at the wrong depth, so the '
            f'IMPORT detector never fires and the census reports zero CONSULTS -- which is what a '
            f"fully forked tree reports. Pass the kit directory's OWN dotted path."
        )
        raise PackageMismatch(msg)


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
    at zero: a floor of zero is the vacuity written down, not a decision to permit it. A *package*
    that resolves no import onto the kit is refused too -- see :func:`_refuse_mismatch`, and note
    that a refusal is the only safe answer there because the wrong one LOOKS like a clean result.

    The sub-packages the import reading is bounded by are DERIVED from *modules* rather than taken
    as a seventh argument: they are a fact about the kit that was read, and a caller free to declare
    them separately could declare a set the kit does not publish -- which is the wrong-depth failure
    arriving through the argument list instead of through *package*.
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
    subpackages = frozenset(module.subpackage for module in held if module.subpackage)
    read = tuple(
        read_row(root, path, side, package=package, subpackages=subpackages) for path, side in sorted(rows.items())
    )
    _refuse_mismatch(read, frozenset(module.name for module in held), package)
    claims = tuple(grade_row(row, held) for row in read)
    return Census(claims=claims, rows_read=len(claims), modules_read=len(held))
