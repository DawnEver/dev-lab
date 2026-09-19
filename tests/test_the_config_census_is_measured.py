"""The CONFIG-layer census is COMPLETE, two-sided, non-vacuous, and RE-MEASURED against the repos.

A placement roster is prose the moment nothing re-derives its numbers. Every constant in
`_config_census_rows.py` was measured on 2026-09-17 against four checkouts, and the tests below read
those checkouts again: lab-commons always (it is the tree this suite runs in, so the floor is never
zero), and the other three whenever they are checked out beside it, NAMING any that are not.

WHAT IS CHECKED, and why each half exists:

* COMPLETENESS, both sides -- every repo x artefact has a row, and no row names a repo or artefact
  that is not declared. One side alone rots: without the first a new artefact arrives unjudged,
  without the second a deleted one leaves a row that reads as current.
* THE COMPOSER'S REFUSALS, PLANTED -- a duplicate key and a key in the wrong partition, driven
  through the REAL composer rather than a re-implementation that would agree with itself.
* THE REASON IS THE DELIVERABLE -- `Placement` refuses a caption at construction, and the planted
  control proves it can still fire.
* THE MEASUREMENTS -- the select sets, the ignore core and its five-code delta, the gitignore core,
  the Makefile core, the hook core, the installed-hook census, the dev-page overlap, and ruff's own
  config precedence in the one repo that carries two configs.

NOTHING HERE MOVES A FILE. This is the DECLARATION and the check that keeps it honest; a migration
is a later, separate lane, and what this buys that lane is that it cannot move an artefact without
saying which side it was on.
"""

from __future__ import annotations

import tomllib

import pytest
from _config_census import (
    MOVES,
    SIDES,
    SPLITS,
    STAYS,
    CensusError,
    Placement,
    compose,
    dev_pages,
    gitignore_patterns,
    hook_ids,
    installed_hook_names,
    make_targets,
    reachable_repos,
    ruff_config,
    ruff_ignore,
    ruff_scalars,
    ruff_select,
    selector_covers,
)
from _config_census_rows import (
    ARTEFACTS,
    CONSUMER_IGNORE_CORE,
    CONSUMER_IGNORE_DELTA,
    CONSUMER_SELECT,
    COUNTER_DIRECTION_CODES,
    GROUPS_THE_KIT_DOES_NOT_LINT,
    HOOK_ID_CORE,
    INSTALLED_HOOKS,
    KIT_IGNORE,
    KIT_SELECT,
    KIT_SELECT_BEFORE_R1,
    MAKE_TARGET_CORE,
    PARTITIONS,
    REPO_PATHS,
    REPOS,
    SHARED_DEV_PAGES,
    SHARED_GITIGNORE_CORE,
)

CENSUS = compose(PARTITIONS)

#: The census's own floor: four repos times six artefacts. Stated as the product rather than as 24,
#: because the product is the property -- a census that lost an artefact and a census that lost a
#: repo are different failures and a bare integer cannot tell them apart.
ROW_FLOOR = len(REPOS) * len(ARTEFACTS)

#: The consumers -- every repo that INSTALLS lab-commons rather than being it.
CONSUMERS = tuple(repo for repo in REPOS if repo != 'lab-commons')


# --------------------------------------------------------------------------- the census's shape


def test_every_repo_and_artefact_has_a_row_and_no_row_invents_one() -> None:
    """COMPLETENESS, BOTH SIDES. A missing row lets an artefact go unjudged; an extra one lies."""
    assert len(CENSUS) == ROW_FLOOR, f'{len(CENSUS)} rows against {len(REPOS)} repos x {len(ARTEFACTS)} artefacts'
    expected = {f'{repo}::{artefact}' for repo in REPOS for artefact in ARTEFACTS}
    assert set(CENSUS) == expected, (
        f'missing: {sorted(expected - set(CENSUS))}; invented: {sorted(set(CENSUS) - expected)}'
    )


def test_every_partition_is_non_empty_and_the_sides_are_all_three_used() -> None:
    """FLOOR. An empty partition, or a census that only ever says one thing, proves nothing."""
    for repo, rows in PARTITIONS:
        assert rows, f'{repo} declares no rows, which makes every check below vacuous for it'
    used = {row.side for row in CENSUS.values()}
    assert used == set(SIDES), (
        f'the census uses only {sorted(used)}. All three sides must be exercised or the ones it never '
        f'reaches are untested vocabulary rather than decisions anybody made.'
    )


def test_the_kit_is_never_the_consumer_of_its_own_move() -> None:
    """A ratchet has two sides: nothing may MOVE out of lab-commons, because that is where it goes."""
    kit_moves = [key for key, row in CENSUS.items() if key.startswith('lab-commons::') and row.side == MOVES]
    assert kit_moves == [], f'{kit_moves}: MOVES means "belongs in the shared kit", and this IS the kit'


def test_a_row_declared_in_two_partitions_raises() -> None:
    """PLANTED. A dict update would take the last one silently, which is the whole hazard."""
    row = Placement(STAYS, 'x' * 400)
    with pytest.raises(CensusError, match='declared in two partitions'):
        compose((('wdg-lab', {'wdg-lab::Makefile': row}), ('wdg-lab', {'wdg-lab::Makefile': row})))


def test_a_row_whose_repo_is_not_its_partitions_raises() -> None:
    """PLANTED. A partition whose name stops describing its rows is a declaration that lies."""
    with pytest.raises(CensusError, match='owns exactly one repo'):
        compose((('wdg-lab', {'optimi-lab::Makefile': Placement(STAYS, 'y' * 400)}),))


def test_a_caption_and_a_fourth_side_are_both_refused_at_construction() -> None:
    """PLANTED, BOTH REFUSALS. The reason is the deliverable; the side is only its label."""
    with pytest.raises(CensusError, match='is not one of the three sides'):
        Placement('maybe', 'z' * 400)
    with pytest.raises(CensusError, match='REASON is the deliverable'):
        Placement(SPLITS, 'shared base, repo delta')


def test_every_reason_names_its_artefact_side_obligation() -> None:
    """A STAYS says what breaks, a MOVES says what is lost, a SPLITS says where the seam is."""
    missing = [key for key, row in CENSUS.items() if not _states_its_obligation(row)]
    assert missing == [], (
        f'{missing}: a STAYS/SPLITS row must say what BREAKS or name the SEAM, and a MOVES row must '
        f'say what a consumer would LOSE. Without that the side is a label and the row is a caption.'
    )


def _states_its_obligation(row: Placement) -> bool:
    lowered = row.why.lower()
    if row.side == MOVES:
        return 'lose' in lowered or 'lost' in lowered
    return 'breaks' in lowered or 'seam' in lowered


# --------------------------------------------------------------------------- the live measurement


def test_the_census_reaches_at_least_its_own_checkout() -> None:
    """FLOOR ON THE SCAN. lab-commons is always here, so an empty reach is a broken reader."""
    reached = reachable_repos(REPO_PATHS)
    assert 'lab-commons' in reached, 'the census could not find the tree it is running in'
    stray = sorted(set(reached) - set(REPOS))
    assert stray == [], f'reached a repo the census does not declare: {stray}'


def test_the_kit_now_selects_the_fifty_eight_and_the_counter_direction_is_unchanged() -> None:
    """FINDING 1, RE-DERIVED AFTER R1. Always runs: both sides are readable from this checkout alone.

    The original reading of this test -- "the kit selects twelve and is neither a superset nor a
    subset" -- was true when the census was written on 2026-09-17 and false by the end of that day.
    What CLOSED is the blindness: the kit adopted the consumers' 58 verbatim. What did NOT close is
    the counter-direction, because its remedy is in three other repos, and it is asserted UNCHANGED
    here rather than deleted: eight codes the kit enforces and every consumer globally ignores.
    """
    kit_root = reachable_repos(REPO_PATHS)['lab-commons']
    live = ruff_select(kit_root)
    assert live == set(KIT_SELECT), f'lab-commons now selects {sorted(live)}, not the recorded {list(KIT_SELECT)}'
    assert live == set(CONSUMER_SELECT), 'the kit and the consumers no longer agree on the select'

    groups = {code for code in CONSUMER_SELECT if not any(selector_covers(s, code) for s in live)}
    assert len(groups) == GROUPS_THE_KIT_DOES_NOT_LINT, (
        f'the kit is blind to {sorted(groups)}; R1 closed that gap and this number may only be 0'
    )

    waived = ruff_ignore(kit_root)
    assert waived == set(KIT_IGNORE), (
        f'lab-commons ignores {sorted(waived)}, not the recorded {list(KIT_IGNORE)}. That list is a '
        f'ratchet: it may only SHRINK, and every entry carries its reason in pyproject.toml.'
    )
    assert not (waived & set(COUNTER_DIRECTION_CODES)), (
        'the kit started ignoring one of the eight codes the counter-direction is measured over, which '
        'would close that finding by lowering the count rather than by deciding it'
    )

    counter = tuple(
        sorted(
            code
            for code in CONSUMER_IGNORE_CORE
            if any(selector_covers(group, code) for group in KIT_SELECT_BEFORE_R1)
            and not any(selector_covers(w, code) for w in waived)
        )
    )
    assert counter == COUNTER_DIRECTION_CODES, (
        f'the counter-direction set is now {list(counter)}, not {list(COUNTER_DIRECTION_CODES)}. It is '
        f'stated over the TWELVE selectors the kit had before R1 on purpose: those eight were '
        f'divergences inside groups both sides already took, and re-deriving them over the adopted 58 '
        f'would fold them into the 48 the adoption itself created. Both sets are ratchets, and they '
        f'are owned by test_the_kit_is_not_linted_less_than_what_it_ships.py.'
    )


def test_selector_covers_resolves_the_linter_before_the_digits() -> None:
    """PLANTED CONTROL for the one function whose naive form changed the headline number.

    ``'ERA001'.startswith('E')`` is True and ruff's answer is False. Getting this wrong inflated the
    counter-direction set from 8 codes to 13, so the control plants exactly those confusions.
    """
    assert selector_covers('E', 'E501')
    assert selector_covers('PLC', 'PLC0415')
    assert selector_covers('B', 'B018')
    assert not selector_covers('E', 'ERA001'), 'pycodestyle E must not swallow eradicate'
    assert not selector_covers('F', 'FBT003'), 'Pyflakes F must not swallow flake8-boolean-trap'
    assert not selector_covers('F', 'FIX001')
    assert not selector_covers('PLC0415', 'PLC0414'), 'the digits match by PREFIX, not by string start'


def test_motronics_reads_ruff_toml_and_the_pyproject_block_is_dead() -> None:
    """FINDING 2, RE-DERIVED against the lane when it is checked out."""
    root = reachable_repos(REPO_PATHS).get('motronics-studio')
    if root is None:
        pytest.fail('the motronics lane is not checked out beside this repo, so finding 2 is unmeasured here')
    assert (root / 'ruff.toml').is_file(), 'the lane no longer carries ruff.toml; finding 2 described that file'
    assert ruff_select(root) == set(CONSUMER_SELECT), 'the winning config drifted from the consumer select'
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    loser = project.get('tool', {}).get('ruff', {})
    assert loser in ({}, {'extend': 'ruff.toml'}), (
        f'the LOSING [tool.ruff] block now holds {sorted(loser)}. It held exactly one key naming the '
        f'winner, which is what made it dead rather than lying, and R3 deleted it; anything else in it '
        f'is a decision ruff never reads.'
    )
    assert ruff_config(root) != loser, 'the reader returned the losing config, so precedence is not being applied'
    assert ruff_config(root), 'ruff.toml is the winner and it must be the non-empty side of that comparison'


def test_the_three_consumers_agree_on_the_select_and_diverge_by_five_codes_in_total() -> None:
    """The measurement every SPLITS row rests on, re-derived for whichever consumers are here."""
    reached = reachable_repos(REPO_PATHS)
    present = [repo for repo in CONSUMERS if repo in reached]
    assert present, f'no consumer is checked out beside this repo; absent: {list(CONSUMERS)}'
    for repo in present:
        root = reached[repo]
        assert ruff_select(root) == set(CONSUMER_SELECT), f'{repo}: select diverged from the family 58'  # noqa: S608 -- 'select' is a ruff selector list, not SQL
        delta = ruff_ignore(root) - set(CONSUMER_IGNORE_CORE)
        assert delta == set(CONSUMER_IGNORE_DELTA[repo]), (
            f'{repo}: ignore delta is now {sorted(delta)}, recorded {list(CONSUMER_IGNORE_DELTA[repo])}'
        )
        assert set(CONSUMER_IGNORE_CORE) <= ruff_ignore(root), f'{repo}: dropped part of the 62-code core'
        assert ruff_scalars(root) == {
            'line-length': 120,
            'target-version': 'py313',
            'unsafe-fixes': True,
            'quote-style': 'single',
        }, f'{repo}: a scalar knob diverged, so "identical except the ignore delta" no longer holds'
    live_core = set.intersection(*(set(ruff_ignore(reached[repo])) for repo in present))
    assert live_core == set(CONSUMER_IGNORE_CORE), (
        f'the three-way ignore core is now {len(live_core)} codes against the declared '
        f'{len(CONSUMER_IGNORE_CORE)}: only-live {sorted(live_core - set(CONSUMER_IGNORE_CORE))}, '
        f'only-declared {sorted(set(CONSUMER_IGNORE_CORE) - live_core)}. An EQUALITY because the '
        f'subset above is satisfied by every shorter tuple, so the constant could be edited down '
        f'forever and stay green -- the shape that hid a two-short `SHARED_GITIGNORE_CORE`. WHOSE '
        f'DRIFT THIS ACCUSES: one of the three CONSUMERS; the kit is not in the intersection, since '
        f'its ignore list is ten codes and is its own delta. Re-measured 2026-09-19: 62 live, 62 '
        f'declared, so the constant was NOT short.'
    )


def test_the_gitignore_core_is_the_consumers_and_the_kit_holds_three_of_it() -> None:
    """The consumer core, as an EQUALITY, and the three patterns of it the kit happens to share.

    IT ASSERTED A SUBSET UNTIL 2026-09-19 AND THAT IS WHY IT WAS WRONG. `SHARED_GITIGNORE_CORE` read
    12 while the live three-way intersection was 14, and `core <= consumer` is satisfied by every
    shorter tuple -- so the constant could drift DOWN forever and this arm would stay green. An
    equality has no such slack: a pattern leaving any consumer reds, and so does one arriving in all
    three without the constant moving.
    """
    reached = reachable_repos(REPO_PATHS)
    kit = gitignore_patterns(reached['lab-commons'])
    assert len(kit) >= 8, f'{len(kit)} patterns read from lab-commons/.gitignore; the reader found nothing'
    assert kit & set(SHARED_GITIGNORE_CORE) == {'*.egg-info/', '.pytest_cache/', '.ruff_cache/'}, sorted(
        kit & set(SHARED_GITIGNORE_CORE)
    )
    present = [repo for repo in CONSUMERS if repo in reached]
    assert len(present) >= 2, f'{present}: a three-way intersection over fewer than two repos is not a reading'
    measured = frozenset.intersection(*(gitignore_patterns(reached[repo]) for repo in present))
    assert measured == set(SHARED_GITIGNORE_CORE), (
        f'the consumer core moved: measured {sorted(measured)} over {present}, recorded '
        f'{sorted(SHARED_GITIGNORE_CORE)}. Re-measure and move the constant in the same edit.'
    )
    for repo in present:
        other = gitignore_patterns(reached[repo])
        assert not kit <= other, f'{repo} became a superset of the kit, so the SPLITS seam moved'


def test_the_makefile_core_is_three_targets_across_all_four() -> None:
    """MAKE_TARGET_CORE both ways, and `verify` in ALL FOUR rather than the gap this used to assert.

    THE ARM THAT FLIPPED, 2026-09-18, and the flip is the point. This test used to assert
    ``'verify' not in per_repo['motronics-studio']`` -- guarding the census row's claim that motronics
    was the only repo without one. A separate edit in the motronics lane gave that repo a `verify`
    naming its own runner, so the guard went red for the RIGHT reason: the tree had moved past the
    prose. The honest repair is the ratchet's other side -- a capability ARRIVED, so it is asserted
    rather than the census being edited to say the arrival never happened.

    The wider re-measurement that came with it: the all-four common set is NINE, not three, and it is
    exactly what `MAKEFILE_BASE` defines. `MAKE_TARGET_CORE` was raised to match, which puts a NAMED
    SET on its population on purpose -- any repo dropping any of the nine reds, and the remedy is the
    target, never the tuple.
    """
    reached = reachable_repos(REPO_PATHS)
    per_repo = {repo: make_targets(root) for repo, root in reached.items()}
    assert per_repo, 'no Makefile was read at all'
    common = set.intersection(*(set(t) for t in per_repo.values()))
    assert common == set(MAKE_TARGET_CORE), (
        f'the four-repo common target set is now {sorted(common)} against the declared '
        f'{list(MAKE_TARGET_CORE)}. THIS IS AN EQUALITY AND THE CONSTANT`S OWN COMMENT ALWAYS SAID SO '
        f'-- "a NAMED SET and not a floor ... the remedy when a repo drops one is to restore the '
        f'TARGET, never to shorten this tuple" -- while the assertion here was a subset any shorter '
        f'tuple satisfies. Declaration and mechanism disagreed in the same commit; the mechanism '
        f'moved. WHOSE DRIFT THIS ACCUSES: ANY of the four, the kit included. A target that JOINED '
        f'the intersection is a real family target and belongs in the tuple and in `MAKEFILE_BASE`. '
        f'Re-measured 2026-09-19: nine live, nine declared, so the constant was NOT short.'
    )
    absent = sorted(repo for repo, targets in per_repo.items() if 'verify' not in targets)
    assert absent == [], f'{absent} lost `verify`, the one target every repo in the family reaches its verdict through'


def test_the_hook_core_is_eleven_and_every_declared_commitizen_stage_is_wired() -> None:
    """THE RATCHET'S OTHER SIDE for the pre-commit rows: DECLARED is not INSTALLED.

    This assertion has now earned its place TWICE, in opposite directions, and the second time is
    why the name changed.

    First: a hand `ls` reported zero installed hooks in every repo; the reader here -- which
    resolves the hooks directory through git, and a worktree's through its parent -- found
    `pre-commit` in three of them and refused the recorded zero.

    Second, 2026-09-17: this arm used to assert that the labs' `commit-msg` stage was UNWIRED, which
    was true and meant EVERY COMMIT MESSAGE IN BOTH LABS WENT UNCHECKED while both trees read as
    guarded. It was closed the same day, so the arm is now its mirror: the stage IS wired, and this
    line is what reds if it is ever unwired again. A ratchet has two sides, and an arm that only
    ever asserted the gap would have gone green forever the moment the gap closed -- silent about
    the regression it exists to catch.

    Third, the same day: the kit's own half. This arm used to assert `hook_ids(lab-commons) ==
    frozenset()` and its message named the repair it was waiting for -- "lab-commons grew a
    .pre-commit-config.yaml ... rewrite the row to describe what landed rather than deleting this
    assertion". That is what happened, so the assertion turned the way it was written to turn: the
    kit is no longer the exception, and the core check below now covers ALL FOUR repos instead of
    excluding the one that publishes the core. An arm phrased as "this repo has nothing" cannot
    survive the repair it asks for; one phrased as "this repo has the core" survives and keeps biting.
    """
    reached = reachable_repos(REPO_PATHS)
    declared = {repo: hook_ids(root) for repo, root in reached.items()}
    for repo, ids in declared.items():
        assert set(HOOK_ID_CORE) <= ids, f'{repo} dropped part of the 11-hook core: {sorted(set(HOOK_ID_CORE) - ids)}'
    common_ids = set.intersection(*(set(ids) for ids in declared.values()))
    assert common_ids == set(HOOK_ID_CORE), (
        f'the four-repo hook core is now {sorted(common_ids)} against the declared {list(HOOK_ID_CORE)}. '
        f'Stated as an EQUALITY for the reason the other cores now are, with one honest caveat: this '
        f'one could not have drifted DOWN silently, because the kit`s own set is pinned EQUAL to the '
        f'core two lines below and the subset arm above bounds it from the other side. What this line '
        f'adds is the UPWARD half -- an id all four repos grew is a family hook that belongs in the '
        f'base -- and legibility, so a reader need not derive the equality from two arms. WHOSE DRIFT '
        f'THIS ACCUSES: any of the four. Re-measured 2026-09-19: eleven live, eleven declared.'
    )
    assert declared['lab-commons'] == set(HOOK_ID_CORE), (
        f'lab-commons declares {sorted(declared["lab-commons"])} against the family core '
        f'{list(HOOK_ID_CORE)}. The kit adopted the base with an EMPTY delta on 2026-09-17, so its set '
        f'IS the core exactly -- an extra id here is a repo-shaped line that belongs in '
        f'`tests/_famconfig_delta.py` with a raised ceiling, and a missing one is the base losing a hook.'
    )
    for repo, root in reached.items():
        assert installed_hook_names(root) == set(INSTALLED_HOOKS[repo]), (
            f'{repo}: installed hooks are now {sorted(installed_hook_names(root))}, recorded '
            f'{list(INSTALLED_HOOKS[repo])}. A config nobody installed is a declaration that lies, and '
            f'this line is the only thing in the family that would notice it changing.'
        )
    for repo in ('lab-commons', 'wdg-lab', 'optimi-lab'):
        if repo not in reached:
            continue
        assert 'commitizen' in declared[repo], f'{repo} stopped declaring commitizen'
        assert 'commit-msg' in installed_hook_names(reached[repo]), (
            f'{repo} declares commitizen at the commit-msg stage and has no commit-msg hook file, so '
            f'every commit message here goes UNCHECKED while the tree reads as guarded. That gap was '
            f'open in both labs until 2026-09-17 and nothing was looking for it; this line is what '
            f'looks. Re-wire it (`pre-commit install -t commit-msg`) rather than relaxing this arm.'
        )
    if 'motronics-studio' in reached:
        assert 'commit-msg' in installed_hook_names(reached['motronics-studio']), (
            'motronics is the row that says every declared stage is wired; its commit-msg hook is gone'
        )


def test_the_labs_one_dev_page_is_a_pointer_and_not_a_gap() -> None:
    """The 13/1/1/14 split, MEASURED: the labs' near-zero is the MOVES already executed."""
    reached = reachable_repos(REPO_PATHS)
    kit_pages = dev_pages(reached['lab-commons'])
    assert len(kit_pages) >= 10, f'{len(kit_pages)} pages under lab-commons/docs-src/dev; the reader found nothing'
    assert set(SHARED_DEV_PAGES) <= kit_pages, sorted(set(SHARED_DEV_PAGES) - kit_pages)
    # The subset above says the kit still HOLDS the shared names; it cannot see the constant drifting
    # DOWN, which is how `SHARED_GITIGNORE_CORE` sat two short and green. The equality is below, on
    # the live intersection, and `test_the_dev_docs_tree_is_shared_by_reference.py` asserts the same
    # one from the other side.
    for repo in ('wdg-lab', 'optimi-lab'):
        if repo not in reached:
            continue
        pages = dev_pages(reached[repo])
        assert pages == {'index.md'}, f'{repo} now holds {sorted(pages)}; its row says the tree is one pointer page'
        text = (reached[repo] / 'docs-src' / 'dev' / 'index.md').read_text(encoding='utf-8')
        assert '../../../lab-commons/docs-src/dev/' in text, f'{repo} index.md stopped pointing at the shared tree'
        assert 'pointer_table' in text, f'{repo} index.md no longer names the generator that keeps it honest'
    if 'motronics-studio' in reached:
        pages = dev_pages(reached['motronics-studio'])
        assert pages & kit_pages == set(SHARED_DEV_PAGES), (
            f'the kit/motronics shared page names are now {sorted(pages & kit_pages)} against the '
            f'declared {sorted(SHARED_DEV_PAGES)}. Asserted as an EQUALITY on purpose: a subset is '
            f'satisfied by every shorter declaration, so the constant could be edited down forever '
            f'and stay green.'
        )
        own = pages - kit_pages
        assert own >= {'gate.md', 'testing.md', 'integration.md', 'user-flow.md', 'compute-resources.md'}, sorted(own)
        stub = (reached['motronics-studio'] / 'docs-src' / 'dev' / 'the-three-participants.md').read_text(
            encoding='utf-8'
        )
        assert '../../../lab-commons/docs-src/dev/' in stub, (
            'the motronics stub stopped pointing upstream, so its SPLITS row describes a former shape'
        )


def test_a_planted_short_core_is_convicted_by_the_equality_and_not_by_the_subset() -> None:
    """PLANTED CONTROL for the four cores this module now pins as EQUALITIES.

    The defect being controlled for is not a wrong measurement -- all four constants re-measured
    exactly right on 2026-09-19 -- but a wrong ASSERTION SHAPE. `DECLARED <= live` is satisfied by
    every shorter declaration, so a constant can be edited down forever and stay green; that is how
    `SHARED_GITIGNORE_CORE` sat at twelve against a live fourteen. This plants exactly that edit --
    one name dropped from each core -- and shows the subset still passes while the equality convicts.
    Without it the four equalities above are only a claim that today's numbers agree.
    """
    reached = reachable_repos(REPO_PATHS)
    consumers = [repo for repo in CONSUMERS if repo in reached]
    assert consumers, 'no consumer is checked out, so nothing below is measured against the family'
    cores = {
        'CONSUMER_IGNORE_CORE': (
            set(CONSUMER_IGNORE_CORE),
            set.intersection(*(set(ruff_ignore(reached[r])) for r in consumers)),
        ),
        'MAKE_TARGET_CORE': (
            set(MAKE_TARGET_CORE),
            set.intersection(*(set(make_targets(r)) for r in reached.values())),
        ),
        'HOOK_ID_CORE': (set(HOOK_ID_CORE), set.intersection(*(set(hook_ids(r)) for r in reached.values()))),
    }
    if 'motronics-studio' in reached:
        cores['SHARED_DEV_PAGES'] = (
            set(SHARED_DEV_PAGES),
            dev_pages(reached['lab-commons']) & dev_pages(reached['motronics-studio']),
        )
    assert len(cores) >= 3, 'the control lost the cores it exists to drive'
    for name, (declared, live) in cores.items():
        assert declared, f'{name} is empty, so both shapes below are vacuous'
        assert declared == live, f'{name}: {len(declared)} declared against {len(live)} live -- fix the CONSTANT'
        shortened = declared - {min(declared)}
        assert shortened <= live, f'{name}: a short core fails even the SUBSET, so this control proves nothing'
        assert shortened != live, f'{name}: the equality accepts a core one name short -- it is not an equality'
