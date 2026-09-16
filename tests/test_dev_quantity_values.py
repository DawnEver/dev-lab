"""The value-half guard, driven through the REAL scanner against planted trees -- both directions.

THE CONTROL THAT MATTERS MOST here is not "a bare number is caught". It is
:func:`test_a_dimensionality_check_would_have_passed_the_angular_defect`, which PLANTS the check a
reasonable person would have written and shows it accepting the exact value this module exists to
refuse. A test that only demonstrates the guard working cannot tell a reader why the guard is
SHAPED this way, and the shape is the whole content of this module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.quantity_values import (
    QuantitySite,
    assert_value_floor,
    carries_a_unit,
    migration_conflicts,
    parse_quantity,
    scan_toml_values,
    value_ratchet,
    value_remedy,
)
from lab_commons.units import Q_

#: The registry shape a consumer hands in: key -> the unit its value must convert to.
_DECLARED = {'intra_slot_pitch': 'deg', 'stack_length': 'mm', 'phase_resistance': 'ohm'}


def _tree(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def test_a_bare_number_under_a_declared_key_is_refused(tmp_path: Path) -> None:
    """The defect in its commonest form: the suffix was deleted and the unit went with it."""
    planted = _tree(tmp_path, 'ring.toml', 'intra_slot_pitch = 1.5233427967\n')
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert [site.reason for site in scan] == ['bare-number']
    assert scan.keys_seen == {'intra_slot_pitch'}


def test_a_quantity_string_is_accepted(tmp_path: Path) -> None:
    """The remedy the user named -- the unit lives in the value, and pint can read it."""
    planted = _tree(tmp_path, 'ring.toml', "intra_slot_pitch = '1.5233427967 deg'\n")
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert not scan.violations
    assert scan.keys_seen == {'intra_slot_pitch'}


def test_a_dimensionality_check_would_have_passed_the_angular_defect() -> None:
    """THE REASON THE GATE IS ON UNITS AND NOT ON DIMENSIONALITY, planted rather than asserted.

    This is the check a reasonable person writes first. It is run here against the defect, and it
    ACCEPTS it -- which is why this module does not use it.
    """
    bare, proper = Q_('1.6'), Q_('1.6 deg')
    assert bare.dimensionality == proper.dimensionality, 'pint calls an angle dimensionless'
    assert bare.is_compatible_with('rad'), 'the obvious check passes the bare float'
    # And the gate this module actually uses separates them.
    assert not carries_a_unit('1.6')
    assert carries_a_unit('1.6 deg')


def test_a_string_pint_reads_as_dimensionless_is_refused(tmp_path: Path) -> None:
    """A string is not the point; a UNIT is. Quoting the float buys nothing and must not pass."""
    planted = _tree(tmp_path, 'ring.toml', "intra_slot_pitch = '1.5233427967'\n")
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert [site.reason for site in scan] == ['no-unit']


def test_a_unit_that_cannot_convert_to_the_declaration_is_refused(tmp_path: Path) -> None:
    """A real unit in the wrong dimension is a different defect and says so."""
    planted = _tree(tmp_path, 'ring.toml', "stack_length = '1.6 deg'\n")
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert [site.reason for site in scan] == ['wrong-unit']


def test_the_walk_descends_arrays_of_tables(tmp_path: Path) -> None:
    """THE MEASURED MISS. Six of motronics' 49 keys live only under `[[...]]` rows.

    A dict-only walk reports this tree clean, which is the same answer a clean tree gives.
    """
    planted = _tree(tmp_path, 'case.toml', '[[winding.rows]]\nintra_slot_pitch = 1.52\n')
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert [site.reason for site in scan] == ['bare-number'], 'the array-of-tables row was not reached'


def test_an_undeclared_key_is_not_this_guards_business(tmp_path: Path) -> None:
    """Scope claim, checked: a key nobody declared is the NAME scan's subject, not this one's."""
    planted = _tree(tmp_path, 'ring.toml', 'wires_per_row = 4\n')
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert not scan.violations
    assert scan.keys_seen == frozenset()


def test_an_unreadable_file_is_named_rather_than_counted_as_clean(tmp_path: Path) -> None:
    """A file that failed to parse must not be indistinguishable from one that parsed clean."""
    planted = _tree(tmp_path, 'broken.toml', 'this is = = not toml\n')
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    assert scan.unreadable == ('broken.toml',)
    assert scan.files_read == 0


def test_the_ratchet_has_a_second_side(tmp_path: Path) -> None:
    """An orphaned declaration is not a pass -- it is a row describing nothing."""
    planted = _tree(tmp_path, 'ring.toml', "intra_slot_pitch = '1.52 deg'\n")
    scan = scan_toml_values([planted], _DECLARED, root=tmp_path)
    problems = value_ratchet(scan, _DECLARED)
    assert len(problems) == 2, problems
    assert all('ORPHANED' in problem for problem in problems)
    assert any('stack_length' in problem for problem in problems)
    assert any('phase_resistance' in problem for problem in problems)


def test_the_interlock_refuses_a_key_held_in_both_registries() -> None:
    """A name cannot be simultaneously waived-as-unconverted and declared-as-converted."""
    conflicts = migration_conflicts({'intra_slot_pitch', 'phase_deg'}, {'intra_slot_pitch'})
    assert set(conflicts) == {'intra_slot_pitch'}
    assert 'did not happen' in conflicts['intra_slot_pitch']


def test_the_interlock_is_quiet_when_the_sets_are_disjoint() -> None:
    """The other side of the same check, so a green interlock means disjoint and not empty."""
    assert migration_conflicts({'phase_deg'}, {'intra_slot_pitch'}) == {}


def test_the_floor_refuses_a_scan_that_read_too_little() -> None:
    """Finding nothing is vacuous rather than green unless the scan is asserted to have run."""
    with pytest.raises(AssertionError, match='did not reach the tree'):
        assert_value_floor(3, 100, 'quantity-value')
    assert_value_floor(100, 100, 'quantity-value')  # the floor's other side: exactly at it passes


def test_the_remedy_names_what_to_write() -> None:
    """A refusal that says only what is wrong sends the reader to the source for the answer."""
    remedy = value_remedy(QuantitySite('ring.toml', 'intra_slot_pitch', '1.52', 'bare-number'), 'deg')
    assert "intra_slot_pitch = '<value> deg'" in remedy
    assert 'Q_(' in remedy


def test_parse_quantity_folds_every_pint_failure_into_none() -> None:
    """A typo in one manifest must report that manifest, never crash the scan over the tree."""
    assert parse_quantity('not a quantity at all') is None
    assert parse_quantity('12.5 flurbles') is None
    assert parse_quantity('12.5 mm') is not None
