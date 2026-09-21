"""The controls for :mod:`lab_commons.dev.famtests.trackedcjk` -- every arm, driven on doctored input.

NO CJK CHARACTER IS WRITTEN INTO THIS FILE EITHER. Every planted one is built with :func:`chr` from
:data:`lab_commons.dev.cjk.CJK_RANGES`, so the ranges stay derived and this test module is itself the
plain-ASCII tracked source its subject is about -- which is the one place a guard like this can
convict the file that tests it.

EVERY SHIPPED ARM IS DRIVEN TWICE: once against a correct reader, where it must pass, and once against
a DOCTORED one, where it must RED. A control asserted only in the first direction has never been shown
to fail, which is the vacuity these bodies exist to refuse one level down. The doctoring is done by
monkeypatching the reader the shipped arm calls, so what is exercised is the shipped arm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import cjk, floors
from lab_commons.dev.famtests.trackedcjk import (
    MisdeclaredWaiver,
    UndeclaredCjk,
    assert_no_undeclared_cjk,
    assert_the_declaration_is_the_shape_the_ratchet_keys_on,
    assert_the_exemptions_match_a_path_segment,
    assert_the_scanner_still_convicts,
    assert_the_source_is_itself_clean,
    take_scan,
)

_CHAR = chr(cjk.CJK_RANGES[2][0])
_PREFIXES = cjk.EXEMPT_PREFIXES
_WHAT = 'NO-CJK-IN-TRACKED-SOURCE'


def _plant(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def _scan(root: Path) -> cjk.Scan:
    return take_scan(sorted(p for p in root.rglob('*') if p.is_file()), root=root, exempt_prefixes=_PREFIXES)


# -- THE VERDICT: the floor first, then the ratchet, in that order. ---------------------------------


def test_a_dirty_file_is_refused_and_declaring_it_clears_the_arm(tmp_path: Path) -> None:
    """The two-sided ratchet, both sides, through the shipped verdict rather than through cjk.ratchet."""
    _plant(tmp_path, 'dirty.md', f'{_CHAR}\n')
    scan = _scan(tmp_path)
    with pytest.raises(UndeclaredCjk, match=r'dirty\.md'):
        assert_no_undeclared_cjk(scan, declared=(), floor=1, headroom=5, what=_WHAT)
    assert_no_undeclared_cjk(scan, declared=('dirty.md',), floor=1, headroom=5, what=_WHAT)


def test_a_waiver_that_outlived_its_file_is_refused_too(tmp_path: Path) -> None:
    """A waiver nothing uses is as wrong as an undeclared offender -- the half a one-sided pin loses."""
    _plant(tmp_path, 'clean.md', 'plain ASCII\n')
    with pytest.raises(UndeclaredCjk, match='ORPHANED'):
        assert_no_undeclared_cjk(_scan(tmp_path), declared=('clean.md',), floor=1, headroom=5, what=_WHAT)


def test_an_empty_declaration_is_legal_and_is_the_state_every_repo_measures(tmp_path: Path) -> None:
    """The fixed state must be reachable: an empty ledger is the goal, not a vacuity to refuse."""
    _plant(tmp_path, 'clean.md', 'plain ASCII\n')
    assert_no_undeclared_cjk(_scan(tmp_path), declared=(), floor=1, headroom=5, what=_WHAT)


def test_an_unread_tree_is_refused_before_the_ratchet_is_consulted(tmp_path: Path) -> None:
    """ORDER IS THE PROPERTY: a walk that reached nothing must not be able to report a clean ratchet."""
    with pytest.raises(floors.FloorUnmet, match=_WHAT):
        assert_no_undeclared_cjk(_scan(tmp_path), declared=(), floor=40, headroom=25, what=_WHAT)


def test_a_floor_the_corpus_outgrew_is_refused_where_no_consumer_refuses_it(tmp_path: Path) -> None:
    """THE SIDE THIS BODY ADDS: 624 files against a floor of 500 refuses only a total collapse."""
    for index in range(30):
        _plant(tmp_path, f'f{index}.md', 'plain ASCII\n')
    with pytest.raises(floors.SlackFloor, match=_WHAT):
        assert_no_undeclared_cjk(_scan(tmp_path), declared=(), floor=2, headroom=5, what=_WHAT)


def test_the_label_reaches_the_refusal_so_a_reader_is_not_sent_to_the_wrong_guard(tmp_path: Path) -> None:
    """``what`` has no default here precisely because ``cjk.assert_floor`` has one that misdirects."""
    with pytest.raises(floors.FloorUnmet) as caught:
        assert_no_undeclared_cjk(_scan(tmp_path), declared=(), floor=9, headroom=5, what='A-SECOND-SCAN')
    assert 'A-SECOND-SCAN' in str(caught.value)


# -- THE DECLARATION SHAPE: the failure that reds loudly for the wrong reason. ----------------------


@pytest.mark.parametrize(
    'entry',
    ['docs/page.md:12', 'docs\\page.md', './docs/page.md', '/docs/page.md'],
)
def test_a_waiver_the_ratchet_cannot_key_on_is_refused(entry: str) -> None:
    """Each wrong shape ORPHANS rather than matching, so the arm still fires and says the wrong thing."""
    with pytest.raises(MisdeclaredWaiver, match='cannot key'):
        assert_the_declaration_is_the_shape_the_ratchet_keys_on([entry])


def test_a_correctly_spelled_waiver_and_an_empty_set_both_pass() -> None:
    """The green direction, including the empty ledger every repo in this family currently holds."""
    assert_the_declaration_is_the_shape_the_ratchet_keys_on(['docs/page.md', 'src/pkg/mod.py'])
    assert_the_declaration_is_the_shape_the_ratchet_keys_on([])


def test_a_misdeclared_waiver_really_does_only_orphan(tmp_path: Path) -> None:
    """THE MEASUREMENT BEHIND THE ARM, asserted rather than claimed in its docstring."""
    _plant(tmp_path, 'dirty.md', f'{_CHAR}\n')
    problems = cjk.ratchet(_scan(tmp_path).occurrences, ['dirty.md:1'])
    assert any('ORPHANED' in problem for problem in problems), 'the line-keyed waiver must fail to match'
    assert any('UNDECLARED' in problem for problem in problems), 'and the real offender stays undeclared'


# -- THE EXEMPTIONS: nested, rooted, and not a substring. -------------------------------------------


def test_the_shipped_exemption_arm_passes_over_the_shipped_prefixes() -> None:
    assert_the_exemptions_match_a_path_segment(_PREFIXES)


def test_the_exemption_arm_reds_when_the_matcher_is_doctored(monkeypatch: pytest.MonkeyPatch) -> None:
    """DOCTORED INPUT, the direction that matters: a substring matcher excuses a tree nobody named."""
    monkeypatch.setattr(
        'lab_commons.dev.cjk.exempted',
        lambda name, prefixes=_PREFIXES: any(prefix.rstrip('/') in name for prefix in prefixes),
    )
    with pytest.raises(AssertionError, match='substring'):
        assert_the_exemptions_match_a_path_segment(_PREFIXES)


def test_the_exemption_arm_reds_when_nesting_is_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opposite doctoring: a root-only match, which reported 47,521 phantom characters once."""
    monkeypatch.setattr(
        'lab_commons.dev.cjk.exempted',
        lambda name, prefixes=_PREFIXES: any(name.startswith(prefix) for prefix in prefixes),
    )
    with pytest.raises(AssertionError, match='nested path SEGMENT'):
        assert_the_exemptions_match_a_path_segment(_PREFIXES)


# -- THE SHIPPED CONTROL: it passes, and it can fail. -----------------------------------------------


def test_the_shipped_control_passes_over_the_shipped_scanner(tmp_path: Path) -> None:
    assert_the_scanner_still_convicts(tmp_path, exempt_prefixes=_PREFIXES)


def test_the_shipped_control_refuses_an_empty_exemption_set(tmp_path: Path) -> None:
    """A control handed nothing to exercise would pass in triumph, so it refuses instead."""
    with pytest.raises(AssertionError, match='no exempt prefixes'):
        assert_the_scanner_still_convicts(tmp_path, exempt_prefixes=())


def test_the_shipped_control_reds_when_the_scanner_finds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRIVE THE REAL ARM ON A DOCTORED READER AND ASSERT IT REDS, before trusting that it works."""
    monkeypatch.setattr('lab_commons.dev.cjk.find_cjk', lambda _text, _ranges=None: ())
    with pytest.raises(AssertionError, match='planted offender'):
        assert_the_scanner_still_convicts(tmp_path, exempt_prefixes=_PREFIXES)


def test_the_shipped_control_reds_when_an_exemption_stops_being_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second doctoring: an excused file folded silently into the clean result rather than named."""
    real = cjk.scan_files

    def _forgetful(paths, **kwargs):  # noqa: ANN003, ANN202 -- a stand-in for one shipped signature
        scan = real(paths, **kwargs)
        return cjk.Scan(
            occurrences=scan.occurrences,
            files_read=scan.files_read,
            exempted=(),
            undecodable=scan.undecodable,
        )

    monkeypatch.setattr('lab_commons.dev.cjk.scan_files', _forgetful)
    with pytest.raises(AssertionError, match='exempt file is missing'):
        assert_the_scanner_still_convicts(tmp_path, exempt_prefixes=_PREFIXES)


def test_the_control_leaves_the_escape_sequence_alone(tmp_path: Path) -> None:
    """THE IRONY ARM: a backslash-u escape is the remedy this family recommends and must pass on its own.

    Asserted directly as well as inside the shipped control, because it is the one distinction whose
    loss would make the guard refuse its own documented repair -- the reader would then be told to
    write a shape the scanner convicts.
    """
    _plant(tmp_path, 'escaped.py', 'REJECTED = "\\u4e00"\n')
    assert _scan(tmp_path).occurrences == ()


# -- THE MODULE'S OWN SOURCE, and this file's with it. ----------------------------------------------


def test_the_shipped_module_carries_no_cjk_of_its_own() -> None:
    assert_the_source_is_itself_clean(also=(Path(__file__),))


def test_the_consumer_file_handed_in_is_scanned_beside_the_kit_module(tmp_path: Path) -> None:
    """THE HALF THE KIT COULD NOT SEE, and the reason `also` has no default.

    Resolving `Path(__file__)` inside the kit scans the kit's own module and nothing else, so every
    consumer wrote the same six lines beside the call to cover ITSELF. A non-ASCII character in the
    consumer's file is a literal the guard would convict if that file ever sat inside the scanned
    tree -- and it does not, which is the whole reason this argument exists.
    """
    clean = tmp_path / 'test_guard.py'
    clean.write_text('REJECTED = "\\u4e00"  # the remedy, in eight ASCII characters\n', encoding='utf-8')
    assert_the_source_is_itself_clean(also=(clean,))
    dirty = tmp_path / 'test_dirty.py'
    dirty.write_text(f'REJECTED = "{_CHAR}"\n', encoding='utf-8')
    assert not dirty.read_text(encoding='utf-8').isascii(), 'the plant must be a real non-ASCII character'
    with pytest.raises(AssertionError, match=r'test_dirty\.py'):
        assert_the_source_is_itself_clean(also=(dirty,))


def test_the_consumer_path_is_required_and_has_no_default_to_fall_back_on() -> None:
    """NO DEFAULT: a body that guessed would report the kit's answer as the repo's."""
    with pytest.raises(TypeError):
        assert_the_source_is_itself_clean()  # type: ignore[call-arg]


def test_this_control_file_carries_no_cjk_either() -> None:
    """The arm the shipped one cannot make: a control planting a real character must stay ASCII too."""
    assert cjk.find_cjk(Path(__file__).read_text(encoding='utf-8')) == ()


def test_the_planted_character_really_is_in_the_shared_ranges() -> None:
    """A control planting something the ranges do not cover would be green and prove nothing."""
    assert cjk.is_cjk(_CHAR), 'the planted code point must be derived from CJK_RANGES, never typed'
