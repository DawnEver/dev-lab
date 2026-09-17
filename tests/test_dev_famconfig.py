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
  `test_a_delta_past_its_ceiling_is_refused`, and `test_planted_a_line_every_delta_adds_is_named`.

The floors are the third property. `assert_base_floor` and `fork_signals` each refuse a reading below
one, and both refusals have their own test, because a floor that is never exercised is a floor
nobody would notice the deletion of.
"""

from __future__ import annotations

from pathlib import Path

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
    RENDERED,
    REPO_FLOOR,
    REQUIRED,
    STAMP,
    Base,
    Delta,
    ForkedDelta,
    VacuousBase,
    artefact_base,
    assert_base_floor,
    delta_problems,
    fork_signals,
    inspect_file,
    measured_delta,
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
