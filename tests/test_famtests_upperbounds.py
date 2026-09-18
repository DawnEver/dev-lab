"""The controls for :mod:`lab_commons.dev.famtests.upperbounds` -- both dialects, both policies.

THE ARM THAT CARRIES THIS FILE is the pair ``pyo3 = "0.29"`` and ``robust = "1.1"``: one spelling,
two meanings, and only the first is a ceiling. A reader that convicts both makes every Cargo manifest
in this family an offender; one that convicts neither is the state the rule was written to end. So
that pair is asserted directly rather than only inside the shipped control, and the PEP 508 reading
of a bare version is asserted beside it, because the two dialects disagree about exactly that token.

EVERY ARM IS DRIVEN ON A DOCTORED READER as well as a correct one and asserted to RED.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.upperbounds import (
    ECOSYSTEMS,
    POLICIES,
    BoundScan,
    UndeclaredUpperBound,
    UnreasonedWaiver,
    assert_no_undeclared_upper_bound,
    assert_the_reader_still_convicts,
    requirements,
    take_scan,
    upper_bounds,
)

_WHAT = 'LATEST-DEPENDENCIES'

_PYPROJECT = '[project]\ndependencies = ["numpy>=1.2", "bokeh~=3.8.0", "pandas"]\n'
_CARGO = '[dependencies]\npyo3 = "0.29"\nrobust = "1.1"\n'


def _bound(scan: BoundScan, **over: object) -> None:
    kwargs: dict[str, object] = {
        'policy': 'ban',
        'declared': {},
        'floor': 1,
        'headroom': 50,
        'requirement_floor': 1,
        'requirement_headroom': 500,
        'what': _WHAT,
    }
    assert_no_undeclared_upper_bound(scan, **(kwargs | over))  # type: ignore[arg-type]


def _names(text: str, ecosystem: str) -> set[str]:
    return {bound.name for bound in upper_bounds(text, ecosystem=ecosystem, manifest='m.toml')}


# -- THE DIALECT DISAGREEMENT, which is the whole reason this reads two ecosystems. -----------------


def test_one_cargo_spelling_means_two_things_and_only_the_zero_one_is_a_ceiling() -> None:
    """``0.29`` refuses the next minor and ``1.1`` does not, from the same three characters."""
    assert _names(_CARGO, 'cargo') == {'pyo3'}


@pytest.mark.parametrize(
    ('spec', 'bounded'),
    [
        ('0.29', True),
        ('^0.29', True),
        ('0.29.2', True),
        ('1.1', False),
        ('^1.1', False),
        ('1', False),
        ('>=1.0', False),
        ('~1.2', True),
        ('=1.2.3', True),
        ('<2', True),
        ('<=2', True),
    ],
)
def test_the_cargo_predicate_is_the_next_non_breaking_release(spec: str, *, bounded: bool) -> None:
    """A named table of spellings, so a case dropped from the reader is a row that disappeared."""
    text = f'[dependencies]\nc = "{spec}"\n'
    assert (_names(text, 'cargo') == {'c'}) is bounded, spec


@pytest.mark.parametrize(
    ('spec', 'bounded'),
    [
        ('', False),
        ('>=1.2', False),
        ('>1.2', False),
        ('<2', True),
        ('<=2', True),
        ('==8.0', True),
        ('~=3.8.0', True),
        ('!=0.5.0', True),
    ],
)
def test_the_pep508_predicate_reads_only_explicit_ceilings(spec: str, *, bounded: bool) -> None:
    """A bare version is not a specifier here, which is precisely where Cargo disagrees."""
    text = f'[project]\ndependencies = ["pkg{spec}"]\n'
    assert (_names(text, 'pep508') == {'pkg'}) is bounded, spec


def test_a_dialect_nobody_declared_is_refused_rather_than_guessed() -> None:
    """Both dialects return a plausible answer, so a misspelling must not silently select one."""
    with pytest.raises(ValueError, match='cargo'):
        requirements(_CARGO, ecosystem='crates')


def test_every_declared_dialect_has_a_working_control() -> None:
    """Parametrized over the NAMED SET, so a dialect dropped from ECOSYSTEMS is a hole with a name."""
    for ecosystem in sorted(ECOSYSTEMS):
        assert_the_reader_still_convicts(ecosystem=ecosystem)


# -- THE READER: optional and development tables, and a dependency with no version at all. ---------


def test_optional_and_development_requirements_are_read_too() -> None:
    """An extra installs into the same resolution, so a ceiling there binds exactly as hard."""
    text = '[project]\ndependencies = ["a"]\n[project.optional-dependencies]\ndev = ["b==1", "c>=1"]\n'
    assert {name for name, _ in requirements(text, ecosystem='pep508')} == {'a', 'b', 'c'}
    assert _names(text, 'pep508') == {'b'}
    cargo = '[dependencies]\na = "1"\n[dev-dependencies]\nb = "0.1"\n[build-dependencies]\nc = "2"\n'
    assert _names(cargo, 'cargo') == {'b'}


def test_a_path_dependency_has_no_version_and_so_is_never_a_bound() -> None:
    """The true answer rather than a convenient one: it is pinned by something this does not read."""
    text = '[dependencies]\nlocal = { path = "../local" }\n'
    assert requirements(text, ecosystem='cargo') == (('local', ''),)
    assert _names(text, 'cargo') == set()


def test_a_bound_says_how_it_is_one() -> None:
    """An invisible caret and an explicit operator are repaired differently, so the reason travels."""
    (caret,) = upper_bounds('[dependencies]\np = "0.29"\n', ecosystem='cargo', manifest='Cargo.toml')
    (operator,) = upper_bounds('[project]\ndependencies = ["p<2"]\n', ecosystem='pep508', manifest='pyproject.toml')
    assert 'breaking slot' in caret.why
    assert '<' in operator.why
    assert caret.manifest == 'Cargo.toml'


# -- THE POPULATIONS, and the silence each floor refuses. ------------------------------------------


def test_an_unparseable_manifest_is_skipped_rather_than_counted_as_read(tmp_path: Path) -> None:
    (tmp_path / 'broken.toml').write_text('[unclosed\n', encoding='utf-8')
    (tmp_path / 'ok.toml').write_text(_PYPROJECT, encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='pep508')
    assert scan.files_read == 1
    assert scan.requirements_seen == 3


def test_a_read_manifest_whose_table_was_renamed_is_refused_by_the_second_floor(tmp_path: Path) -> None:
    """THE SILENCE THE MANIFEST FLOOR CANNOT SEE: every file read, and no requirement in any of them."""
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='pep508')
    assert scan.files_read == 1, 'the manifest floor has nothing to complain about'
    with pytest.raises(floors.FloorUnmet, match='requirements'):
        _bound(scan, requirement_floor=3)


def test_an_unread_tree_is_refused_by_the_manifest_floor(tmp_path: Path) -> None:
    with pytest.raises(floors.FloorUnmet, match='manifests'):
        _bound(take_scan([], root=tmp_path, ecosystem='pep508'), floor=2)


def test_a_floor_the_population_outgrew_is_refused_on_the_other_side() -> None:
    with pytest.raises(floors.SlackFloor, match='manifests'):
        _bound(BoundScan(files_read=900, requirements_seen=9, bounds=()), floor=40, headroom=25)


# -- THE TWO POLICIES, neither of them the other's default. ----------------------------------------


def test_the_ban_policy_refuses_the_bound_and_its_waiver_list_alike(tmp_path: Path) -> None:
    """A ban with a waiver list is not a ban, and that is refused explicitly rather than ignored."""
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT, encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='pep508')
    with pytest.raises(UndeclaredUpperBound, match='bokeh'):
        _bound(scan, policy='ban')
    with pytest.raises(UndeclaredUpperBound, match='not a ban'):
        _bound(scan, policy='ban', declared={'bokeh': 'a reason'})


def test_the_declare_policy_accepts_a_reasoned_bound_and_refuses_an_unreasoned_one(tmp_path: Path) -> None:
    (tmp_path / 'Cargo.toml').write_text(_CARGO, encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='cargo')
    _bound(scan, policy='declare', declared={'pyo3': 'ABI-coupled with numpy; bump both together'})
    with pytest.raises(UnreasonedWaiver, match='no reason'):
        _bound(scan, policy='declare', declared={'pyo3': '   '})


def test_the_declare_policy_is_two_sided(tmp_path: Path) -> None:
    """A declaration outliving its bound is a waiver nothing uses, in the other direction."""
    (tmp_path / 'Cargo.toml').write_text('[dependencies]\nrobust = "1.1"\n', encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='cargo')
    with pytest.raises(UndeclaredUpperBound, match='NO LONGER BOUND'):
        _bound(scan, policy='declare', declared={'pyo3': 'gone'})


def test_a_policy_nobody_declared_is_refused() -> None:
    with pytest.raises(ValueError, match='ban'):
        _bound(BoundScan(files_read=1, requirements_seen=1, bounds=()), policy='strict')


def test_the_policies_are_a_named_set_and_both_are_exercised() -> None:
    assert set(POLICIES) == {'ban', 'declare'}


def test_a_clean_manifest_passes_under_both_policies(tmp_path: Path) -> None:
    """The green direction, because a guard that cannot pass is deleted rather than obeyed."""
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies = ["numpy>=1.2", "pandas"]\n', encoding='utf-8')
    scan = take_scan(sorted(tmp_path.glob('*.toml')), root=tmp_path, ecosystem='pep508')
    for policy in sorted(POLICIES):
        _bound(scan, policy=policy)


# -- THE SHIPPED CONTROL, driven on a doctored reader. ---------------------------------------------


def test_the_shipped_control_reds_when_the_caret_rule_is_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    """DOCTORED INPUT: a reader that knows only PEP 508 operators misses the invisible half entirely."""

    class _Blind:
        @staticmethod
        def match(_text: str) -> None:
            return None

    monkeypatch.setattr('lab_commons.dev.famtests._upperbounds_readings._CARET_ZERO', _Blind)
    with pytest.raises(AssertionError, match='planted ceilings'):
        assert_the_reader_still_convicts(ecosystem='cargo')


def test_the_shipped_control_reds_when_the_reader_convicts_every_caret(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opposite doctoring: convicting a bare 1.1 would make every Cargo manifest an offender."""
    monkeypatch.setattr(
        'lab_commons.dev.famtests._upperbounds_readings._why_bounded',
        lambda spec, *, ecosystem: 'everything is a bound' if spec.strip() else None,  # noqa: ARG005
    )
    with pytest.raises(AssertionError, match='planted ceilings'):
        assert_the_reader_still_convicts(ecosystem='cargo')
