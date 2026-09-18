"""A CORPUS of test files, a per-file site LEDGER, and a CENSUS -- over readings taken from the AST.

THE SURFACE, and the reading half lives next door. Every name
:mod:`lab_commons.dev._testfacts_readers` defines is re-exported here, so a consumer imports one
module and never learns where the seam falls. What THIS module adds is everything that needs a
POPULATION rather than a file: the glob that finds one, the floor that refuses an empty one, the
ledger that ratchets it and the census that cuts it.

A THIRD READING ARRIVED 2026-09-18 AND DID NOT MOVE THE SEAM. :func:`vacuous_test_functions` reads
an assertion SHAPE where the others read a DECLARATION, and it belongs on the same surface for the
reason this module's first sentence gives: what it publishes is "readings taken from the AST", and a
shape is one. :func:`mark_names` already reads a DECORATION and :func:`call_names` an imperative
CALL -- two syntactic forms of one question -- so a third form is not a fourth subject. What stays
here is what needs a POPULATION, and that is unchanged.

THE PARTITION IS FIRST-MATCH-WINS AND HAS A NAMED RESIDUAL. The whole point of a census like this is
the population that matched NOTHING -- the files that are in a slow tier because of where they sit
and for no reason any code can read. A partition with no residual bucket loses exactly that
population, so :func:`census` requires a name for it.

A FLOOR IS MANDATORY, not a courtesy argument. A scan over an empty corpus reports the same clean
numbers as a scan over a healthy one, so :func:`collect` and :func:`census` both take a required
``floor`` and raise :class:`VacuousScanError` under it. Finding nothing must not be able to read as
green -- and a census is a MEASUREMENT, never a verdict: it counts, and the consuming repo's own
ratchets decide what the counts are allowed to be.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lab_commons.dev._testfacts_readers import (
    FAILING_CONTEXTS,
    VACUOUS_ASSERT_METHODS,
    FileFacts,
    Predicate,
    VacuousScanError,
    call_names,
    count_test_functions,
    is_assertion,
    is_vacuous_assert,
    mark_names,
    read_facts,
    timeout_ceilings,
    vacuous_test_functions,
)

__all__ = [
    'FAILING_CONTEXTS',
    'VACUOUS_ASSERT_METHODS',
    'Bucket',
    'Census',
    'FileFacts',
    'Predicate',
    'VacuousScanError',
    'call_names',
    'census',
    'collect',
    'count_test_functions',
    'is_assertion',
    'is_vacuous_assert',
    'mark_names',
    'pytest_files',
    'read_facts',
    'site_ledger',
    'timeout_ceilings',
    'vacuous_test_functions',
]


def pytest_files(root: Path, *, subdir: str = 'tests', pattern: str = 'test_*.py') -> tuple[Path, ...]:
    """Every file matching *pattern* under ``root/subdir``, sorted. No floor: this is the raw glob.

    NOT NAMED ``test_files``, and the reason is not style: pytest COLLECTS any module-level callable
    whose name starts with ``test_``, so a consumer importing that spelling into a test module would
    have it collected as a test and error on a fixture called ``root``. A shared surface must not
    hand its importers a landmine.

    The floor belongs to :func:`collect`, which is where the result stops being a list of paths and
    starts being evidence.
    """
    return tuple(sorted((root / subdir).rglob(pattern)))


def collect(paths: Iterable[Path], *, root: Path, floor: int) -> tuple[FileFacts, ...]:
    """Read every path, naming each one relative to *root* with forward slashes.

    Args:
        paths: the files to read.
        root: what the names are relative to -- the key a consumer's own tables are written in.
        floor: the smallest number of files this scan may reach and still mean anything.

    Raises:
        VacuousScanError: fewer than *floor* files were reached.

    """
    facts = tuple(read_facts(path, name=path.relative_to(root).as_posix()) for path in paths)
    if len(facts) < floor:
        msg = (
            f'the test-file scan reached {len(facts)} files under {root}, below the {floor} floor. '
            f'An unread tree and a clean one produce the same counts, so this reading is refused '
            f'rather than reported. Fix the corpus -- do not lower the floor.'
        )
        raise VacuousScanError(msg)
    return facts


def site_ledger(facts: Iterable[FileFacts], *names: str) -> dict[str, int]:
    """Per-file site counts for *names*, in row order, omitting every file that holds none.

    A RATCHET WITH BOTH SIDES IN ONE READING. The KEYS are the named set -- a file that stops
    declaring a site leaves the ledger, so a declaration still naming it reds. The VALUES are the
    ceiling -- a file in the set absorbing one more moves the sum without moving a key, the half a
    named set is blind to. A clean file is ABSENT rather than zero, so the keys ARE the population.

    Raises:
        ValueError: no name was asked about -- see :meth:`FileFacts.sites`.

    """
    if not names:
        msg = 'site_ledger() needs at least one name: a ledger over no names is empty for every tree.'
        raise ValueError(msg)
    counts = ((row.name, row.sites(*names)) for row in facts)
    return {name: count for name, count in counts if count}


@dataclass(frozen=True, slots=True)
class Bucket:
    """One named part of a census, holding the FACTS rather than a count.

    The rows are kept so a caller can print the residual population by name. A bucket that carried
    only its totals would be a count pin: it cannot say WHICH file moved, which is the reading every
    consumer of this actually needs.
    """

    name: str
    rows: tuple[FileFacts, ...]

    @property
    def files(self) -> int:
        """How many files the scan read -- the floor that keeps a vacuous scan from reading green."""
        return len(self.rows)

    @property
    def tests(self) -> int:
        """How many tests the scan found across every file."""
        return sum(row.tests for row in self.rows)

    @property
    def names(self) -> tuple[str, ...]:
        """The file names, in row order, so a caller can name what was read."""
        return tuple(row.name for row in self.rows)

    def by_directory(self) -> dict[str, int]:
        """File counts per directory, most populous first -- where a residual concentrates."""
        return dict(Counter(row.directory for row in self.rows).most_common())


@dataclass(frozen=True, slots=True)
class Census:
    """A population, cut into named buckets, with everything unmatched kept as the last one."""

    scanned: Bucket
    population: Bucket
    buckets: tuple[Bucket, ...]

    def bucket(self, name: str) -> Bucket:
        """The bucket called *name*.

        Raises:
            KeyError: no bucket carries that name -- a lookup that silently returned an empty
                bucket would report a misspelled name as a clean population.

        """
        for item in self.buckets:
            if item.name == name:
                return item
        raise KeyError(name)

    def render(self) -> str:
        """The lines a caller prints: the scan, the population, then every bucket in cut order."""
        lines = [
            f'{self.scanned.name:<28}: {self.scanned.files:>6} files, {self.scanned.tests} test functions',
            f'{self.population.name:<28}: {self.population.files:>6} files, {self.population.tests} test functions',
        ]
        lines.extend(f'  {item.name:<26}: {item.files:>6} files, {item.tests} test functions' for item in self.buckets)
        return '\n'.join(lines)


def census(
    facts: Sequence[FileFacts],
    *,
    selects: Predicate,
    rules: Sequence[tuple[str, Predicate]],
    residual: str,
    floor: int,
    population: str = 'population',
    scanned: str = 'scanned',
) -> Census:
    """Cut the files *selects* claims into *rules*, FIRST MATCH WINS, keeping the rest in *residual*.

    Args:
        facts: what :func:`collect` read.
        selects: which files are in the population at all -- the consumer's tier claim.
        rules: ``(name, predicate)`` in cut order. First match wins, so a file with two reasons is
            counted under the first one rather than twice; a file counted twice would make the
            buckets sum to more than the population and quietly hide the residual.
        residual: the name for everything the rules did not claim. REQUIRED, because that population
            -- in the tier for no stated reason -- is what a census like this exists to find.
        floor: the smallest scan this may report on. See :func:`collect`.
        population: the label for the selected set.
        scanned: the label for everything read.

    Raises:
        VacuousScanError: fewer than *floor* files were handed in.
        ValueError: two rules share a name, which would make :meth:`Census.bucket` ambiguous.

    """
    if len(facts) < floor:
        msg = (
            f'the census was handed {len(facts)} files, below the {floor} floor. A census over an '
            f'empty corpus reports a clean partition of nothing.'
        )
        raise VacuousScanError(msg)
    names = [name for name, _ in rules]
    if len(set(names)) != len(names) or residual in names:
        msg = f'bucket names must be distinct, including the residual: {[*names, residual]}'
        raise ValueError(msg)
    claimed = tuple(row for row in facts if selects(row))
    grouped: dict[str, list[FileFacts]] = {name: [] for name in names}
    left: list[FileFacts] = []
    for row in claimed:
        for name, predicate in rules:
            if predicate(row):
                grouped[name].append(row)
                break
        else:
            left.append(row)
    buckets = tuple(Bucket(name, tuple(grouped[name])) for name in names)
    return Census(
        scanned=Bucket(scanned, tuple(facts)),
        population=Bucket(population, claimed),
        buckets=(*buckets, Bucket(residual, tuple(left))),
    )
