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

`REQUIRED` IS THIS ARTEFACT'S TERMINAL MODE, AND THE LAST CLASS DRIVES THE MEASUREMENT THAT SAYS SO.
The question was reopened on 2026-09-18 on the ground that the stated reason had expired: the base
reads REQUIRED because motronics had no `verify:`, that gap closed, so the Makefile can now be
RENDERED. BOTH HALVES OF THAT ARE WRONG and re-measuring is what says which:

* The recorded reason was never motronics' missing target. `_famconfig_rows` says it is that the four
  repos share target NAMES and NO recipe, so a rendered family Makefile would be a declaration that
  lies. Re-measured over all four today, SEVEN of the nine shared targets still carry a different
  recipe in more than one repo, and `install:` and `install-dev:` carry four distinct ones apiece.
* RENDERED compares BYTES, and no base header is a shared LINE. The two targets whose recipe BODIES
  do agree are the two that carry their content on the header: `all:` is spelled three ways
  (`all: verify`, `all: fmt test`, `all: fmt lint test`) and `verify:` two (`verify:`,
  `verify: lint`). REQUIRED matches a colon-terminated base line by TARGET NAME, which is the
  affordance that lets one base bind all three spellings; RENDERED has no such affordance, so
  adopting it would mean the base fixing one repo's prerequisite list on the other three -- a
  per-tree fact legislated from here.
* The sharper half of the complaint -- "REQUIRED asserts presence, so it cannot see a recipe
  diverge" -- was closed the same day by a DIFFERENT mechanism rather than by a mode change.
  `unbound_recipes` is wired into `famconfig._required_report`, and it catches the state a mode
  change would not have made legible anyway: a target present with the base's recipe sitting under
  something else, so `make verify` runs and does nothing.

So the two sides are not "presence" versus "bytes". They are a CONTRACT that binds three spellings
of nine targets and byte-checks the one portable recipe, against a RENDERING that would have to own
every recipe in every repo. The class below pins the measurement, both ways: it reds if the recipes
ever converge -- which is the day to reopen this -- and it reds if the mode moves without them.
"""

from __future__ import annotations

from pathlib import Path

from _config_census import reachable_repos
from _config_census_rows import REPO_PATHS
from _famconfig_delta import DELTAS, MAKE_TARGET_FLOOR, MAKEFILE, MAKEFILE_DELTA, REPO

from lab_commons.dev.famconfig import (
    REQUIRED,
    artefact_base,
    delta_lines,
    meaningful_lines,
    measured_delta,
    recipe_blocks,
    satisfies,
)
from lab_commons.dev.famtests.configrender import (
    assert_artefact_is_rendered,
    assert_delta_is_not_a_fork,
    assert_modes_are_as_agreed,
    assert_no_base_line_left_undeclared,
)

ROOT = Path(__file__).resolve().parents[1]

#: The targets whose RECIPE differs between at least two of the four repos, MEASURED 2026-09-18. It
#: is a NAMED SET rather than a count, for the reason the integration rule gives: an integer cannot
#: say WHICH target converged, and the honest-looking repair when it disagrees is to edit the digit.
DIVERGENT_RECIPES: frozenset[str] = frozenset(
    {'clean:', 'fmt:', 'install:', 'install-dev:', 'lint:', 'test:', 'test-parallel:'}
)

#: The two whose recipe BODIES agree in all four -- and both of them carry their content on the
#: HEADER instead, which is why their agreement is not an argument for rendering. `all:` has an empty
#: body everywhere and three different prerequisite lists; `verify:` has the base's one portable
#: recipe and two different prerequisite lists.
SHARED_RECIPES: frozenset[str] = frozenset({'all:', 'verify:'})

#: How many repos must be readable before "they disagree" means anything. TWO: divergence measured
#: over one checkout is not a weak reading, it is an impossible one.
DIVERGENCE_FLOOR = 2

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


class TestRequiredIsTheTerminalModeForThisArtefact:
    """THE RE-OPENED QUESTION, ANSWERED BY MEASUREMENT. See this module's docstring for the argument.

    Every arm here reads all four live Makefiles through the kit's own readers -- `meaningful_lines`,
    `recipe_blocks` and `satisfies` -- and nothing in it is a fact about lab-commons alone. That is
    deliberate: a mode is a property of the ARTEFACT across the family, so an arm that could be
    satisfied by this repo's own file would be answering a different question.
    """

    @staticmethod
    def _blocks() -> dict[str, dict[str, tuple[str, ...]]]:
        """Each reached repo's Makefile as ``header line -> recipe lines``, read by the kit."""
        base = artefact_base(MAKEFILE)
        reached = reachable_repos(REPO_PATHS)
        return {
            repo: recipe_blocks(meaningful_lines((root / MAKEFILE).read_text(encoding='utf-8'), base.comment))
            for repo, root in sorted(reached.items())
            if (root / MAKEFILE).is_file()
        }

    def test_the_shared_targets_still_carry_unshared_recipes(self) -> None:
        """THE MEASUREMENT RENDERING WOULD HAVE TO SURVIVE, and it does not: 7 of the 9 diverge."""
        blocks = self._blocks()
        assert len(blocks) >= DIVERGENCE_FLOOR, (
            f'{len(blocks)} Makefile(s) readable here; divergence measured over fewer than '
            f'{DIVERGENCE_FLOOR} repos is not a weak reading but an impossible one'
        )
        base = artefact_base(MAKEFILE)
        headers = [line for line in base.content_lines if line.endswith(':')]
        assert len(headers) >= MAKE_TARGET_FLOOR, f'the base declares {len(headers)} target headers'
        divergent = {
            header
            for header in headers
            if len(
                {tuple(lines) for repo in blocks for name, lines in blocks[repo].items() if satisfies(header, (name,))}
            )
            > 1
        }
        assert divergent == DIVERGENT_RECIPES, (
            f'the recipe divergence moved: now {sorted(divergent)}, recorded {sorted(DIVERGENT_RECIPES)}. '
            f'If it SHRANK to nothing the four repos finally agree on their recipes and RENDERED is '
            f'worth re-opening -- with this measurement quoted. If it GREW, a repo took its own tree '
            f'or toolchain into a recipe the base had, and the remedy is there and not here.'
        )
        assert set(headers) - divergent == SHARED_RECIPES, sorted(set(headers) - divergent)

    def test_no_base_header_is_a_shared_LINE_so_byte_equality_has_nothing_to_stand_on(self) -> None:
        """THE SECOND HALF, and the one that settles it even for the two recipes that DO agree.

        RENDERED compares bytes. `all:` and `verify:` agree on their bodies and disagree on the
        header itself, because that is where a Makefile puts its prerequisites -- and a prerequisite
        list is each repo's own dependency graph. A base fixing one spelling would legislate it.
        """
        blocks = self._blocks()
        assert len(blocks) >= DIVERGENCE_FLOOR, f'{len(blocks)} Makefile(s) readable here'
        spellings = {
            header: {name for repo in blocks for name in blocks[repo] if satisfies(header, (name,))}
            for header in SHARED_RECIPES
        }
        for header, seen in sorted(spellings.items()):
            assert len(seen) > 1, (
                f'{header} is now spelled identically in every reached repo: {sorted(seen)}. That is '
                f'one of the two preconditions RENDERED needs; check the other arm before acting on it.'
            )

    def test_the_mode_is_still_required_and_the_reason_is_the_measurement_above(self) -> None:
        """THE RATCHET. A mode arriving as RENDERED while the recipes still diverge is the bad half."""
        assert_modes_are_as_agreed(modes={MAKEFILE: REQUIRED})
        assert artefact_base(MAKEFILE).mode == REQUIRED, (
            'Makefile moved off REQUIRED. The two arms above are the evidence that has to have '
            'flipped first; if it has not, this is a base promising byte equality it cannot hold.'
        )
