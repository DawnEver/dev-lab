r"""The family config base, its renderer, and the guard that refuses a hand-edited rendering.

EVERY PROPERTY HERE IS PLANTED, and that is the only way this file could be worth anything. A guard
over generated files has one failure mode -- it agrees with whatever it finds -- so a suite that only
rendered a file and then read it back would pass against a guard that returns ``INSTALLED``
unconditionally. So each arm writes a file, BREAKS it in one specific way, and asserts the REAL
function names that way; and the clean control beside it proves the same function can still pass, so
neither direction is vacuous on its own.

THE RATCHET IS TESTED FROM BOTH SIDES, because a one-sided ratchet is the shape this family refuses:

* a base line cannot silently vanish -- `test_planted_a_deleted_base_line_reds` and, for the weaker
  mode, `test_planted_a_missing_required_target_reds`;
* a delta cannot silently grow into a fork -- `test_a_delta_that_restates_a_base_line_is_refused`,
  `test_a_delta_past_its_ceiling_is_refused`, and `test_planted_a_line_every_delta_adds_is_named`;
* a base cannot acquire a line it is unable to PLACE --
  `test_planted_a_re_ignore_promoted_into_the_base_is_refused_and_named` against
  `test_an_ordinary_line_is_still_promotable_into_the_same_base`. That pair is the one this file was
  missing: the anti-fork arm above argues FOR promoting a line every consumer holds, and for a
  last-match-wins artefact that argument is sometimes wrong, so the two arms disagree on purpose and
  both directions are planted.

The floors are the third property. `assert_base_floor` and `fork_signals` each refuse a reading below
one, and both refusals have their own test, because a floor that is never exercised is a floor
nobody would notice the deletion of.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev._famconfig_rows import (
    GITIGNORE_BASE,
    MAKE_TARGET_CONSUMER_CORE,
    MAKEFILE_BASE,
    MAKEFILE_RESIDUAL_SIGNALS,
    PRECOMMIT_BASE,
)
from lab_commons.dev.famconfig import (
    ABSENT,
    BASES,
    DRIFTED,
    FOREIGN,
    GITIGNORE_FLOOR,
    HOOK_ID_CORE,
    INSTALLED,
    MAKE_TARGET_CORE,
    ORDER_SENSITIVE_ARTEFACTS,
    RENDERED,
    REPO_FLOOR,
    REQUIRED,
    STAMP,
    Base,
    Delta,
    ForkedDelta,
    PositionalBase,
    VacuousBase,
    artefact_base,
    assert_base_floor,
    assert_base_is_order_free,
    delta_problems,
    floating_subject,
    fork_signals,
    inspect_file,
    measured_delta,
    positional_base_lines,
    render,
    rendered_lines,
    satisfies,
)

#: The measured three-way intersection, 2026-09-17. Pinned as a COUNT beside the named lines below
#: rather than instead of them: the count says the table was not quietly halved, the names say which.
GITIGNORE_LINES = 14

#: How many artefacts the family declares. A floor -- a `BASES` that read empty would make every
#: parametrized arm below pass over nothing at all.
ARTEFACT_FLOOR = 3


def _base() -> Base:
    return artefact_base('.gitignore')


def _delta(added: tuple[str, ...] = ('target/', 'htmlcov/'), ceiling: int = 4) -> Delta:
    return Delta(repo='planted-repo', added=added, dropped={}, ceiling=ceiling)


# ----------------------------------------------------------------- the base is what was measured


def test_the_gitignore_base_is_the_measured_intersection() -> None:
    """The 14 patterns, by NAME and by count -- a count alone cannot say WHICH line left."""
    assert len(GITIGNORE_BASE) == GITIGNORE_LINES
    assert_base_floor(len(GITIGNORE_BASE), GITIGNORE_FLOOR, '.gitignore')
    assert 'uv.lock' in GITIGNORE_BASE, 'the ruling of 2026-09-17 keeps the lockfile out of git'
    assert '.venv*' in GITIGNORE_BASE
    assert sorted(GITIGNORE_BASE) == list(GITIGNORE_BASE), 'sorted, so the measurement is re-derivable'


def test_every_shared_hook_id_survives_into_the_rendered_precommit_base() -> None:
    """The base's SUBJECT checked against its SPELLING: valid YAML that lost a hook would be green."""
    assert len(HOOK_ID_CORE) >= ARTEFACT_FLOOR
    text = '\n'.join(PRECOMMIT_BASE)
    missing = [hook for hook in HOOK_ID_CORE if f'id: {hook}' not in text]
    assert missing == [], f'the pre-commit base no longer declares {missing}'


def test_every_shared_make_target_survives_into_the_makefile_base() -> None:
    """Same property, other artefact -- and over BOTH readings, the all-four core and the wider one.

    The consumer core is what the base actually takes; the all-four core is checked too because it is
    a subset of it, so a base that lost `fmt` would red on both and a base that lost `clean` on one.
    """
    assert len(MAKE_TARGET_CORE) >= ARTEFACT_FLOOR
    assert set(MAKE_TARGET_CORE) <= set(MAKE_TARGET_CONSUMER_CORE)
    missing = [
        target for target in (*MAKE_TARGET_CORE, *MAKE_TARGET_CONSUMER_CORE) if f'{target}:' not in MAKEFILE_BASE
    ]
    assert missing == [], f'the Makefile base no longer requires {missing}'


def test_the_residual_fork_signals_are_named_and_stay_out_of_the_base() -> None:
    """A signal the base declines has to be accounted for, or it rots into noise nobody reads.

    Two-sided: each residual is recorded, and none of them has quietly been promoted into the base
    without the reason for declining it being deleted in the same edit.
    """
    assert len(MAKEFILE_RESIDUAL_SIGNALS) >= ARTEFACT_FLOOR
    promoted = [line for line in MAKEFILE_RESIDUAL_SIGNALS if line in MAKEFILE_BASE]
    assert promoted == [], f'{promoted} is both declined and taken -- delete the residual row with the decision'


def test_the_precommit_base_declares_the_line_every_consumer_holds() -> None:
    """`fail_fast: false` is in the base because the anti-fork arm named it on its first live run."""
    assert 'fail_fast: false' in PRECOMMIT_BASE


def test_every_declared_artefact_has_a_mode_and_a_non_empty_base() -> None:
    """A base that read empty renders a file everything passes against."""
    assert len(BASES) >= ARTEFACT_FLOOR
    for name, base in BASES.items():
        assert base.artefact == name
        assert base.mode in {RENDERED, REQUIRED}, f'{name} declares mode {base.mode!r}'
        assert_base_floor(len(base.lines), 1, name)


def test_an_artefact_with_no_base_is_refused_by_name() -> None:
    """`[tool.ruff]` is deliberately not here, and asking for it says so rather than returning None."""
    with pytest.raises(ForkedDelta, match='no family base'):
        artefact_base('ruff.toml')


# ------------------------------------------------------------------------- render and inspect


def test_a_freshly_rendered_file_inspects_as_installed(tmp_path: Path) -> None:
    """THE CONTROL. Without it every planted arm below would pass against a guard that always reds."""
    base, delta = _base(), _delta()
    path = tmp_path / '.gitignore'
    path.write_text(render(base, delta), encoding='utf-8')
    report = inspect_file(path, base, delta)
    assert report.status == INSTALLED, report.detail
    assert report.ok
    assert report.offending == ()


def test_the_rendering_carries_its_provenance_and_both_halves(tmp_path: Path) -> None:
    """Stamp, every base line, and the delta -- and no date or digest that could itself go stale."""
    text = render(_base(), _delta())
    assert STAMP in text
    for line in GITIGNORE_BASE:
        assert f'\n{line}\n' in text, f'{line} did not reach the rendering'
    assert 'target/' in text
    (tmp_path / 'unused').write_text(text, encoding='utf-8')


def test_planted_a_hand_edited_line_reds_as_drifted(tmp_path: Path) -> None:
    """PLANTED: one base line rewritten in place -- exactly the edit the seam exists to catch."""
    base, delta = _base(), _delta()
    path = tmp_path / '.gitignore'
    path.write_text(render(base, delta).replace('.venv*', '.venv-local'), encoding='utf-8')
    report = inspect_file(path, base, delta)
    assert report.status == DRIFTED, report.detail
    assert 'missing: .venv*' in report.offending
    assert 'unexpected: .venv-local' in report.offending


def test_planted_a_deleted_base_line_reds(tmp_path: Path) -> None:
    """THE RATCHET'S FIRST SIDE: a base line cannot leave a rendered file without a declared drop."""
    base, delta = _base(), _delta()
    path = tmp_path / '.gitignore'
    kept = [line for line in render(base, delta).splitlines() if line != 'uv.lock']
    path.write_text('\n'.join(kept) + '\n', encoding='utf-8')
    report = inspect_file(path, base, delta)
    assert report.status == DRIFTED, report.detail
    assert 'missing: uv.lock' in report.offending


def test_planted_an_unstamped_file_reds_as_foreign_rather_than_drifted(tmp_path: Path) -> None:
    """PLANTED: somebody's own file. Rendering over it would clobber it, so it gets its own answer."""
    base, delta = _base(), _delta()
    path = tmp_path / '.gitignore'
    path.write_text('*.pyc\nbuild/\n', encoding='utf-8')
    report = inspect_file(path, base, delta)
    assert report.status == FOREIGN, report.detail
    assert 'clobber' in report.detail


def test_a_missing_file_is_absent_rather_than_clean(tmp_path: Path) -> None:
    """The third answer. An unwritten artefact guarantees nothing, which is not the same as passing."""
    report = inspect_file(tmp_path / '.gitignore', _base(), _delta())
    assert report.status == ABSENT
    assert not report.ok


# ------------------------------------------------------------------- what a delta may express


def test_a_declared_drop_renders_its_reason_and_still_installs(tmp_path: Path) -> None:
    """A REMOVAL IS VISIBLE IN THE FILE, which is what distinguishes it from a drift on disk."""
    base = _base()
    delta = Delta(repo='planted-repo', added=(), dropped={'*.c': 'this repo builds no Cython'}, ceiling=0)
    path = tmp_path / '.gitignore'
    text = render(base, delta)
    path.write_text(text, encoding='utf-8')
    assert '# dropped from the base by planted-repo: *.c -- this repo builds no Cython' in text
    assert inspect_file(path, base, delta).status == INSTALLED


def test_a_drop_naming_a_line_the_base_does_not_have_is_refused() -> None:
    """THE RATCHET'S OTHER SIDE ON DROPS: a waiver cannot outlive the thing it waived."""
    delta = Delta(repo='planted-repo', added=(), dropped={'node_modules/': 'gone upstream'}, ceiling=0)
    problems = delta_problems(_base(), delta)
    assert any('does not have that line' in problem for problem in problems), problems
    with pytest.raises(ForkedDelta, match='does not have that line'):
        render(_base(), delta)


def test_a_drop_with_an_empty_reason_is_refused() -> None:
    """A reasonless drop is a drift with a declaration pinned to it, and reads as a decision."""
    delta = Delta(repo='planted-repo', added=(), dropped={'*.c': '   '}, ceiling=0)
    with pytest.raises(ForkedDelta, match='empty reason'):
        render(_base(), delta)


def test_a_delta_that_restates_a_base_line_is_refused() -> None:
    """THE FORK SEED: the base copied into the delta, where re-rendering no longer guards it."""
    delta = Delta(repo='planted-repo', added=('uv.lock',), dropped={}, ceiling=4)
    with pytest.raises(ForkedDelta, match='the base already has it'):
        render(_base(), delta)


def test_a_delta_past_its_ceiling_is_refused() -> None:
    """An escape hatch needs a CEILING rather than a reason, and this is where the ceiling bites."""
    delta = Delta(repo='planted-repo', added=('a/', 'b/', 'c/'), dropped={}, ceiling=2)
    with pytest.raises(ForkedDelta, match='past its ceiling'):
        render(_base(), delta)


# ------------------------------------------------------------------------ the REQUIRED mode


def _makefile(targets: tuple[str, ...]) -> str:
    recipes = {'lint:': '\truff check .', 'fmt:': '\truff format .', 'test:': '\tpytest'}
    body = [line for target in targets for line in (target, recipes.get(target, '\tpython -m lab_commons.dev.verify'))]
    return '\n'.join(body) + '\n'


def test_a_target_header_is_satisfied_by_its_prerequisites_and_nothing_looser() -> None:
    """THE FALSE POSITIVE THIS CLOSES, and the arm that stops the fix from becoming a substring test.

    Measured on the live consumers, a literal comparison called `all:` absent from all three, because
    a Makefile target carries its prerequisites on the same line. So a header matches by prefix. The
    second half is what keeps that honest: `alligator:` does not satisfy `all:`, and a recipe line is
    still compared byte for byte, because a recipe is the half that is genuinely portable or not.
    """
    assert satisfies('all:', ('all: install-dev lint test',))
    assert satisfies('all:', ('all:',))
    assert not satisfies('all:', ('alligator: x',))
    assert not satisfies('all:', ('install: all',))
    assert satisfies('	python -m lab_commons.dev.verify', ('	python -m lab_commons.dev.verify',))
    assert not satisfies('	python -m lab_commons.dev.verify', ('	python -m lab_commons.dev.verify --fast',))


def test_a_makefile_holding_every_base_target_installs(tmp_path: Path) -> None:
    """THE CONTROL for the weaker mode: recipes differ per repo and the contract still holds."""
    base = artefact_base('Makefile')
    assert base.mode == REQUIRED
    path = tmp_path / 'Makefile'
    path.write_text(_makefile(tuple(base.lines)), encoding='utf-8')
    report = inspect_file(path, base, Delta(repo='planted-repo', added=(), dropped={}, ceiling=0))
    assert report.status == INSTALLED, report.detail


def test_planted_a_missing_required_target_reds(tmp_path: Path) -> None:
    """PLANTED: `verify` dropped from the Makefile -- the exact state motronics is in today."""
    base = artefact_base('Makefile')
    path = tmp_path / 'Makefile'
    path.write_text(_makefile(('lint:', 'fmt:', 'test:')), encoding='utf-8')
    report = inspect_file(path, base, Delta(repo='planted-repo', added=(), dropped={}, ceiling=0))
    assert report.status == DRIFTED, report.detail
    assert 'verify:' in report.offending


def test_planted_a_declared_drop_that_the_file_contradicts_reds(tmp_path: Path) -> None:
    """A declaration that lies, in its cheapest form: the drop says gone and the file says here."""
    base = artefact_base('Makefile')
    delta = Delta(repo='planted-repo', added=(), dropped={'verify:': 'this repo has its own gate'}, ceiling=0)
    path = tmp_path / 'Makefile'
    path.write_text(_makefile(tuple(base.lines)), encoding='utf-8')
    report = inspect_file(path, base, delta)
    assert report.status == DRIFTED, report.detail
    assert 'verify:' in report.offending


# --------------------------------------------------------------------- survey and anti-fork


def test_a_measured_delta_round_trips_an_unmanaged_file(tmp_path: Path) -> None:
    """The adoption lane's instrument: read a consumer's file, render it back, and it installs."""
    base = _base()
    path = tmp_path / '.gitignore'
    path.write_text('\n'.join([*GITIGNORE_BASE[:-2], 'target/', 'usr/']) + '\n', encoding='utf-8')
    delta = measured_delta(path, base, 'planted-repo')
    assert delta.added == ('target/', 'usr/')
    assert set(delta.dropped) == set(GITIGNORE_BASE[-2:])
    path.write_text(render(base, delta), encoding='utf-8')
    assert inspect_file(path, base, delta).status == INSTALLED


def test_planted_a_line_every_delta_adds_is_named() -> None:
    """THE ANTI-FORK ARM: three repos adding one line is a base line that was never promoted."""
    deltas = [
        Delta(repo='a', added=('htmlcov/', 'target/'), dropped={}, ceiling=4),
        Delta(repo='b', added=('htmlcov/', 'usr/'), dropped={}, ceiling=4),
        Delta(repo='c', added=('htmlcov/', 'attic/'), dropped={}, ceiling=4),
    ]
    signals = fork_signals(deltas)
    assert len(signals) == 1
    assert 'htmlcov/' in signals[0]
    assert fork_signals([*deltas[:2], Delta(repo='c', added=('attic/',), dropped={}, ceiling=4)]) == ()


def test_a_fork_scan_below_its_floor_refuses() -> None:
    """Finding nothing across one delta is vacuous, so it raises instead of reporting agreement."""
    with pytest.raises(VacuousBase, match='below the'):
        fork_signals([Delta(repo='a', added=('x/',), dropped={}, ceiling=1)])
    assert REPO_FLOOR >= ARTEFACT_FLOOR


def test_a_base_below_its_floor_refuses() -> None:
    """The floor's own control -- a floor never exercised is one nobody notices the deletion of."""
    with pytest.raises(VacuousBase, match='below the 10 floor'):
        assert_base_floor(2, GITIGNORE_FLOOR, '.gitignore')


def test_rendered_lines_and_render_agree() -> None:
    """One rendering, two spellings: the text form is the line form joined, never a second answer."""
    base, delta = _base(), _delta()
    assert render(base, delta) == '\n'.join(rendered_lines(base, delta)) + '\n'


# ------------------------------------------ the nested addition, and what it did NOT turn out to be

#: wdg-lab's seven extra `pre-commit-hooks` ids, MEASURED 2026-09-17 from that repo's own
#: `tests/architecture/_famconfig.py::EXTRA_HOOK_IDS`. They are the real subject: every one of them
#: belongs INSIDE the entry the base renders, which is the position an append cannot reach.
_EXTRA_HOOK_IDS: Final = (
    'check-builtin-literals',
    'check-illegal-windows-names',
    'check-symlinks',
    'check-vcs-permalinks',
    'destroyed-symlinks',
    'fix-byte-order-marker',
    'requirements-txt-fixer',
)

#: The `exclude:` wdg-lab must hang on `trailing-whitespace` -- a CHILD of a base line rather than a
#: sibling of the block, and the second shape an append cannot express.
_EXCLUDE = r'        exclude: ^tests/architecture/_suppressions\.tsv$'

#: The two anchors, both MEASURED unique in the base by the first test below before they are used.
_ID_ANCHOR: Final = '      - id: check-added-large-files'
_TW_ANCHOR: Final = '      - id: trailing-whitespace'


def _precommit() -> Base:
    """The real `.pre-commit-config.yaml` base -- the artefact both labs are blocked on."""
    return artefact_base('.pre-commit-config.yaml')


def _nested() -> Delta:
    """wdg-lab's blocked delta, expressed as anchored additions rather than as an append."""
    return Delta(
        repo='wdg-lab',
        added=(),
        dropped={},
        ceiling=8,
        anchored={
            _ID_ANCHOR: tuple(f'      - id: {hook_id}' for hook_id in _EXTRA_HOOK_IDS),
            _TW_ANCHOR: (_EXCLUDE,),
        },
    )


def test_the_precommit_base_really_does_repeat_its_structural_lines() -> None:
    """THE FLOOR UNDER THE WHOLE SECTION. Finding no collision would make every arm below vacuous."""
    base = _precommit()
    assert base.lines.count('    hooks:') == 2, base.lines
    assert base.lines.count('') >= 1, 'no blank base line, so the content_lines distinction has no subject'
    assert base.lines.count(_ID_ANCHOR) == 1, 'the id anchor is not unique, so anchoring on it is ambiguous'
    assert base.lines.count(_TW_ANCHOR) == 1, 'the trailing-whitespace anchor is not unique'


def test_a_blank_base_line_is_not_a_restatement() -> None:
    """DEFECT 1. `delta_problems` was the module's ONE reader of `base.lines`; a blank is LAYOUT.

    `content_lines` exists for exactly this distinction and every other site already reads it. A
    blank cannot be the base copied into the delta, because it carries nothing to copy.
    """
    base = _precommit()
    assert '' in base.lines, 'no blank base line to plant against'
    assert '' not in base.content_lines
    problems = delta_problems(base, Delta(repo='planted-repo', added=('',), dropped={}, ceiling=4))
    assert not [problem for problem in problems if 'already has it' in problem], problems


def test_restating_a_structural_content_line_is_still_refused_and_the_refusal_names_the_anchor() -> None:
    """DEFECT 1 IS NOT THE ADOPTION FIX, and this arm is the measurement that says so.

    `    hooks:` is a CONTENT line, so reading `content_lines` instead of `lines` leaves it refused --
    correctly, since a second copy of the block is the base re-forming inside the delta. What changes
    is that the refusal now NAMES the remedy instead of failing opaquely.
    """
    base = _precommit()
    delta = Delta(repo='planted-repo', added=('    hooks:',), dropped={}, ceiling=4)
    problems = delta_problems(base, delta)
    assert any('already has it' in problem for problem in problems), problems
    assert any('anchored' in problem for problem in problems), problems
    with pytest.raises(ForkedDelta, match='already has it'):
        render(base, delta)


def test_the_real_blocked_delta_is_expressible_and_lands_inside_the_block() -> None:
    """DEFECT 2. The seven extra ids and the `exclude:` go where they belong, restating nothing."""
    base, delta = _precommit(), _nested()
    assert delta_problems(base, delta) == (), delta_problems(base, delta)
    lines = rendered_lines(base, delta)
    commitizen = lines.index('  - repo: https://github.com/commitizen-tools/commitizen')
    for hook_id in _EXTRA_HOOK_IDS:
        assert lines.index(f'      - id: {hook_id}') < commitizen, f'{hook_id} landed outside the block'
    assert lines[lines.index(_TW_ANCHOR) + 2] == _EXCLUDE, lines
    assert _EXCLUDE not in base.content_lines, 'the delta must restate nothing'


def test_a_nested_delta_round_trips_and_a_hand_edit_to_an_anchored_line_reds(tmp_path: Path) -> None:
    """PLANTED, BOTH DIRECTIONS. The rendering installs, and breaking one anchored line drifts."""
    base, delta = _precommit(), _nested()
    path = tmp_path / '.pre-commit-config.yaml'
    path.write_text(render(base, delta), encoding='utf-8')
    assert inspect_file(path, base, delta).status == INSTALLED

    path.write_text(path.read_text(encoding='utf-8').replace('check-symlinks', 'check-symlinkz'), encoding='utf-8')
    edited = inspect_file(path, base, delta)
    assert edited.status == DRIFTED, edited
    assert any('check-symlinks' in line for line in edited.offending), edited.offending


def test_an_anchor_naming_a_line_the_base_does_not_have_is_refused() -> None:
    """THE ANCHOR'S RATCHET, the same side as a drop's: a declaration cannot outlive its subject."""
    delta = Delta(repo='planted-repo', added=(), dropped={}, ceiling=4, anchored={'      - id: gone': ('x',)})
    with pytest.raises(ForkedDelta, match='the base does not have that line'):
        render(_precommit(), delta)


def test_an_ambiguous_anchor_is_refused_by_count() -> None:
    """A base line that occurs twice names no position, and silently picking one is a coin flip."""
    delta = Delta(repo='planted-repo', added=(), dropped={}, ceiling=4, anchored={'    hooks:': ('      - id: x',)})
    with pytest.raises(ForkedDelta, match='2 times'):
        render(_precommit(), delta)


def test_an_anchor_on_a_dropped_line_is_refused() -> None:
    """The two declarations contradict: one says the line goes, the other hangs content off it."""
    delta = Delta(
        repo='planted-repo',
        added=(),
        dropped={_TW_ANCHOR: 'this repo does not run it'},
        ceiling=4,
        anchored={_TW_ANCHOR: (_EXCLUDE,)},
    )
    with pytest.raises(ForkedDelta, match='drops it and anchors'):
        render(_precommit(), delta)


def test_an_anchor_carrying_no_lines_is_refused() -> None:
    """A ratchet's other side: an anchor that adds nothing is a waiver nothing uses."""
    delta = Delta(repo='planted-repo', added=(), dropped={}, ceiling=4, anchored={_TW_ANCHOR: ()})
    with pytest.raises(ForkedDelta, match='anchors no lines'):
        render(_precommit(), delta)


def test_anchored_lines_count_against_the_ceiling() -> None:
    """Otherwise the ceiling is escapable by anchoring, which is an escape hatch with no ceiling."""
    delta = Delta(repo='planted-repo', added=(), dropped={}, ceiling=2, anchored={_TW_ANCHOR: (_EXCLUDE, 'a', 'b')})
    with pytest.raises(ForkedDelta, match='past its ceiling'):
        render(_precommit(), delta)
    assert delta_problems(_precommit(), _nested()) == ()


def test_fork_signals_names_a_line_every_delta_anchors() -> None:
    """The anti-fork arm reads the WHOLE delta: a line hidden in an anchor is still a shared line."""
    deltas = [
        Delta(repo=name, added=(f'{name}/',), dropped={}, ceiling=4, anchored={_TW_ANCHOR: (_EXCLUDE,)})
        for name in ('a', 'b', 'c')
    ]
    signals = fork_signals(deltas)
    assert len(signals) == 1, signals
    assert repr(_EXCLUDE) in signals[0], signals


#: THE RE-IGNORE, lifted verbatim from a sibling repo's live `.gitignore` where it sits at line 108,
#: below the `!**/.claude/memory/**` negation at line 85 that re-included the cache the base rule at
#: line 8 had excluded. That file records the incident in its own comment: a `.pyc` under
#: `.claude/memory/` was TRACKED in 2026-08, and "a bare `**/__pycache__/` here would sit BEFORE
#: nothing and change nothing; these must follow the negations to win."
_RE_IGNORE: Final = '**/.claude/**/__pycache__/'

#: THE CONTROL IN THE OTHER DIRECTION, and it is the half that stops this arm being a refusal of every
#: promotion. `**/.DS_Store` is an ordinary family candidate: no base rule already matches it, so it
#: means the same wherever it renders and the sorted table can carry it.
_ORDINARY: Final = '**/.DS_Store'


def _promoted(line: str) -> Base:
    """The live `.gitignore` base with *line* promoted into it, sorted exactly as the table is."""
    return Base('.gitignore', tuple(sorted((*GITIGNORE_BASE, line))), RENDERED)


def test_planted_a_re_ignore_promoted_into_the_base_is_refused_and_named() -> None:
    """THE PROMOTION HAZARD, planted with the real line from the incident that proves it.

    `fork_signals` would argue FOR this promotion -- it is a line a consumer's delta holds -- and the
    renderer would place it ABOVE every negation, so the `.pyc` goes back to being tracked with the
    file reading as more strictly ignored than before. Nothing else in this package can see that: the
    bytes render exactly as declared and every base line is present.
    """
    with pytest.raises(PositionalBase, match=r'\*\*/\.claude/\*\*/__pycache__/'):
        rendered_lines(_promoted(_RE_IGNORE), _delta())


def test_the_refusal_names_the_remedy_rather_than_only_the_defect() -> None:
    """A refusal that cannot be acted on is one that gets routed around."""
    with pytest.raises(PositionalBase, match='BELOW the negation it closes'):
        assert_base_is_order_free(_promoted(_RE_IGNORE))


def test_an_ordinary_line_is_still_promotable_into_the_same_base() -> None:
    """THE CONTROL. A guard that refused every promotion would report what a frozen table reports."""
    assert positional_base_lines(_promoted(_ORDINARY), floating_floor=2) == ()
    assert_base_is_order_free(_promoted(_ORDINARY))
    assert _ORDINARY in rendered_lines(_promoted(_ORDINARY), _delta())


def test_the_live_base_is_order_free_today_and_the_scan_was_not_empty() -> None:
    """THE FLOOR. Two floating rules here; a reading that found none subsumes nothing, vacuously."""
    floating = tuple(line for line in _base().content_lines if floating_subject(line))
    assert floating == ('**/.env', '**/__pycache__/'), floating
    assert positional_base_lines(_base(), floating_floor=len(floating)) == ()


def test_a_base_with_no_floating_rule_is_refused_rather_than_reported_clean() -> None:
    """The floor's own arm: finding no subsumption in a table with nothing to subsume is not green."""
    with pytest.raises(VacuousBase, match='floating-rule'):
        positional_base_lines(Base('.gitignore', ('dist/', 'build/'), RENDERED), floating_floor=2)


def test_a_rule_carrying_its_own_path_is_not_a_floating_subject() -> None:
    """`**/log/*.log` is about a LOCATION, so a deeper rule genuinely narrows it and may be promoted."""
    assert floating_subject('**/__pycache__/') == '/__pycache__/'
    assert floating_subject('**/.env') == '/.env'
    assert floating_subject('**/log/*.log') is None
    assert floating_subject('**/temp/**') is None
    assert floating_subject('.pytest_cache/') is None


def test_the_order_sensitive_set_is_named_rather_than_counted() -> None:
    """A base outside the map is DECLARED order-insensitive; adding one is a decision with a floor."""
    assert set(ORDER_SENSITIVE_ARTEFACTS) == {'.gitignore'}, ORDER_SENSITIVE_ARTEFACTS
    assert set(ORDER_SENSITIVE_ARTEFACTS) <= set(BASES), 'a declaration that outlived its subject'
    assert all(floor >= 1 for floor in ORDER_SENSITIVE_ARTEFACTS.values()), 'a floor of zero is no floor'
