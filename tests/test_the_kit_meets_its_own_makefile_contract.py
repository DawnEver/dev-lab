r"""THE KIT MEETS THE Makefile CONTRACT IT PUBLISHES, and until 2026-09-18 it was the only repo that did not.

WHAT WAS WRONG. `lab_commons.dev._famconfig_rows.MAKEFILE_BASE` is a target CONTRACT -- nine headers
plus the one recipe that is genuinely portable, `python -m lab_commons.dev.verify` -- measured across
four repos. This repo declared no Makefile delta and met five of the nine: `all`, `clean`, `install`,
`install-dev` and `test-parallel` were absent, and `verify` ran a hand-written `lint fmt-check test`
chain rather than the module this package ships for exactly that job. The repo publishing the
contract was the one repo outside it, which is the shape the config census found at every layer.

WHY THIS IS A SEPARATE MODULE FROM THE PRE-COMMIT ONE. The two artefacts are judged under different
MODES and the difference is the whole point of there being two: `.pre-commit-config.yaml` is RENDERED
and its bytes must equal base-plus-delta, while `Makefile` is REQUIRED and only the base LINES must
be present, because the four measured repos share target NAMES and no recipe. Filing both under a
module named for the rendered one would bury that.

THE COMPLETENESS ARM IS STILL ABSENT, and this module does not quietly close it. `.gitignore` is the
third kit base and this repo has not adopted it; the row at the end of
``test_the_kit_renders_its_own_precommit_config.py`` holds that absence and now names one artefact
where it named two. A suite that called ``assert_every_base_is_accounted_for`` here would be green on
a completeness that has not happened.

NOTHING HERE RE-IMPLEMENTS THE KIT. Every assertion is one of the shared bodies in
:mod:`lab_commons.dev.famtests.configrender` -- the same ones both labs parametrize. This module
supplies only what is a fact about THIS repo: the root, the name, the delta table, and the remedy.
"""

from __future__ import annotations

from pathlib import Path

from _famconfig_delta import DELTAS, MAKE_TARGET_FLOOR, MAKEFILE, MAKEFILE_DELTA, REPO

from lab_commons.dev.famconfig import REQUIRED, artefact_base, delta_lines, measured_delta
from lab_commons.dev.famtests.configrender import (
    assert_artefact_is_rendered,
    assert_delta_is_not_a_fork,
    assert_modes_are_as_agreed,
    assert_no_base_line_left_undeclared,
)

ROOT = Path(__file__).resolve().parents[1]

#: The remedy this suite prints. It has NO default in the kit's arm because the command is the repo's
#: own; REQUIRED mode cannot re-render a Makefile at all, so the remedy is to add the target or to
#: declare the drop, and this line says which file the drop lives in.
REMEDY = 'add the target to ./Makefile, or declare it as a Delta.dropped entry in tests/_famconfig_delta.py'


class TestTheMakefileIsTheFamilyContractPlusThisReposRecipes:
    def test_the_declaration_is_a_delta_of_the_base_and_not_a_fork(self) -> None:
        """Driven on the DECLARATION, so a malformed delta is a different answer from a missing target."""
        assert_delta_is_not_a_fork(artefact=MAKEFILE, deltas=DELTAS, repo=REPO)

    def test_every_base_target_is_present_in_this_repos_own_makefile(self) -> None:
        """THE PROPERTY, in REQUIRED mode: the nine contract lines are here, each under its own recipe."""
        assert_artefact_is_rendered(root=ROOT, artefact=MAKEFILE, deltas=DELTAS, repo=REPO, rerender_hint=REMEDY)

    def test_no_base_line_left_the_file_without_a_declared_drop(self) -> None:
        """The survey's route in. REQUIRED mode never compares bytes, so this is how a loss stays visible."""
        assert_no_base_line_left_undeclared(root=ROOT, artefact=MAKEFILE, repo=REPO)

    def test_the_mode_this_repo_agreed_to_is_the_one_it_is_judged_under(self) -> None:
        """REQUIRED asserts presence only; RENDERED would demand byte equality.

        A base silently arriving in the other mode would demand that this repo's recipes equal three
        other repos', which the measurement across the four says they do not.
        """
        assert_modes_are_as_agreed(modes={MAKEFILE: REQUIRED})

    def test_the_ceiling_is_the_measurement_and_the_delta_still_fits_under_it(self) -> None:
        """THE RATCHET'S OTHER SIDE. Headroom nobody chose is how a delta stops being a delta."""
        live = delta_lines(MAKEFILE_DELTA)
        assert MAKEFILE_DELTA.ceiling == 26, 're-measure the delta before moving the number'
        assert len(live) == MAKEFILE_DELTA.ceiling, (
            f'this repo declares {len(live)} Makefile lines against a ceiling of {MAKEFILE_DELTA.ceiling}. '
            f'The ceiling was set AT the measurement, so a line added here raises it in the same edit '
            f'and says what it is for, and a line removed lowers it.'
        )

    def test_the_survey_finds_nothing_to_drop_and_the_scan_had_a_floor(self) -> None:
        """PLANTED FLOOR. A survey over a base that read empty reports no drops and looks identical."""
        base = artefact_base(MAKEFILE)
        assert len(base.content_lines) >= MAKE_TARGET_FLOOR, (
            f'the Makefile base holds {len(base.content_lines)} contract lines, below the '
            f'{MAKE_TARGET_FLOOR} floor -- every assertion in this module just got thinner'
        )
        survey = measured_delta(ROOT / MAKEFILE, base, REPO)
        assert survey.dropped == {}, (
            f'base lines absent from ./Makefile with no declared drop: {sorted(survey.dropped)}'
        )

    def test_a_missing_target_is_refused_and_the_refusal_names_it(self, tmp_path: Path) -> None:
        """PLANTED CONTROL, both directions, through the same arm the property uses.

        `verify:` is the bent line because it is the one this repo did not have: it is the base line
        motronics is still missing and the one whose recipe the base owns outright. A guard green on
        the real tree could be asserting a constant, so the same file with that target deleted must
        red, and the refusal must NAME it or the guard reported a failure it never located.
        """
        live = (ROOT / MAKEFILE).read_text(encoding='utf-8')
        assert 'verify:' in live, 'this control plants nothing: the real Makefile has no verify target'
        planted = tmp_path / MAKEFILE
        planted.write_text(live, encoding='utf-8')
        clean = measured_delta(planted, artefact_base(MAKEFILE), REPO)
        assert clean.dropped == {}, f'the unedited copy already reports drops: {sorted(clean.dropped)}'
        planted.write_text(live.replace('verify:\n\tpython -m lab_commons.dev.verify', ''), encoding='utf-8')
        bent = measured_delta(planted, artefact_base(MAKEFILE), REPO)
        assert 'verify:' in bent.dropped, f'deleting the verify target did not red: {sorted(bent.dropped)}'
        assert 'python -m lab_commons.dev.verify' in ' '.join(bent.dropped), (
            f'the refusal never names the recipe the base owns: {sorted(bent.dropped)}'
        )
