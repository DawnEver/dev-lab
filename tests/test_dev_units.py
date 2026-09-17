"""A name that spells its unit is found, and the scan that finds it can PROVE what it searched.

The rule this guards -- a unit-suffixed name is refused, so the unit has nowhere to live but the value
-- is only worth carrying if the guard can tell "this tree is clean" from "I read nothing". So every
test here is one of three shapes, and the third is the one that makes the other two mean anything:

* a PLANTED CONTROL: a synthetic tree with one known violation per scanned surface, driven through the
  REAL :func:`~lab_commons.dev.units.scan_files` and the SAME list handed in, never a re-implementation
  of the matching that would agree with itself by construction;
* the OPPOSITE DIRECTION for each claim -- a clean tree reports nothing while still reporting its file
  count, a token inside a name is not a trailing segment, a comment is not a key;
* the DECLARED GAPS, pinned as tests rather than left as prose: the excluded single letters (metre
  among them) carry their collisions, and a function-local name is out of scope on purpose.

NOTHING HERE SCANS THIS REPOSITORY, and that is a measurement rather than a policy. A guard whose
control is the tree it lives in cannot be run on the tree it lives in -- and MEASURED 2026-09-15, this
file IS itself a violation four times: `'--slot-pitch-mm'` and `'--outer-diameter-mm'` appear below as
EXPECTED VALUES, and a whole flag literal is exactly what the CLI surface refuses. Prose is not (the
planted docstring names a flag and is silent), but an assertion cannot be written without writing the
spelling down. `tests/test_no_name_carries_a_unit.py` exempts this file for that reason and asserts the
exemption is USED, so the day these literals move the exemption has to move with them.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from lab_commons.dev import units
from lab_commons.dev._unit_tokens import EXCLUDED_TOKENS, UNIT_TOKENS
from lab_commons.dev.units import (
    SCANNED_SUFFIXES,
    Scan,
    Violation,
    assert_registry_sane,
    scan_files,
    trailing_token,
)

#: The planted Python module, and it carries a NEGATIVE control as well as four positive ones: the
#: docstring names a flag in prose, the function body holds a `local_mm`, and neither is a violation.
#: The flag literal below is the `=value` form, which is exactly how the user's own example is written.
_PY = '''"""Planted: a docstring naming --probe-depth-mm is PROSE, and prose is not a scanned surface."""

import argparse

GAP_MM = 1.2
SLOT_COUNT = 36


def solve(gap_rad: float, *, slot_pitch_mm: float = 12.5, timeout_ms: int = 500):
    local_mm = 2.0
    return gap_rad, slot_pitch_mm, timeout_ms, local_mm


def build(argv):
    return argv + ['--outer-diameter-mm=2.5']


class Spec:
    gap_deg: float = 1.0
    slot_count: int = 36
'''

#: The planted manifest: a kebab bare key, a quoted key, and a table whose key is the offender -- the
#: three spellings TOML allows. The comment and the string VALUE are both written in ASSIGNMENT SHAPE
#: and are NOT keys: the key set comes from the parse, and the line scan reads the comment-stripped
#: text, so neither can produce a record however much it looks like one.
_TOML = """# gap_mm = 12.5 is the wrong way to write it
slot-pitch-mm = 12.5
"conductor-width-mm" = 3.2
title = "a value naming gap_mm is not a key"

[motor]
gap_mm = 1.0

[motor.timing]
deadline_ms = 30

[[slot]]
pitch_mm = 11
"""

#: JSON and JSONL are the same untyped-value defect through a different parser, and they take the two
#: different locating paths: a whole document for `.json`, one document per line for `.jsonl`.
_JSON = """{
  "gap_mm": 1.0,
  "note": "pitch_mm is a value here, not a key",
  "motor": {"pitch_deg": 2.0}
}
"""

_JSONL = """{"deadline_ms": 30, "gap": 1.0}
{"outer_diameter_mm": 2.0}
"""

#: Not a scanned surface, so the scan must NAME it rather than drop it: a file silently skipped is
#: indistinguishable from a file that was read and found clean.
_NOTES = 'gap_mm = 12.5 in prose markdown, which this scan does not read.\n'

_CLEAN_PY = '''"""A module whose names carry their unit in the VALUE, which is the whole point."""


def solve(radial_gap: float, deg_phase: float, slot_count: int) -> float:
    return radial_gap + deg_phase + slot_count
'''


#: The carve-out tree, and every interesting case is a PAIR with the same name shape: `bore_mm` is
#: bound to a bare float as a parameter and as a field (lines 12 and 21) and to a proven quantity in
#: both roles (lines 16 and 28). `LEGACY_MM` names a quantity constructor in a COMMENT and must stay a
#: violation, which holds by construction rather than by stripping -- `ast` discards comments, so
#: there is no `Q_` anywhere in that statement's tree.
_EXEMPT = """from pint import Quantity

from lab_commons.units import Q_, ureg

GAP_MM = 1.2
RING_MM = Q_(2.0, 'mm')
BORE_MM = ureg.Quantity(3.0, 'mm')
DEPTH_MM = Quantity(4.0, 'mm')
LEGACY_MM = 5.0  # was Q_(5.0, 'mm') before the unit moved into the value


def solve(bore_mm: float, gap_mm: Quantity, span_mm: LengthType, count: int):
    return bore_mm, gap_mm, span_mm, count


def documented(bore_mm: Quantity):
    return bore_mm


class Declared:
    bore_mm: float = 1.0
    gap_mm: Quantity = Q_(1.0, 'mm')
    span_mm: LengthType = 1.0
    depth_mm: float = Q_(4.0, 'mm')


class Instrumented:
    bore_mm: Quantity = Q_(1.0, 'mm')
"""


def _plant(tmp_path: Path) -> list[Path]:
    """Write the planted tree and return the SAME list a caller would hand the scan."""
    written = {
        'planted.py': _PY,
        'manifest.toml': _TOML,
        'deck.json': _JSON,
        'deck.jsonl': _JSONL,
        'notes.md': _NOTES,
    }
    for name, text in written.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    return [tmp_path / name for name in written]


def test_a_planted_violation_is_found_on_every_scanned_surface(tmp_path: Path) -> None:
    """THE CONTROL. Six names in the module, five in the manifest, two per deck -- 15, through the real scan.

    The expectation is the SET of (name, token) pairs rather than a count, because the thing worth
    pinning is WHICH name each surface yielded: a count would stay green if one surface stopped
    yielding and another started.
    """
    scan = scan_files(_plant(tmp_path), root=tmp_path)

    found = {(violation.name, violation.token) for violation in scan.violations}
    assert found == {
        ('GAP_MM', 'mm'),
        ('gap_rad', 'rad'),
        ('slot_pitch_mm', 'mm'),
        ('timeout_ms', 'ms'),
        ('--outer-diameter-mm', 'mm'),
        ('gap_deg', 'deg'),
        ('slot-pitch-mm', 'mm'),
        ('conductor-width-mm', 'mm'),
        ('gap_mm', 'mm'),
        ('deadline_ms', 'ms'),
        ('pitch_mm', 'mm'),
        ('pitch_deg', 'deg'),
        ('outer_diameter_mm', 'mm'),
    }, f'the planted tree must yield exactly these names; got {sorted(found)}'
    assert len(scan.violations) == 15, 'six in the module, five in the manifest, two per deck'

    # And no place may be reported twice: a locator that matched a name inside a comment or a string
    # value would add a second record pointing at prose rather than at code.
    places = {(violation.path, violation.line, violation.name) for violation in scan.violations}
    assert len(places) == len(scan.violations), 'one name was reported twice at one line'


def test_a_clean_tree_reports_nothing_and_still_counts_what_it_read(tmp_path: Path) -> None:
    """The opposite direction, and the reason it is not vacuous: the same call still reports its files.

    `radial_gap` is the shape the rule does NOT refuse and `deg_phase` is the mirror of `phase_deg`, so
    a scan that matched the token anywhere in a name would red here rather than report clean.
    """
    (tmp_path / 'clean.py').write_text(_CLEAN_PY, encoding='utf-8')
    (tmp_path / 'notes.md').write_text(_NOTES, encoding='utf-8')

    scan = scan_files([tmp_path / 'clean.py', tmp_path / 'notes.md'], root=tmp_path)

    assert scan.violations == ()
    assert scan.files_read == 1, 'the clean run must still say it read the file it judged'
    assert scan.skipped == ('notes.md',)


def test_every_scan_reports_the_token_set_it_searched_for(tmp_path: Path) -> None:
    """The FLOOR. "Found nothing" and "searched for nothing" are the same empty tuple otherwise."""
    scan = scan_files(_plant(tmp_path), root=tmp_path)

    assert scan.tokens == tuple(sorted(UNIT_TOKENS)), 'the default scan must say which set it used'
    assert scan.files_read == 4, 'four of the five planted files are a scanned suffix'
    assert scan.skipped == ('notes.md',), 'a file that was not read must be NAMED, not dropped'


def test_a_narrowed_token_set_is_visible_in_the_record(tmp_path: Path) -> None:
    """A caller that narrowed the set cannot be mistaken for one that used the shared default."""
    scan = scan_files(_plant(tmp_path), root=tmp_path, tokens=('mm', 'MS'))

    assert scan.tokens == ('mm', 'ms'), 'the set is reported lower-cased and sorted, as it is matched'
    assert {violation.token for violation in scan.violations} == {'mm', 'ms'}, 'rad/deg are not searched'
    assert scan.tokens != tuple(sorted(UNIT_TOKENS)), 'a narrowed scan cannot read as the default one'


def test_a_domain_repo_can_opt_into_a_single_letter(tmp_path: Path) -> None:
    """The escape the exclusions point at, driven rather than described.

    `_m` is excluded from the shared default because `Q_0A_per_m` in `lab_commons.em` carries a pint
    Quantity in its value; a domain repo that wants metre adds the row, and the Scan reports it.
    """
    (tmp_path / 'planted.py').write_text('PROBE_DEPTH_M = 0.001\n', encoding='utf-8')

    assert scan_files([tmp_path / 'planted.py'], root=tmp_path).violations == ()

    opted = scan_files([tmp_path / 'planted.py'], root=tmp_path, tokens=(*UNIT_TOKENS, 'm'))
    assert [violation.name for violation in opted.violations] == ['PROBE_DEPTH_M']
    assert opted.tokens == tuple(sorted({*UNIT_TOKENS, 'm'}))


def test_the_scan_reads_the_files_it_is_handed_and_no_others(tmp_path: Path) -> None:
    """The file list is an ARGUMENT, which is what lets this control exist at all."""
    (tmp_path / 'handed_in.py').write_text(_CLEAN_PY, encoding='utf-8')
    (tmp_path / 'left_out.py').write_text('GAP_MM = 1.0\n', encoding='utf-8')

    scan = scan_files([tmp_path / 'handed_in.py'], root=tmp_path)

    assert scan.violations == ()
    assert scan.files_read == 1, 'the neighbouring offender was never handed in, so it was never read'


def test_only_the_last_segment_is_matched() -> None:
    """`gap_rad` is the defect and `radial_gap` is not: the rule is about the SUFFIX a reader takes."""
    assert trailing_token('gap_rad') == 'rad'
    assert trailing_token('radial_gap') is None
    assert trailing_token('phase_deg') == 'deg'
    assert trailing_token('deg_phase') is None
    assert trailing_token('slot-pitch-mm') == 'mm'
    assert trailing_token('--slot-pitch-mm') == 'mm'


def test_a_token_that_is_not_the_whole_segment_is_not_a_match() -> None:
    """Exact, not a substring: the family's `Q_1mm` constants hold pint Quantities and must not red."""
    for name in ('Q_1mm', 'Q_0Nm', 'millimetre', 'mm2x', 'deltamm'):
        assert trailing_token(name) is None, f'{name} spells no trailing unit segment'
    assert trailing_token('mm2') == 'mm2', 'a squared unit is written as its own segment'
    assert trailing_token('GAP_MM') == 'mm', 'a constant shouts its unit, and shouting is still spelling'


def test_the_record_names_the_path_the_line_the_name_and_the_token(tmp_path: Path) -> None:
    """The shape the caller reads, pinned as a tuple so a reordering cannot slip through."""
    (tmp_path / 'planted.py').write_text(_PY, encoding='utf-8')
    scan = scan_files([tmp_path / 'planted.py'], root=tmp_path)

    assert Violation._fields == ('path', 'line', 'name', 'token')
    (record,) = [violation for violation in scan.violations if violation.name == 'GAP_MM']
    assert record == ('planted.py', 5, 'GAP_MM', 'mm'), f'the path is root-relative; got {record}'
    assert scan.violations == tuple(sorted(scan.violations)), 'a diff of two runs must be readable'

    # And the line is a REAL line of the planted file, for every record rather than the one above --
    # a cross-check against the file, not a second implementation of the locating pass.
    lines = _PY.splitlines()
    for violation in scan.violations:
        assert violation.name in lines[violation.line - 1], f'{violation} does not point at itself'


def test_a_path_outside_the_declared_root_is_refused(tmp_path: Path) -> None:
    """A record keyed by an absolute path is a fact about one box, so the naming is REFUSED instead."""
    outside = tmp_path.parent / 'elsewhere.py'
    with pytest.raises(ValueError, match='not under'):
        scan_files([outside], root=tmp_path)


def test_the_python_surface_is_parameters_and_declared_fields(tmp_path: Path) -> None:
    """All five parameter kinds, a class field, a module constant -- and nothing else."""
    (tmp_path / 'planted.py').write_text(_PY, encoding='utf-8')
    names = {violation.name for violation in scan_files([tmp_path / 'planted.py'], root=tmp_path)}

    assert {'gap_rad', 'slot_pitch_mm', 'timeout_ms'} <= names, 'every def parameter is an interface'
    assert 'gap_deg' in names, 'a dataclass/Pydantic field is an interface'
    assert 'GAP_MM' in names, 'a module constant is an interface'


def test_a_local_and_a_prose_flag_are_declared_out_of_scope(tmp_path: Path) -> None:
    """The two exclusions that must be pinned rather than left as prose, because they look like misses.

    A function-local assignment never reaches a second party -- the function's INPUTS are its
    parameters, which ARE scanned -- and a flag named in a docstring is not a literal, which is what
    keeps the guard's own control from being the first thing it reports.
    """
    (tmp_path / 'planted.py').write_text(_PY, encoding='utf-8')
    names = {violation.name for violation in scan_files([tmp_path / 'planted.py'], root=tmp_path)}

    assert 'local_mm' not in names, 'a local is implementation, not interface'
    assert 'slot_count' not in names, 'the clean neighbour is not rounded up with the offenders'
    assert not any(name.startswith('--probe') for name in names), 'the docstring flag is prose'


def test_a_quantity_binding_is_exempt_while_a_bare_float_of_the_same_shape_is_not(tmp_path: Path) -> None:
    """THE CARVE-OUT, DRIVEN IN BOTH DIRECTIONS ON TWINS: same name shape, different proof.

    `bore_mm` appears four times and the only thing that separates the two pairs is what it is BOUND
    to -- a `float` annotation on one side, a `Quantity` annotation on the other -- so a carve-out that
    exempted by NAME would pass this and a carve-out that exempted nothing would fail it.
    """
    (tmp_path / 'declared.py').write_text(_EXEMPT, encoding='utf-8')
    scan = scan_files([tmp_path / 'declared.py'], root=tmp_path)

    flagged = {(violation.name, violation.line) for violation in scan.violations}
    assert flagged == {
        ('GAP_MM', 5),  # a bare float constant, no annotation, nothing that proves a quantity
        ('LEGACY_MM', 9),  # the comment NAMES Q_ and the value is a plain 5.0
        ('bore_mm', 12),  # parameter annotated float
        ('bore_mm', 21),  # declared field annotated float
    }, f'the four bare bindings; got {flagged}'

    exempted = {(violation.name, violation.line) for violation in scan.exempt}
    assert exempted == {
        ('RING_MM', 6),  # Q_(...)
        ('BORE_MM', 7),  # ureg.Quantity(...)
        ('DEPTH_MM', 8),  # Quantity(...)
        ('gap_mm', 12),  # parameter annotated Quantity
        ('span_mm', 12),  # parameter annotated a family quantity type
        ('bore_mm', 16),  # the TWIN of the flagged parameter on line 12
        ('gap_mm', 22),  # field annotated Quantity AND constructed
        ('span_mm', 23),  # field annotated LengthType
        ('depth_mm', 24),  # field annotated float, but the right-hand side proves it
        ('bore_mm', 28),  # the TWIN of the flagged field on line 21
    }, f'the ten provable bindings; got {exempted}'


def test_the_carve_out_is_reported_rather_than_silent(tmp_path: Path) -> None:
    """An exemption is EVIDENCE. "0 violations" and "the carve-out ate the tree" must not look alike."""
    (tmp_path / 'declared.py').write_text(_EXEMPT, encoding='utf-8')
    scan = scan_files([tmp_path / 'declared.py'], root=tmp_path)

    assert len(scan.exempt) == 10, 'the count and the names are the same fact, and the names are here'
    assert set(scan.violations).isdisjoint(scan.exempt), 'a name is a violation or an exemption, never both'
    assert tuple(scan) == scan.violations, 'the exempt records must never iterate out as violations'
    assert {violation.token for violation in scan.exempt} == {'mm'}, 'each record keeps the token it matched'

    # And the carve-out is not a blanket on the file: the same scan still reports its violations.
    assert scan.files_read == 1 and {violation.name for violation in scan.violations} == {
        'GAP_MM',
        'LEGACY_MM',
        'bore_mm',
    }


def test_a_flag_is_read_from_a_whole_literal_and_not_from_prose(tmp_path: Path) -> None:
    """`--outer-diameter-mm=2.5` is a literal; the same words inside a docstring are not."""
    (tmp_path / 'planted.py').write_text(_PY, encoding='utf-8')
    scan = scan_files([tmp_path / 'planted.py'], root=tmp_path)

    flags = {violation.name for violation in scan.violations if violation.name.startswith('--')}
    assert flags == {'--outer-diameter-mm'}, f'the record names the flag, not its argument; got {flags}'


def test_toml_comments_and_string_values_are_not_keys(tmp_path: Path) -> None:
    """The PARSE decides what is a key, so neither a comment nor a value can be a false positive."""
    (tmp_path / 'manifest.toml').write_text(_TOML, encoding='utf-8')
    scan = scan_files([tmp_path / 'manifest.toml'], root=tmp_path)

    assert len(scan.violations) == 5, f'the five planted keys and only those; got {scan.violations}'
    assert {violation.name for violation in scan.violations} == {
        'slot-pitch-mm',
        'conductor-width-mm',
        'gap_mm',
        'deadline_ms',
        'pitch_mm',
    }, 'a quoted key is read without its quotes, because the parse is what names it'
    # `gap_mm` is ALSO written in the comment on line 1, in assignment shape, and only the real key
    # may be reported: a comment is not a key, however much of one it names.
    (gap,) = [violation for violation in scan.violations if violation.name == 'gap_mm']
    assert (gap.line, _TOML.splitlines()[gap.line - 1]) == (7, 'gap_mm = 1.0'), f'got {gap}'


def test_a_table_header_is_a_key_too(tmp_path: Path) -> None:
    """`[geometry.arc_ms]` names a unit in a header, and a header is not an assignment.

    The two directions are in one file: `pitch_mm` is the assignment form and `arc_ms` the header
    form, so a scan that only read assignments would report one record where there are two.
    """
    (tmp_path / 'manifest.toml').write_text('[slot]\npitch_mm = 11\n\n[geometry.arc_ms]\nspan = 1\n', encoding='utf-8')
    scan = scan_files([tmp_path / 'manifest.toml'], root=tmp_path)

    assert {violation.name for violation in scan.violations} == {'pitch_mm', 'arc_ms'}


def test_json_and_jsonl_keys_are_read_by_their_own_parsers(tmp_path: Path) -> None:
    """Two locating paths, one key set: the whole document, and one document per line."""
    (tmp_path / 'deck.json').write_text(_JSON, encoding='utf-8')
    (tmp_path / 'deck.jsonl').write_text(_JSONL, encoding='utf-8')
    scan = scan_files([tmp_path / 'deck.json', tmp_path / 'deck.jsonl'], root=tmp_path)

    assert {(violation.path, violation.name) for violation in scan.violations} == {
        ('deck.json', 'gap_mm'),
        ('deck.json', 'pitch_deg'),
        ('deck.jsonl', 'deadline_ms'),
        ('deck.jsonl', 'outer_diameter_mm'),
    }, f'got {scan.violations}'
    jsonl = [violation for violation in scan.violations if violation.path == 'deck.jsonl']
    assert sorted(violation.line for violation in jsonl) == [1, 2], 'a jsonl line is its own document'


def test_a_flag_literal_at_a_call_site_is_caught_and_a_bare_word_is_not(tmp_path: Path) -> None:
    """The CLI surface, both directions: `--slot-pitch-mm` is a flag, `--speed` and `-n` are not."""
    (tmp_path / 'cli.py').write_text(
        'import argparse\n\nparser = argparse.ArgumentParser()\n'
        "parser.add_argument('--slot-pitch-mm', type=float)\n"
        "parser.add_argument('--speed', type=float)\n"
        "parser.add_argument('-n', type=int)\n",
        encoding='utf-8',
    )
    scan = scan_files([tmp_path / 'cli.py'], root=tmp_path)

    assert {violation.name for violation in scan.violations} == {'--slot-pitch-mm'}


def test_the_scanned_suffixes_are_declared(tmp_path: Path) -> None:
    """Which surfaces are read is DATA, so a suffix added or dropped is a diff rather than a surprise."""
    assert SCANNED_SUFFIXES == ('.json', '.jsonl', '.py', '.toml')
    assert scan_files([], root=tmp_path) == Scan(
        violations=(),
        exempt=(),
        tokens=tuple(sorted(UNIT_TOKENS)),
        files_read=0,
        skipped=(),
    ), 'an empty scan is an empty scan, and it still says which set it searched for'


def test_the_excluded_registry_is_not_vacuous() -> None:
    """Every exclusion names a collision, and metre -- core's own unit -- is FINDABLE among them.

    A scan that silently omits metre reads exactly like a scan that found none, so the exclusion is a
    row with a reason a reader can argue with rather than an absence.
    """
    blank = sorted(token for token, reason in EXCLUDED_TOKENS.items() if not reason.strip())
    assert blank == [], f'exclusions with no recorded collision: {blank}'
    assert 'm' in EXCLUDED_TOKENS, "metre is core's own unit; its omission must be declared"
    assert 'metre' in EXCLUDED_TOKENS['m']
    assert 's' in EXCLUDED_TOKENS and 'second' in EXCLUDED_TOKENS['s']
    assert set(UNIT_TOKENS).isdisjoint(EXCLUDED_TOKENS), 'a token in both tables refuses and excuses itself'
    assert 'mm' not in EXCLUDED_TOKENS, "sanity: the user's own example token is included"


#: The floor a reason has to clear to be a REASON, and it is a floor rather than a pin: prose grows and
#: the shortest row here is a measurement that happens to be short ("decibel -- `_db` is a database
#: handle, 28 rows"). MEASURED 2026-09-15 the shortest is 70 characters, so 60 refuses a shrug without
#: refusing a terse truth.
_REASON_FLOOR = 60


def _shrugs(excluded: Mapping[str, str]) -> list[str]:
    """The rows whose reason is filler rather than a measurement -- as DATA, so a bad row can be planted.

    Four properties, and each is the failure of one way to fake a reason. A COUNT, because "it is not a
    unit here" is unfalsifiable and "843 rows, zero of pressure" is not. A BACKTICKED NAME WHOSE OWN
    FINAL SEGMENT IS THE TOKEN, because a reason that cites no collision is a reason about nothing --
    and the citation is scored by :func:`trailing_token` ITSELF, so a reason naming a spelling the
    machinery could never match is caught here rather than in production. A LENGTH FLOOR, because the
    cheapest filler is a fragment. And UNIQUENESS, because a copy-pasted reason reads as two considered
    decisions and is one -- and the second row is the one nobody re-measured.

    Takes its table as an ARGUMENT for the reason :func:`~lab_commons.dev.units.assert_registry_sane`
    does: a check that can only ever be run against the real data cannot be shown to fire at all.
    """
    offenders = [token for token, reason in excluded.items() if len(reason.strip()) < _REASON_FLOOR]
    offenders += [token for token, reason in excluded.items() if not re.search(r'\d', reason)]
    offenders += [
        token
        for token, reason in excluded.items()
        if not any(trailing_token(span, (token,)) == token for span in re.findall(r'`([^`]+)`', reason))
    ]
    seen: dict[str, str] = {}
    for token, reason in excluded.items():
        offenders += [token, seen[reason]] if reason in seen else []
        seen.setdefault(reason, token)
    return sorted(set(offenders))


def test_every_exclusion_records_a_measured_collision_rather_than_a_shrug() -> None:
    """The real table passes, and the check that says so is DRIVEN against filler rather than trusted.

    A row whose reason is filler cannot be told from a hole somebody widened to make a red suite green,
    which is why `assert_registry_sane` already refuses a BLANK one. This is the floor above that: blank
    is not the only way to record nothing, and the reasons a reader will actually meet are the terse
    ones, so the check exists to refuse a shrug and the planted rows below prove it can.
    """
    assert _shrugs(EXCLUDED_TOKENS) == [], 'a row above is filler rather than a measurement'

    planted = {
        'x': 'not a unit here',  # no count, no collision, too short -- filler on all three counts
        'y': 'metre -- `_y` is something else entirely, and it is not a unit in this tree at all.',  # no count
        'z': 'metre -- 4 rows measured, none of them the unit, and the cited spelling `gap_zz` does not '
        'end in the token it is filed under',  # a citation the machinery could never match
        'w': 'the identical sentence',  # the duplicate pair, and both members are named
        'v': 'the identical sentence',
    }
    assert _shrugs(planted) == ['v', 'w', 'x', 'y', 'z'], f'planted filler was not refused: {_shrugs(planted)}'


#: The rows this registry moved OUT of the include table, each as ``(a name ending in the token, the
#: collision the exclusion records)``. The first element is a SPELLING the token genuinely is -- the
#: unit a repo would opt in for -- and the second is a REAL name measured in the family. Driven in both
#: directions, because an exclusion has two: the collision must be clean under the shared default, and
#: the unit spelling must still be catchable by a repo that adds the row back.
_MOVED_OUT: dict[str, tuple[str, str]] = {
    'dm': ('gap_dm', 'cached_dm'),  # decimetre vs a DiscreteModel
    'ev': ('settle_ev', 't_ev'),  # electronvolt vs an event time
    'fm': ('gap_fm', 'srdab_fm'),  # femtometre vs the frequency-modulated drive law
    'ft': ('length_ft', 'ft'),  # foot vs the tangential force component
    'hp': ('rated_hp', '_hp'),  # horsepower vs the BH-curve derivative
    'hr': ('standby_hr', 'r_hr'),  # hour vs an archived residual matrix
    'km': ('distance_km', 'KM'),  # kilometre vs the motor constant
    'kw': ('load_kw', 'band_kw'),  # kilowatt vs keyword arguments
    'lb': ('mass_lb', 'radius_lb'),  # pound vs a lower bound
    'ng': ('mass_ng', 'tol_ng'),  # nanogram vs the ngspice side of a cross-check
    'pm': ('gap_pm', 'flux_d_pm'),  # picometre vs a permanent magnet
    'ps': ('delay_ps', 'Simulink-PS'),  # picosecond vs the Simulink-PS converter block
    'psi': ('pressure_psi', '_PSI'),  # pounds per square inch vs flux linkage
    'sec': ('window_sec', 'n_sec'),  # second vs a sector count
    'us': ('latency_us', 'us'),  # microsecond vs the control input u(s)
    'wh': ('energy_wh', '_wh'),  # watt-hour vs the want side of a mesh comparison
}


def test_every_moved_token_is_refused_by_nobody_and_its_collision_is_clean() -> None:
    """The removals, in BOTH directions and through the REAL matcher rather than a restatement of it.

    A removal is only honest if the unit spelling it gave up is still identifiable: the opt-in below is
    the escape every exclusion in this registry points at, so a row that moved out and could not be
    added back would be a capability DELETED rather than a default narrowed.
    """
    for token, (unit_name, collision) in _MOVED_OUT.items():
        assert token not in UNIT_TOKENS, f'{token!r} was moved out and is still in the shared default'
        assert token in EXCLUDED_TOKENS, f'{token!r} left the table without a recorded collision'

        assert trailing_token(collision) is None, f'{collision!r} is the collision and must not be refused'
        assert trailing_token(unit_name) is None, f'{unit_name!r} is refused by the shared default'

        opted = (*UNIT_TOKENS, token)
        assert trailing_token(unit_name, opted) == token, (
            f'{token!r} is excluded AND unreachable by an opt-in, which is a deleted capability rather '
            f'than a narrowed default'
        )
        assert trailing_token(collision, opted) == token, (
            f'an opt-in must reach the spelling it opted into; {collision!r} did not'
        )


#: The rows this registry ADDED, each as ``(token, a name that ends in it)``. The names are measured:
#: `volume_m3`, `area_m2`, `inertias_kg_m2`, `flux_linkage_wb`, `ld_uh`, `volume_mm3`, `g_per_cm3`.
_ADDED: dict[str, str] = {
    'cm3': 'g_per_cm3',
    'm2': 'inertias_kg_m2',
    'm3': 'density_kg_per_m3',
    'mm3': 'volume_mm3',
    'uh': 'ld_uh',
    'wb': 'flux_linkage_wb',
}


def test_every_added_token_is_refused_as_a_final_segment_and_only_there() -> None:
    """The additions, in both directions: the segment is caught, a PREFIX of a longer segment is not.

    The negative direction is the one with a measurement behind it -- a pattern that scored a token as a
    prefix of a longer word produced a 9,735-hit flood and was pure artifact -- so `m2` must catch
    `area_m2` and must not catch `m2x`, and `m3` must catch `kg_per_m3` and must not catch `mm3`.
    """
    for token, unit_name in _ADDED.items():
        assert token in UNIT_TOKENS, f'{token!r} is declared added and is not in the table'
        assert token not in EXCLUDED_TOKENS, f'{token!r} is in BOTH tables'
        assert trailing_token(unit_name) == token, f'{unit_name!r} ends in {token!r} and was not refused'

        assert trailing_token(f'{unit_name}x') is None, f'{token!r} matched as a PREFIX of a longer word'
        assert trailing_token(f'{token}_extra') is None, f'{token!r} matched inside a name, not at its end'


def test_a_bad_registry_row_is_refused_at_the_seam() -> None:
    """The control for the refusal itself: the real data is passed, and then two bad rows are planted."""
    assert_registry_sane(UNIT_TOKENS, EXCLUDED_TOKENS)

    with pytest.raises(ValueError, match='BOTH tables'):
        assert_registry_sane(('mm', 'gap'), {'mm': 'metre, and also millimetre'})
    with pytest.raises(ValueError, match='no reason'):
        assert_registry_sane(('mm',), {'m': '   '})
    with pytest.raises(ValueError, match='sorted'):
        assert_registry_sane(('MM', 'cm'), {})
    with pytest.raises(ValueError, match='sorted'):
        assert_registry_sane(('cm', 'mm', 'cm'), {})


def test_the_module_declares_its_public_surface() -> None:
    """One name per idea, and the caller exporting it needs to know which names those are."""
    assert set(units.__all__) == {
        'SCANNED_SUFFIXES',
        'Scan',
        'Violation',
        'assert_registry_sane',
        'scan_files',
        'trailing_token',
    }
    for name in units.__all__:
        assert hasattr(units, name), f'{name} is exported and does not exist'


def _subtract_enclosing_scopes(text: str) -> tuple[units._Signature, ...]:
    """The pre-single-descent implementation, kept as the CONTROL the one-pass reader is judged against.

    This is how :func:`~lab_commons.dev.units._python_signatures` decided module/class scope before
    the single descent landed: a full ``ast.walk`` per ENCLOSING callable to collect the assignments
    that are function-local, then a second full ``ast.walk`` to yield. It is reproduced here rather
    than imported so the equivalence test below compares two INDEPENDENT answers. If it is ever
    edited to match a new ``_python_signatures``, this test stops proving anything -- it is the OLD
    behaviour on purpose, and its cost (a nested function re-walked once per callable containing it)
    is the whole reason the new one exists.
    """
    tree = ast.parse(text)
    callables = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    local = {
        id(inner)
        for outer in ast.walk(tree)
        if isinstance(outer, callables)
        for inner in ast.walk(outer)
        if isinstance(inner, (ast.Assign, ast.AnnAssign))
    }
    found: list[units._Signature] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
            found.extend(
                (argument.lineno, argument.arg, units._exempt_annotation(argument.annotation))
                for argument in every
                if argument is not None
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and id(node) not in local:
            exempt = units._exempt_assignment(node)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                found.extend((leaf.lineno, leaf.id, exempt) for leaf in ast.walk(target) if isinstance(leaf, ast.Name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal = units._FLAG.fullmatch(node.value)
            if literal is not None:
                found.append((node.lineno, literal.group(0).split('=', 1)[0], False))
    return tuple(found)


#: Every scope shape the two readers must agree about, in ONE module: a nested callable three deep, a
#: name shadowed in an inner scope, a comprehension, a lambda (with a unit-suffixed DEFAULT, which the
#: old code reached through the lambda's own subtree), a class body inside a function, an async def,
#: and -- the opposite direction -- a module constant and a class field that are NOT local and must
#: still be reported. The exempt carve-out is planted in both scopes so a change of scope decision
#: cannot hide behind it.
_SCOPE_CORPUS = """\
GAP_MM = 1.0


class Stator:
    slot_width_mm: float = 2.0
    proven_mm = Q_(2.0, 'mm')

    def method(self, tooth_mm: float) -> None:
        inner_mm = 3.0

        def nested(depth_mm: int) -> None:
            deeper_mm = 4.0

            def deepest(leaf_mm: int) -> None:
                bottom_mm = 5.0
                shadowed_mm = 6.0

            shadowed_mm = 7.0

        shadowed_mm = 8.0


async def outer(edge_mm: float) -> None:
    lengths_mm = [item_mm for item_mm in range(3)]
    scale_mm = lambda span_mm=9.0: span_mm

    class Local:
        body_mm = 10.0

        def deep(self, arg_mm: float) -> None:
            local_mm = 11.0

    chained_mm = also_mm = 12.0
    typed_mm: float = Q_(13.0, 'mm')
"""


def test_the_single_descent_reports_exactly_what_the_enclosing_scope_walk_reported() -> None:
    """THE EQUIVALENCE PROOF: every scope shape the two readers must agree about, planted at once.

    The risk the single descent carries is entirely in WHICH assignments it calls function-local: a
    flag carried down the tree instead of a set built by re-walking each enclosing callable. So the
    plant is scope shapes, not names -- nesting three deep, the same name bound at three different
    depths, a comprehension, a lambda default, a class body inside a function, an async def.

    THE FLOOR COMES FIRST: the control is asserted to find the module constant and the class fields
    and to find NONE of the function-local names, before the two answers are compared. Without it an
    equality between two empty tuples would read as success and the descent could be skipping
    everything.
    """
    control = _subtract_enclosing_scopes(_SCOPE_CORPUS)
    names = [name for _, name, _ in control]

    # THE FLOOR, both directions: what module/class scope declares is reported...
    assert 'GAP_MM' in names
    assert 'slot_width_mm' in names
    assert 'proven_mm' in names
    # ...and every assignment REACHABLE from a callable is not, at any depth or in any inner scope --
    # a class body nested inside a function included, which is the one answer here that reads as a
    # surprise and is the control's, not this test's: `body_mm` is inside `outer`.
    for local_name in ('inner_mm', 'deeper_mm', 'bottom_mm', 'shadowed_mm', 'lengths_mm', 'local_mm', 'body_mm'):
        assert local_name not in names, local_name
    for local_name in ('chained_mm', 'also_mm', 'typed_mm', 'scale_mm'):
        assert local_name not in names, local_name
    # Parameters ARE reported at every depth, including a lambda's -- the two readers must agree there too.
    for parameter in ('tooth_mm', 'depth_mm', 'leaf_mm', 'edge_mm', 'arg_mm'):
        assert parameter in names, parameter
    # The carve-out is exercised on both sides of the decision.
    assert (6, 'proven_mm', True) in control
    assert (5, 'slot_width_mm', False) in control

    assert tuple(units._python_signatures(_SCOPE_CORPUS)) == control


def test_the_single_descent_agrees_with_the_control_on_this_repository() -> None:
    """The planted corpus is what the two must agree about; this is every shape nobody thought to plant.

    A floor rather than a guess at the count: this repository tracks well over 40 Python files, and a
    comparison over an empty list would agree with itself.
    """
    sources = sorted(Path(__file__).resolve().parents[1].glob('**/*.py'))
    sources = [path for path in sources if '.venv' not in path.parts and '__pycache__' not in path.parts]
    assert len(sources) >= 40, f'the corpus is too small to prove anything: {len(sources)}'
    for path in sources:
        text = path.read_text(encoding='utf-8')
        assert tuple(units._python_signatures(text)) == _subtract_enclosing_scopes(text), path.name


def _search_per_name(lines: Sequence[str], names: Iterable[str], pattern: str) -> tuple[units._Signature, ...]:
    """The pre-index implementation of :func:`~lab_commons.dev.units._locate`, kept as the CONTROL.

    This is how a key's line was found before the word-run index landed: one compiled pattern per
    name, and every one of them searched against every line -- quadratic in a file's key count, which
    is what put 3.96M ``re.search`` calls at the top of the scan's profile. It is reproduced here
    rather than imported so the equivalence test below compares two INDEPENDENT answers. It must
    never be "fixed" to agree with the new one: it is the OLD behaviour on purpose, and the day it is
    edited to match, this test stops proving anything.
    """
    patterns = [(name, re.compile(pattern.format(name=re.escape(name)))) for name in names]
    found: list[units._Signature] = []
    for number, raw in enumerate(lines, start=1):
        text = units._strip_comment(raw)
        found.extend((number, name, False) for name, compiled in patterns if compiled.search(text))
    return tuple(found)


#: Every key shape the two locators must agree about, in ONE document: a leaf repeated under two
#: tables, a key inside an array of tables (twice, at two lines), a dotted key, a quoted key, a kebab
#: key, an inline table, a name that occurs in a COMMENT (which must not be located) and the same
#: name inside a STRING VALUE (which the control DOES locate -- the pattern is loose by design, and
#: an equivalence test asserts what the control does, not what one wishes it did).
_KEY_CORPUS = """\
# gap_mm = 0.0 -- a comment that reads as an assignment
gap_mm = 1.0
note = "gap_mm = 99.0 in a string"

[stator]
gap_mm = 2.0
"quoted_mm" = 3.0
tooth.depth_mm = 4.0
kebab-mm = 5.0
inline = { span_mm = 6.0 }

[[rotor.magnets]]
length_mm = 7.0

[[rotor.magnets]]
length_mm = 8.0
"""

#: The JSON half of the same question: the pattern differs (quoted both sides, ``:`` for delimiter)
#: and the prefilter has to be exact for it too. A repeated key at two lines and a nested object.
_KEY_CORPUS_JSON = """\
{
  "gap_mm": 1.0,
  "stator": {"gap_mm": 2.0, "tooth-mm": 3.0},
  "note": "\\"gap_mm\\": 99.0",
  "rotor": [{"length_mm": 4.0}, {"length_mm": 5.0}]
}
"""


def _keys(loaded: object) -> list[str]:
    return sorted({dotted.rsplit('.', 1)[-1] for dotted in units._dotted_keys(loaded)})


def test_the_indexed_locator_reports_exactly_what_the_search_per_name_locator_reported() -> None:
    """THE EQUIVALENCE PROOF for TOML: every key shape the two locators must agree about, planted at once.

    The risk the index carries is entirely in WHICH names it lets through to the regex: a name whose
    first word-run is absent from the line is never searched for. So the plant is key SHAPES --
    quoted, dotted, kebab, inline, array-of-tables, a leaf shared by two tables -- plus the two
    places a name appears where it is NOT a key.

    THE FLOOR COMES FIRST: the control is asserted to report the planted keys at their exact lines,
    and to report NOTHING on the comment line, before the two answers are compared. Without it an
    equality between two empty tuples would read as success and the index could be dropping
    everything.
    """
    lines = _KEY_CORPUS.splitlines()
    control = _search_per_name(lines, _keys(tomllib.loads(_KEY_CORPUS)), units._TOML_KEY)

    # THE FLOOR: the exact rows, at the exact lines the plant puts them on.
    assert (2, 'gap_mm', False) in control
    assert (6, 'gap_mm', False) in control, 'the leaf shared by two tables is two violations'
    assert (7, 'quoted_mm', False) in control
    assert (8, 'depth_mm', False) in control, 'a dotted key is located at its leaf'
    assert (9, 'kebab-mm', False) in control
    assert (10, 'span_mm', False) in control, 'an inline table is a key position'
    assert (13, 'length_mm', False) in control
    assert (16, 'length_mm', False) in control, 'the second array-of-tables entry is its own line'
    # ...and the comment is stripped before anything is searched, so line 1 carries no row at all.
    assert [row for row in control if row[0] == 1] == []

    assert tuple(units._locate(lines, _keys(tomllib.loads(_KEY_CORPUS)), units._TOML_KEY)) == control


def test_the_indexed_locator_agrees_with_the_control_on_json_too() -> None:
    """The same proof for the JSON pattern, which is a DIFFERENT pattern and needs its own floor.

    ``"{name}"[ \t]*:`` has no lookbehind -- the opening quote is what bounds the name on the left --
    so the argument that makes the word-run prefilter exact has to hold for it separately.
    """
    lines = _KEY_CORPUS_JSON.splitlines()
    names = _keys(json.loads(_KEY_CORPUS_JSON))
    control = _search_per_name(lines, names, units._JSON_KEY)

    assert (2, 'gap_mm', False) in control
    assert (3, 'gap_mm', False) in control, 'a nested object key is its own line'
    assert (3, 'tooth-mm', False) in control
    assert (5, 'length_mm', False) in control

    assert tuple(units._locate(lines, names, units._JSON_KEY)) == control


def test_the_indexed_locator_agrees_with_the_control_on_this_repository_and_on_an_empty_document() -> None:
    """Every TOML this repository tracks, plus the two degenerate documents a planted corpus omits.

    A document with NO lines and one with no key at all must agree too, and they agree trivially --
    which is exactly why they are compared behind a floor rather than on their own: the assertion
    that carries this test is the row count of the real files, and a comparison over an empty list
    would agree with itself.
    """
    root = Path(__file__).resolve().parents[1]
    sources = [path for path in sorted(root.glob('*.toml')) if path.is_file()]
    rows = 0
    for path in sources:
        text = path.read_text(encoding='utf-8')
        lines = text.splitlines()
        names = _keys(tomllib.loads(text))
        control = _search_per_name(lines, names, units._TOML_KEY)
        rows += len(control)
        assert tuple(units._locate(lines, names, units._TOML_KEY)) == control, path.name
    assert rows >= 40, f'the corpus is too small to prove anything: {rows} located keys'

    for degenerate in ('', '# nothing but a comment\n'):
        lines = degenerate.splitlines()
        names = _keys(tomllib.loads(degenerate))
        assert tuple(units._locate(lines, names, units._TOML_KEY)) == _search_per_name(lines, names, units._TOML_KEY)
