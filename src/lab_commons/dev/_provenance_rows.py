"""WHAT EACH PUBLISHED `lab_commons.dev` MODULE REPLACED, or did not -- DATA, one row per module.

READ AS SOURCE by `lab_commons.dev._provenance.provenance_rows`, never imported, so every value here
is a literal. `undeclared_modules` is the mechanism that makes this file a ratchet rather than a
habit: a published module with no row reds, and a row naming no module reds too.

THREE KINDS, AND ONLY THE FIRST IS A PROVENANCE CLAIM.

* `supersedes` -- this module replaced those consumer files, whole or in part. This is the only kind
  the census's PROVENANCE detector reads.
* `adopted_by` -- the consumer file DELEGATES to this module and stays. Recorded because the
  distinction is exactly what a docstring cannot make: prose that names a file names it for both
  reasons at once, which is how `verify`'s mention of `scripts/gate/runner.py` (carved FROM, 0 of 51
  names shared) became the false positive that `named_only` exists to hold.
* `original` -- no consumer fork behind it. It is a DECLARATION, refusable by a reader: `forge` is
  the row to look at first, because motronics-studio's `scripts/repo/forge_protect.py` shares `Forge`
  and `token_for` with it, and three tranches still read that file BY HAND as still local. Overlap is
  not provenance here for the same reason it is not a detector next door.

A CONSUMER PATH IS SPELLED AS THE CONSUMER SPELLS IT, repo-relative. Matching is by suffix, so a
basename reaches the row without a repo name in front of it -- and a repo name in front of it would
be one repo's answer in a file three repos read.
"""

from __future__ import annotations

from typing import Final

__all__ = ['PROVENANCE']

PROVENANCE: Final[dict[str, tuple[str, ...]]] = {
    'ab_bench': ('original',),
    'agent_guard': ('original',),
    # ORIGINAL rather than a supersession: the three repos' allow blocks were hand-written and
    # nothing generated them, so there is no consumer file this replaced -- only nine rows it now
    # derives or admits. The row motronics added by hand on 2026-09-18 is the first thing it subsumes.
    'allow_adoption': ('original',),
    'bounded': (
        'supersedes',
        'scripts/gate/bounded.py',
        'scripts/gate/_box.py',
        'scripts/gate/wall_reason.py',
        'scripts/gate/width.py',
    ),
    'boxlock': ('original',),
    'boxwait': ('original',),
    'bypath': ('supersedes', 'scripts/gate/_by_path.py'),
    'checkout': (
        'supersedes',
        'scripts/lanes/prune_origin_branches.py',
        'scripts/lanes/session_branches.py',
        'scripts/repo/worktree_debris.py',
    ),
    'cjk': ('original',),
    'content': ('original',),
    'datedlog': ('supersedes', 'scripts/gate/_dated.py'),
    'dep': ('supersedes', 'scripts/gate/native_install.py'),
    'devdocs': ('original',),
    # THREE implementations existed -- motronics `scripts/repo/docs.py`, wdg-lab `scripts/docs.py`,
    # optimi-lab `scripts/pdoc`. The table stayed with each repo, so this is adoption, not a move.
    'docsite': ('adopted_by', 'scripts/repo/docs.py'),
    'docwidth': ('original',),
    'envkey': ('original',),
    'famconfig': ('original',),
    # The floor refusal was written EIGHT times across this family and no two copies agreed -- four
    # standalone bodies raising four different exception types, three of them here in `src/`; three
    # more inlined at the top of a larger arm; and wdg-lab's `bind_floor`. TWO of the four are both
    # named `VacuousScan` over DIFFERENT base classes, in this one repo. The consumer path named is
    # the one that PUBLISHED the helper; optimi-lab's EIGHT inline copies have no path to name.
    'floors': ('supersedes', 'tests/architecture/_corpus.py'),
    # See the module docstring above: declared original against a measured 2-name overlap.
    'forge': ('original',),
    'gatebase': ('supersedes', 'scripts/gate/base.py'),
    'hook_adoption': ('supersedes', 'scripts/repo/write_deny_rules.py'),
    'hook_install': ('supersedes', 'scripts/repo/_hooks.py'),
    # `scripts/hooks/with-retry.sh` is a REMEDY that resolves in one checkout on earth, which is why
    # `hooks` holds the statements and `hook_adoption` holds the pointer. Neither replaced it.
    'hooks': ('original',),
    'installdoor': ('original',),
    'logref': ('original',),
    # Both named by `netverb`'s docstring as the vacuum it closes, and both ADOPTED it on 2026-09-17
    # while staying: wdg-lab's roster carries one as SPLITS and the other as STAYS.
    'netverb': ('adopted_by', 'scripts/pull_all.py', 'scripts/wdg-lab-update.sh'),
    'profile': ('original',),
    'quantity_values': ('original',),
    'reports': ('original',),
    'rules': ('original',),
    'seams': ('supersedes', 'scripts/gate/seam_install.py'),
    'selfbuild': ('supersedes', 'scripts/gate/native_install.py'),
    'shadow_build': ('supersedes', 'scripts/gate/native_ab.py'),
    'shards': ('supersedes', 'scripts/gate/_shards.py'),
    'supersede': ('original',),
    'symcov': ('supersedes', 'scripts/repo/_symbol_coverage.py'),
    # 'original' until 2026-09-18, when the assertion-SHAPE reader landed here and took the whole
    # reading half of a consumer's vacuous-assert lint -- its `_called_name`, `_is_assertion`,
    # `_is_vacuous_assert` and its walk. The consumer keeps its own floors and its bar, which is the
    # population half `collect` and `census` already own; what moved is the reading.
    'testfacts': ('supersedes', 'tests/architecture/ratchets/test_no_test_asserts_only_is_not_none.py'),
    'treedirt': ('supersedes', 'scripts/gate/tree_state.py'),
    'units': ('original',),
    'verdict': ('original',),
    # `scripts/gate/runner.py` is the tree this was CARVED FROM and it stayed: it shares 0 of its 51
    # names with this module. Naming it `supersedes` is the mistake this kind exists to refuse.
    'verify': ('adopted_by', 'scripts/gate/runner.py'),
    # -- `lab_commons.dev.famtests`, the shared assertion bodies. Each replaces a consumer's whole
    #    test file, which is the class of row that has no import to be found by: a test file that
    #    has not adopted the body yet imports nothing from the kit at all.
    'agentguard': ('supersedes', 'tests/architecture/test_the_agent_guard_is_live.py'),
    'allowguard': ('supersedes', 'tests/architecture/test_no_allow_entry_names_a_denied_shape.py'),
    # TWO consumer files, not one, and the pair is why this is a single row: they ask the same
    # question of PATH citations and of bare NAME citations, share the walk, the prose reader and the
    # history exemptions, and measure 5.45% and 0.85% repo density against a 3.0% move bar -- so read
    # separately a roster says MOVE about one and STAY about the other, and the repo keeps half a
    # mechanism. The readings half, `famtests/_citedtests_readings.py`, is private and has no row.
    'citedtests': (
        'supersedes',
        'tests/architecture/docs/test_a_cited_test_file_exists.py',
        'tests/architecture/docs/test_a_cited_test_function_exists.py',
    ),
    'configrender': ('supersedes', 'tests/architecture/test_the_family_config_is_rendered.py'),
    # NOT a second spelling of `datedlog`, which CONSTRUCTS `<base>/<yy>/<mm>/<dd>/<kind>/<name>` and
    # cannot write the four-digit, kind-less layout these readers are about. The argument is in the
    # readings half, `famtests/_datedmemory_readings.py`, because it is a fact about the readers.
    'datedmemory': ('supersedes', 'tests/architecture/test_memory_lives_under_a_date.py'),
    'hookinstall': ('supersedes', 'tests/architecture/test_the_declared_hooks_are_installed.py'),
    # NOT a second spelling of `bounded`, which OWNS THE WAIT -- it runs a child under a wall, reaps
    # the tree and prices the width. This owns THE SCAN. Measured 2026-09-18: the two surfaces share
    # no name and no argument type, the refusals are opposite in kind (terminate one live tree vs
    # return a pinnable set before anything runs), and only one of them reads a population and so
    # needs a floor. The argument is in the module, because it is a fact about the scanner.
    'untimedwaits': ('supersedes', 'tests/architecture/gate/test_no_untimed_subprocess.py'),
    # FOUR consumer rosters, not three: motronics holds TWO, one for `scripts/` and one for
    # `tests/architecture/`, and they declare DIFFERENT ceilings (40 and 50) over intervals that
    # exclude each other's value. That is why the bars are arguments here and not constants, and why
    # both motronics paths are named -- a single row would have read as one repo, one answer.
    'density': (
        'supersedes',
        'tests/architecture/_placement.py',
        'tests/architecture/layering/_helpers.py',
        'tests/architecture/layering/_tests_placement.py',
    ),
    'placement': (
        'supersedes',
        'tests/architecture/_placement.py',
        'tests/architecture/layering/_helpers.py',
        'tests/architecture/layering/_tests_placement.py',
    ),
    'rostercensus': ('supersedes', 'tests/architecture/test_the_roster_is_re_read_against_the_kit.py'),
    'rulespages': (
        'supersedes',
        'tests/architecture/test_the_rules_pages_are_a_ratchet.py',
        'tests/architecture/ratchets/test_rules_line_ratchet.py',
    ),
    'visibility': ('supersedes', 'tests/architecture/test_this_checkout_is_visible_on_origin.py'),
    # -- `lab_commons.dev.githooks`.
    'bootstrap': ('supersedes', 'scripts/hooks/with-venv.sh'),
}
