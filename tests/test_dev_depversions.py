"""The controls for :mod:`lab_commons.dev.depversions` -- every reading, on files, in both directions.

WHY THIS FILE'S CENTRE OF GRAVITY IS THE READERS RATHER THAN THE PROBLEM FUNCTIONS. A problem
function that returned a sentence unconditionally would make every consumer red and be deleted; one
that returned ``None`` unconditionally would make every consumer green and be worthless. So each is
driven on BOTH sides of its boundary, and the boundaries are chosen where the arithmetic could go
wrong rather than where it is convenient: exactly at the age ceiling, on the future-dated row the
ceiling can never fire on, and on the package that is installed but whose lock records no version.

THE LAST ARM IS THE ONE THIS MODULE'S OWN DOCSTRING MAKES A CLAIM ABOUT, so it is checked rather than
asserted: the verdict reaches no network because the RUNTIME it calls imports no transport, and that
is an import graph rather than a promise. It is scanned with a planted control beside it, because a
scan that walks the wrong two files and a scan that walks the right two and finds nothing write the
same report.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import floors
from lab_commons.dev.depversions import (
    STALE_AFTER_DAYS,
    Exemption,
    Observed,
    Resolved,
    UnreadableState,
    environment_gap,
    exemption_problems,
    gap,
    installed_versions,
    read_observed,
    resolved_lock,
    staleness,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_ROOT = Path(__file__).resolve().parents[1]
_DAY = date(2026, 9, 21)

#: A committed baseline with one row of each kind. Planted as TEXT because the reader's subject is a
#: file a repo commits, and a fixture built from ``Observed`` objects would test the round trip this
#: file also tests rather than the shape a human writes by hand.
_BASELINE = """\
[observed.an-index-dep]
latest = "1.0.0"
observed_on = "2026-09-21"
kind = "index"
source = "an-index-dep"

[observed.a-remote-dep]
latest = "ffffffffffffffffffffffffffffffffffffffff"
observed_on = "2026-09-21"
kind = "remote"
source = "https://example.invalid/a-remote-dep.git"
"""

_LOCK = """\
version = 1
[[package]]
name = "an-index-dep"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "a-remote-dep"
version = "0.1.1"
source = { git = "https://example.invalid/a-remote-dep.git#aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }

[[package]]
name = "this-checkout"
version = "0.0.0"
source = { editable = "." }
"""

_REVISION = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'


def _observed(*, latest: str = '1.0.0', on: date = _DAY, kind: str = 'index', name: str = 'a-dep') -> Observed:
    """One row, spelled with every field a control needs to move exactly one of."""
    return Observed(name=name, latest=latest, observed_on=on, kind=kind, source=name)


def _locked(*, version: str = '1.0.0', identity: str = '1.0.0') -> Resolved:
    """One resolved row, with the version and the identity separable -- which is the whole point."""
    return Resolved(name='a-dep', version=version, identity=identity, source='registry:https://pypi.org/simple')


def test_a_committed_baseline_is_read_as_it_is_written(tmp_path: Path) -> None:
    """The shape a repo commits, read back with every field -- the reader's first contract."""
    path = tmp_path / 'observed.toml'
    path.write_text(_BASELINE, encoding='utf-8')
    rows = read_observed(path)
    assert sorted(rows) == ['a-remote-dep', 'an-index-dep']
    assert rows['an-index-dep'].kind == 'index'
    assert rows['a-remote-dep'].kind == 'remote'
    assert rows['a-remote-dep'].latest == 'ffffffffffffffffffffffffffffffffffffffff'
    assert rows['an-index-dep'].observed_on == _DAY


def test_an_absent_baseline_is_empty_and_an_unreadable_one_REFUSES(tmp_path: Path) -> None:
    """THE TWO SILENCES ARE DIFFERENT FACTS, and only one of them is safe to report as empty.

    An absent file means "this repo declares no baseline yet", which the consumer's floor refuses. A
    file that EXISTS and cannot be read means nobody read what is on disk, and returning an empty
    mapping for it is the vacuous green: it is indistinguishable from a baseline whose every package
    is up to date, and it stays that way until somebody opens the file.
    """
    assert read_observed(tmp_path / 'gone.toml') == {}
    broken = tmp_path / 'broken.toml'
    broken.write_text('this is not toml = = =\n', encoding='utf-8')
    with pytest.raises(UnreadableState, match='not readable TOML'):
        read_observed(broken)
    no_table = tmp_path / 'empty.toml'
    no_table.write_text('something_else = 1\n', encoding='utf-8')
    with pytest.raises(UnreadableState, match=r'no \[observed\] table'):
        read_observed(no_table)
    short = tmp_path / 'short.toml'
    short.write_text('[observed.a-dep]\nlatest = "1.0.0"\n', encoding='utf-8')
    with pytest.raises(UnreadableState, match='is incomplete'):
        read_observed(short)
    dated = tmp_path / 'dated.toml'
    dated.write_text(
        '[observed.a-dep]\nlatest = "1.0.0"\nkind = "index"\nsource = "a-dep"\nobserved_on = "yesterday"\n',
        encoding='utf-8',
    )
    with pytest.raises(UnreadableState, match='not an ISO date'):
        read_observed(dated)


def test_the_lock_resolves_two_identities_and_skips_what_is_not_a_dependency(tmp_path: Path) -> None:
    """A registry row is identified by its VERSION, a git row by its REVISION, and a local one by neither.

    The skip is asserted rather than assumed: the consumer's own project is always in the lock, and a
    reader that judged it against "the latest" would be asking a question about a package nobody
    publishes.
    """
    path = tmp_path / 'uv.lock'
    path.write_text(_LOCK, encoding='utf-8')
    rows = resolved_lock(path)
    assert sorted(rows) == ['a-remote-dep', 'an-index-dep']
    assert rows['an-index-dep'].identity == '1.0.0'
    assert rows['an-index-dep'].version == '1.0.0'
    assert rows['a-remote-dep'].identity == _REVISION
    assert rows['a-remote-dep'].version == '0.1.1'
    assert rows['a-remote-dep'].source == 'git:https://example.invalid/a-remote-dep.git'
    assert 'this-checkout' not in rows, 'an editable source is this checkout, not a dependency to track'


def test_an_absent_lock_is_empty_and_a_corrupt_one_REFUSES(tmp_path: Path) -> None:
    """Same two silences as the baseline, and the same refusal, because the repairs differ."""
    assert resolved_lock(tmp_path / 'uv.lock') == {}
    path = tmp_path / 'uv.lock'
    path.write_text('[[package]\nname = "a"\n', encoding='utf-8')
    with pytest.raises(UnreadableState, match='not readable TOML'):
        resolved_lock(path)


def test_the_gap_is_exact_string_equality_and_names_both_sides() -> None:
    """No ordering anywhere.

    The requirement is "not the latest, fail", and a comparator would be a second, unmeasured opinion
    about an ordering a PEP 440 version and a git revision do not share.
    """
    held = _observed(latest=_REVISION, kind='remote')
    assert gap('a-dep', _REVISION, held) is None
    sentence = gap('a-dep', 'b' * 40, held)
    assert sentence is not None
    assert 'b' * 40 in sentence, sentence
    assert _REVISION in sentence, sentence
    assert 'a-dep' in sentence
    assert gap('a-dep', '1.0.0', None) is not None, 'an uncovered package is a finding, not a pass'


def test_the_environment_arm_makes_no_claim_it_cannot_support() -> None:
    """Three absences and one comparison, so no claim is made that cannot be supported.

    A lock resolves for markers and platforms a box does not satisfy, so "not installed" is a fact
    about the box; and a lock that records no version has nothing to compare against, so inventing
    one would be the declaration that lies.
    """
    same = _locked(version='1.0.0')
    assert environment_gap('a-dep', '1.0.0', same) is None
    drift = environment_gap('a-dep', '0.9.0', same)
    assert drift is not None
    assert '0.9.0' in drift, drift
    assert '1.0.0' in drift, drift
    assert environment_gap('a-dep', None, same) is None, 'an absent install is not drift'
    assert environment_gap('a-dep', '0.9.0', _locked(version='')) is None, 'no version in the lock, no claim'


def test_the_age_ceiling_binds_at_the_boundary_and_a_future_date_is_refused() -> None:
    """The ceiling binds at its own number and a date nobody can check is refused.

    At the number the baseline holds; past it it reds; and a future stamp would hold the ceiling off
    for as long as it is wrong, so it is a finding rather than a young reading.
    """
    assert STALE_AFTER_DAYS == 7, 'the family ruling is 7 days; a different number here is a second opinion'
    for age in (0, 1, STALE_AFTER_DAYS):
        assert staleness(_DAY, _DAY + timedelta(days=age), ceiling_days=STALE_AFTER_DAYS) is None
    stale = staleness(_DAY, _DAY + timedelta(days=STALE_AFTER_DAYS + 1), ceiling_days=STALE_AFTER_DAYS)
    assert stale is not None
    assert 'past the 7-day ceiling' in stale, stale
    assert staleness(_DAY, _DAY + timedelta(days=1), ceiling_days=1) is None, 'a repo may name its own cadence'
    ahead = staleness(_DAY, _DAY - timedelta(days=3), ceiling_days=STALE_AFTER_DAYS)
    assert ahead is not None, 'a stamp in the future is a finding rather than a young reading'
    assert 'AFTER' in ahead, ahead


def test_the_exemption_census_is_two_sided_and_the_ceiling_is_on_the_set() -> None:
    """An escape hatch needs a ceiling, and four problems, one per way an exemption stops being a record.

    No reason, a passed review date, a name nobody tracks, and too many of them.
    """
    tracked = ('a-dep', 'b-dep', 'dropped')
    assert exemption_problems({}, tracked, today=_DAY, ceiling=2) == ()
    healthy = {'dropped': Exemption(reason='the vendor has not tagged since 2024', review_on=date(2026, 12, 1))}
    assert exemption_problems(healthy, tracked, today=_DAY, ceiling=2) == (), 'a clean waiver is left alone'
    unreasoned = {'dropped': Exemption(reason='   ', review_on=date(2026, 12, 1))}
    assert 'no reason recorded' in exemption_problems(unreasoned, tracked, today=_DAY, ceiling=2)[0]
    expired = {'dropped': Exemption(reason='a reason', review_on=date(2026, 1, 1))}
    assert 'which has passed' in exemption_problems(expired, tracked, today=_DAY, ceiling=2)[0]
    orphan = {'nobody-tracks-this': Exemption(reason='a reason', review_on=date(2026, 12, 1))}
    assert 'not a package this declaration tracks' in exemption_problems(orphan, tracked, today=_DAY, ceiling=2)[0]
    both = {'dropped': healthy['dropped'], 'dropped2': Exemption(reason='  ', review_on=date(2026, 12, 1))}
    problems = exemption_problems(both, tracked, today=_DAY, ceiling=1)
    assert 'the ceiling is 1' in problems[0], problems
    assert len(problems) == 3, problems


def test_the_environment_reading_invents_nothing() -> None:
    """A distribution that is here is answered, and one that is not is ABSENT rather than blank.

    The two are different repairs, and mapping the second to an empty string would merge them.
    """
    found = installed_versions(('structlog', 'lab-commons-nothing-installs-this'))
    assert 'structlog' in found
    assert found['structlog'].strip()
    assert 'lab-commons-nothing-installs-this' not in found


#: The modules whose whole claim is that a verdict can be taken without a network, named as data so
#: the scan reads a SET rather than a glob that could silently walk nothing.
NO_NETWORK_MODULES: tuple[str, ...] = (
    'src/lab_commons/dev/depversions.py',
    'src/lab_commons/dev/famtests/latestversions.py',
)

#: The stdlib roots a network verb arrives through, plus the two lab_commons modules that ARE one.
NETWORK_ROOTS = frozenset({'ftplib', 'http', 'socket', 'smtplib', 'subprocess', 'urllib'})
NETWORK_MODULES = frozenset({'lab_commons.dev.dep_observe', 'lab_commons.dev.netverb'})


def _runtime_imports(tree: ast.Module) -> set[str]:
    """Every module a file imports RUNTIME -- a ``TYPE_CHECKING`` import is a declaration, not a call."""
    found: set[str] = set()

    def visit(body: Sequence[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                # BOTH SPELLINGS, and the second is the one that matters: `from lab_commons.dev import
                # dep_observe` has module `lab_commons.dev` and the network module only in its NAMES,
                # so a scan reading the module alone could not see the seam it exists to guard.
                found.add(node.module)
                found.update(f'{node.module}.{alias.name}' for alias in node.names)
            elif isinstance(node, ast.If) and not _is_type_checking(node.test):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                visit(node.orelse)
                visit(node.finalbody)
                for handler in node.handlers:
                    visit(handler.body)

    visit(tree.body)
    return found


def _is_type_checking(test: ast.expr) -> bool:
    """Whether an ``if`` guards a typed-only import -- the one place a network NAME may be spelled."""
    return (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
        isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'
    )


def _network_reach(root: Path, paths: Sequence[str]) -> tuple[str, ...]:
    """Every runtime import under *root*/*paths* that could reach a network, as ``path: module``."""
    out: list[str] = []
    for relative in paths:
        tree = ast.parse((root / relative).read_text(encoding='utf-8'))
        out.extend(
            f'{relative}: imports {name}'
            for name in sorted(_runtime_imports(tree))
            if name.split('.')[0] in NETWORK_ROOTS or name in NETWORK_MODULES
        )
    return tuple(out)


def test_the_verdict_reaches_no_network_and_a_planted_reach_is_convicted(tmp_path: Path) -> None:
    """THE CLAIM THIS MODULE'S DOCSTRING MAKES, checked as an import graph rather than believed.

    ``famtests.upperbounds`` refuses a network call inside a blocking verdict in its own words, and
    the answer here is placement: the transports live in ``dep_observe``, the verdict takes a CALLER'S
    fetcher, and nothing on the verdict's path imports one. A scan that read the wrong two files and
    one that read the right two and found nothing write the same report, so the corpus is asserted to
    exist AND a module that really does import a transport is planted beside it.
    """
    read = tuple(relative for relative in NO_NETWORK_MODULES if (_ROOT / relative).is_file())
    floors.assert_floor(len(read), floor=2, what='verdict-path modules')
    floors.assert_floor_still_binds(len(read), floor=2, headroom=8, what='verdict-path modules')
    assert _network_reach(_ROOT, read) == (), (
        'a module on the verdict path imports a network verb. The verdict may CALL one through the '
        'fetcher it is handed, and it may not be one: an unanswered call has to be INCONCLUSIVE, and '
        'that is only checkable while the call is somebody else to make.'
    )
    planted = tmp_path / 'planted_net.py'
    planted.write_text('import urllib.request\nfrom lab_commons.dev import dep_observe\n', encoding='utf-8')
    assert _network_reach(tmp_path, ('planted_net.py',)) == (
        'planted_net.py: imports lab_commons.dev.dep_observe',
        'planted_net.py: imports urllib.request',
    )
    typed_only = tmp_path / 'typed_only.py'
    typed_only.write_text(
        'from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from lab_commons.dev import dep_observe\n',
        encoding='utf-8',
    )
    assert _network_reach(tmp_path, ('typed_only.py',)) == (), (
        'a TYPE_CHECKING import names a type and calls nothing; convicting it would make the seam '
        'unspellable in the one place a signature has to describe it.'
    )
