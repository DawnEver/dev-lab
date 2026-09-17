"""What a test FILE declares about itself, read STATICALLY -- and a census built on those readings.

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
arrive as PREDICATES the caller supplies (:data:`Predicate`), and this module never learns a vendor
name, a directory prefix or a wall.

THE PARTITION IS FIRST-MATCH-WINS AND HAS A NAMED RESIDUAL. The whole point of a census like this is
the population that matched NOTHING -- the files that are in a slow tier because of where they sit
and for no reason any code can read. A partition with no residual bucket loses exactly that
population, so :func:`census` requires a name for it.

A READING IS A TUPLE AND NEVER A SET. A set answers WHICH and not HOW MANY, so a module holding one
waiver and one holding nine were a single value here -- and a per-file site COUNT is exactly what a
ceiling is: without one, a pinned module absorbs new waivers while the NAME set sits still.

A FLOOR IS MANDATORY, not a courtesy argument. A scan over an empty corpus reports the same clean
numbers as a scan over a healthy one, so :func:`collect` and :func:`census` both take a required
``floor`` and raise :class:`VacuousScanError` under it. Finding nothing must not be able to read as
green -- and a census is a MEASUREMENT, never a verdict: it counts, and the consuming repo's own
ratchets decide what the counts are allowed to be.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'Bucket',
    'Census',
    'FileFacts',
    'Predicate',
    'VacuousScanError',
    'call_names',
    'census',
    'collect',
    'count_test_functions',
    'mark_names',
    'pytest_files',
    'read_facts',
    'site_ledger',
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
