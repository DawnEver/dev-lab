"""The controls for :mod:`lab_commons.dev.famtests.injectedwidth` -- every arm, both directions.

THE PAIR THIS FILE EXISTS TO HOLD. This guard and the CJK guard next door key their declarations
differently -- a SITE here, a FILE there -- and their consumer files are close enough to copy from one
another. So the cross-shaped declaration is asserted in BOTH directions here: a file-keyed entry must
be refused by this module, and it must also be shown to ORPHAN rather than fall silent if it ever got
past, because orphaning loudly for the wrong reason is the failure mode that gets a true declaration
deleted.

EVERY SHIPPED ARM IS DRIVEN ON A DOCTORED READER as well as a correct one, and asserted to RED. An arm
only ever seen passing has not been shown to be an arm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import docwidth, floors
from lab_commons.dev.famtests.injectedwidth import (
    MisdeclaredSite,
    OverwideDeclaration,
    OverwidthDocument,
    assert_the_declaration_is_the_shape_the_ratchet_keys_on,
    assert_the_scanner_still_convicts,
    assert_widths_are_the_named_set,
    take_scan,
)
from lab_commons.dev.famtests.trackedcjk import (
    assert_the_declaration_is_the_shape_the_ratchet_keys_on as cjk_shape,
)

_CEILING = docwidth.WIDTH_CEILING
_WHAT = 'INJECTED-DOC-WIDTH-CEILING'


def _plant(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def _scan(root: Path, ceiling: int = _CEILING) -> docwidth.WidthScan:
    return take_scan(sorted(root.rglob('*.md')), root=root, ceiling=ceiling)


def _bound(scan: docwidth.WidthScan, **over: object) -> None:
    kwargs: dict[str, object] = {
        'declared': (),
        'declared_ceiling': 0,
        'floor': 1,
        'headroom': 50,
        'what': _WHAT,
    }
    assert_widths_are_the_named_set(scan, **(kwargs | over))  # type: ignore[arg-type]


# -- THE VERDICT, in the order it takes its three questions. ----------------------------------------


def test_an_overwide_line_is_refused_and_declaring_its_site_clears_the_arm(tmp_path: Path) -> None:
    _plant(tmp_path, 'AGENTS.md', 'x' * (_CEILING + 1) + '\n')
    scan = _scan(tmp_path)
    with pytest.raises(OverwidthDocument, match=r'AGENTS\.md:1'):
        _bound(scan)
    _bound(scan, declared=('AGENTS.md:1',), declared_ceiling=1)


def test_a_rewrapped_line_whose_waiver_stayed_is_refused_too(tmp_path: Path) -> None:
    """The second side: an unused waiver reads as a decision nobody made."""
    _plant(tmp_path, 'AGENTS.md', 'short\n')
    with pytest.raises(OverwidthDocument, match='ORPHANED'):
        _bound(_scan(tmp_path), declared=('AGENTS.md:1',), declared_ceiling=1)


def test_a_declaration_over_its_own_ceiling_is_refused(tmp_path: Path) -> None:
    """The hatch's ceiling, which one of the three consumers has and the other does not."""
    _plant(tmp_path, 'AGENTS.md', ('y' * (_CEILING + 1) + '\n') * 3)
    scan = _scan(tmp_path)
    sites = ('AGENTS.md:1', 'AGENTS.md:2', 'AGENTS.md:3')
    _bound(scan, declared=sites, declared_ceiling=3)
    with pytest.raises(OverwideDeclaration, match='may only go'):
        _bound(scan, declared=sites, declared_ceiling=2)


def test_a_ceiling_of_zero_is_legal_and_is_the_strongest_value(tmp_path: Path) -> None:
    """The asymmetry with a FLOOR, where zero refuses nothing and is itself refused."""
    _plant(tmp_path, 'AGENTS.md', 'short\n')
    _bound(_scan(tmp_path), declared=(), declared_ceiling=0)
    with pytest.raises(floors.FloorMisdeclared):
        _bound(_scan(tmp_path), floor=0)


def test_the_ratchet_is_consulted_only_after_the_floor_binds(tmp_path: Path) -> None:
    """ORDER IS THE PROPERTY: an unmatched corpus must not report a clean ratchet."""
    _plant(tmp_path, 'AGENTS.md', 'x' * (_CEILING + 1) + '\n')
    scan = _scan(tmp_path)
    assert scan.overwidth, 'the scan really holds an offender, so the floor is what fires'
    with pytest.raises(floors.FloorUnmet, match=_WHAT):
        _bound(scan, floor=25)


def test_a_floor_pinned_at_the_measurement_is_what_the_headroom_replaces(tmp_path: Path) -> None:
    """Two consumers pin AT their count; this side is why that is a count pin rather than a floor."""
    for index in range(30):
        _plant(tmp_path, f'p{index}.md', 'short\n')
    with pytest.raises(floors.SlackFloor, match=_WHAT):
        _bound(_scan(tmp_path), floor=2, headroom=5)


# -- THE DECLARATION SHAPE, and the pair it forms with the CJK ledger. ------------------------------


@pytest.mark.parametrize('entry', ['AGENTS.md', 'docs\\page.md:3', './AGENTS.md:3', '/AGENTS.md:3', 'AGENTS.md:'])
def test_a_waiver_that_is_not_a_site_is_refused(entry: str) -> None:
    with pytest.raises(MisdeclaredSite, match='names a SITE'):
        assert_the_declaration_is_the_shape_the_ratchet_keys_on([entry])


def test_a_correctly_spelled_site_and_an_empty_set_both_pass() -> None:
    assert_the_declaration_is_the_shape_the_ratchet_keys_on(['.claude/rules/workflow.md:12', 'AGENTS.md:3'])
    assert_the_declaration_is_the_shape_the_ratchet_keys_on([])


def test_the_two_ledger_shapes_refuse_each_other_in_both_directions() -> None:
    """THE PAIR. Each guard's ledger must be refused by the other, or a copy passes both files."""
    with pytest.raises(MisdeclaredSite):
        assert_the_declaration_is_the_shape_the_ratchet_keys_on(['AGENTS.md'])
    with pytest.raises(AssertionError):
        cjk_shape(['AGENTS.md:3'])
    assert_the_declaration_is_the_shape_the_ratchet_keys_on(['AGENTS.md:3'])
    cjk_shape(['AGENTS.md'])


def test_a_file_keyed_waiver_really_does_only_orphan_here(tmp_path: Path) -> None:
    """THE MEASUREMENT BEHIND THE ARM: it reds loudly, and for a reason that is not the real one."""
    _plant(tmp_path, 'AGENTS.md', 'x' * (_CEILING + 1) + '\n')
    problems = docwidth.width_ratchet(_scan(tmp_path).overwidth, ('AGENTS.md',))
    assert any('ORPHANED' in problem for problem in problems)
    assert any('UNDECLARED' in problem for problem in problems)


# -- THE SHIPPED CONTROL: it passes, and it can fail. -----------------------------------------------


def test_the_shipped_control_passes_over_the_shipped_scanner(tmp_path: Path) -> None:
    assert_the_scanner_still_convicts(tmp_path, ceiling=_CEILING)


def test_the_shipped_control_passes_at_a_tightened_ceiling(tmp_path: Path) -> None:
    """The ceiling is the consumer's, so the boundary must be planted wherever it is drawn."""
    assert_the_scanner_still_convicts(tmp_path, ceiling=40)


def test_the_shipped_control_reds_when_the_comparison_becomes_inclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOCTORED INPUT: `>` turned `>=` is one character and both read as correct.

    Only a line of exactly *ceiling* columns separates them, which is the planting the control makes
    and the line a repo sitting at a measured maximum of 99 would never write by accident.
    """
    real = docwidth.line_widths
    monkeypatch.setattr('lab_commons.dev.docwidth.line_widths', lambda text: tuple((n, w + 1) for n, w in real(text)))
    with pytest.raises(AssertionError, match='exactly AT the ceiling'):
        assert_the_scanner_still_convicts(tmp_path, ceiling=_CEILING)


def test_the_shipped_control_reds_when_a_second_site_in_one_file_is_folded_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reading that turns a SITE ledger into a FILE ledger without anything else changing."""
    real = docwidth.scan_widths

    def _one_per_file(paths: object, **kwargs: object) -> docwidth.WidthScan:
        scan = real(paths, **kwargs)  # type: ignore[arg-type]
        seen: dict[str, docwidth.Overwidth] = {}
        for hit in scan.overwidth:
            seen.setdefault(hit.path, hit)
        return docwidth.WidthScan(
            overwidth=tuple(seen.values()), files_read=scan.files_read, undecodable=scan.undecodable
        )

    monkeypatch.setattr('lab_commons.dev.docwidth.scan_widths', _one_per_file)
    with pytest.raises(AssertionError, match='keyed by file and not by site'):
        assert_the_scanner_still_convicts(tmp_path, ceiling=_CEILING)


def test_the_shipped_control_reds_when_the_ratchet_stops_convicting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ratchet that never fires passes every arm that only ever asks it for silence."""
    monkeypatch.setattr('lab_commons.dev.docwidth.width_ratchet', lambda _overwidth, _declared: ())
    with pytest.raises(AssertionError, match='convicts nothing'):
        assert_the_scanner_still_convicts(tmp_path, ceiling=_CEILING)


def test_an_undecodable_file_is_named_rather_than_counted_as_compliant(tmp_path: Path) -> None:
    """A file that could not be read and one that was read and complies are different facts."""
    (tmp_path / 'AGENTS.md').write_bytes(b'\xff\xfe\x00broken')
    _plant(tmp_path, 'CLAUDE.md', 'short\n')
    scan = _scan(tmp_path)
    assert scan.files_read == 1
    assert scan.undecodable == ('AGENTS.md',)
