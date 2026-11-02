"""WHAT EACH PUBLISHED `dev_lab.dev` MODULE REPLACED -- DATA, one row per module that makes a claim.

READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported, so every value here
is a literal. `undeclared_modules` is the mechanism that makes this file a ratchet rather than a
habit: a published module with no row reds, and a row naming no module reds too.

THREE KINDS, AND ONLY THE FIRST IS A PROVENANCE CLAIM. The first two live here; the third is a
bare name in `_original_rows.py`, because it claims nothing about any consumer file.

* `supersedes` -- this module replaced those consumer files, whole or in part. This is the only kind
  the census's PROVENANCE detector reads.
* `adopted_by` -- the consumer file DELEGATES to this module and stays. Recorded because the
  distinction is exactly what a docstring cannot make: prose that names a file names it for both
  reasons at once, which is how `verify`'s mention of `scripts/gate/runner.py` (carved FROM, 0 of 51
  names shared) became the false positive that `named_only` exists to hold.
* `original` -- no consumer fork behind it. It is a DECLARATION, refusable by a reader: `forge` is
  the row to look at first, because consumer-a's `scripts/repo/forge_protect.py` shares `Forge`
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
    # THE TWO ROWS THE `__init__`-ONLY BLINDNESS HID, added 2026-09-18 in the commit that closed it.
    # Neither is new; both were published, imported and unreadable to the ratchet, because
    # `_published` drops any path with a private part and `__init__.py` has one. A guard that cannot
    # SEE a module cannot notice it has no row, which is the failure mode that reads exactly like
    # compliance.
    #
    # `agenthooks` SUPERSEDES the engine that lived in exactly ONE repo. `hooks` authored the deny
    # registry and `hook_adoption` rendered it into the engine's JSON, while the engine itself was
    # consumer-a' file alone -- so a repo could render a correct `deny-rules.json` and be left with an
    # inert declaration that reads as a guard.
    'agenthooks': ('supersedes', '.claude/hooks/deny-commands.js'),
    # `githooks` SUPERSEDES the copies, and the drift is the measurement rather than the argument:
    # `bump-version.sh` existed in consumer-a and in consumer-b, and the two had diverged in ONE
    # direction for months, every fix landing in whichever copy its author's defect hit. ONE path is
    # named, not two: `scripts/hooks/bump-version.sh` is live at the consumer-a lane `bc8ca7cc6`, and
    # consumer-b has no copy at `ef5fa9fc` -- checked before writing, because a row naming a path that
    # does not exist downgrades a live fork to no finding at all, silently and in the flattering
    # direction. That happened here on 2026-09-18 and is why the check is now the habit.
    'githooks': ('supersedes', 'scripts/hooks/bump-version.sh'),
    'bounded': (
        'supersedes',
        'scripts/gate/bounded.py',
        'scripts/gate/_box.py',
        'scripts/gate/wall_reason.py',
        'scripts/gate/width.py',
    ),
    'bypath': ('supersedes', 'scripts/gate/_by_path.py'),
    'checkout': (
        'supersedes',
        'scripts/lanes/prune_origin_branches.py',
        'scripts/lanes/session_branches.py',
        'scripts/repo/worktree_debris.py',
    ),
    'codeplace': ('supersedes', 'tests/architecture/repo/test_code_lives_only_where_code_belongs.py'),
    'scratch': (
        'supersedes',
        'scripts/clean/scratch.py',
        'tests/architecture/repo/test_scratch_is_archived_or_promoted.py',
    ),
    'datedlog': ('supersedes', 'scripts/gate/_dated.py'),
    'dep': ('supersedes', 'scripts/gate/native_install.py'),
    # THREE implementations existed -- consumer-a `scripts/repo/docs.py`, consumer-b `scripts/docs.py`,
    # consumer-c `scripts/pdoc`. The table stayed with each repo, so this is adoption, not a move.
    'docsite': ('adopted_by', 'scripts/repo/docs.py'),
    # SUPERSEDES consumer-b's `scripts/durations.py`, which is the LEDGER half and nothing else -- the
    # verdict taken on it stays in that repo's `test_slow_is_discovered_by_the_wall.py`, which is
    # therefore NOT named here: it holds `WALL_SECONDS`, `SLOW_BAR`, `FAST_CEILING`, the ledger floor
    # and the marked NAME set, all five of them repo facts. The two readings that file wrote --
    # `unmarked_but_slow` and `marked_but_fast` -- DO move, which is why this is a supersession of one
    # file and an adoption of nothing: the consumer deletes its `scripts/durations.py` and keeps its
    # own bars. Checked before writing: that path is live in consumer-b today.
    'durations': ('supersedes', 'scripts/durations.py'),
    # The floor refusal was written EIGHT times across this family and no two copies agreed -- four
    # standalone bodies raising four different exception types, three of them here in `src/`; three
    # more inlined at the top of a larger arm; and consumer-b's `bind_floor`. TWO of the four are both
    # named `VacuousScan` over DIFFERENT base classes, in this one repo. The consumer path named is
    # the one that PUBLISHED the helper; consumer-c's EIGHT inline copies have no path to name.
    'floors': ('supersedes', 'tests/architecture/_corpus.py'),
    'gatebase': ('supersedes', 'scripts/gate/base.py'),
    'hook_adoption': ('supersedes', 'scripts/repo/write_deny_rules.py'),
    'hook_install': ('supersedes', 'scripts/repo/_hooks.py'),
    # Both named by `netverb`'s docstring as the vacuum it closes, and both ADOPTED it on 2026-09-17
    # while staying: consumer-b's roster carries one as SPLITS and the other as STAYS.
    'netverb': ('adopted_by', 'scripts/pull_all.py', 'scripts/consumer-b-update.sh'),
    # `supersedes` AND NOT `adopted_by`, and the distinction is load-bearing here: the whole of
    # `_transcript.py` except its `[census]` grammar is on this page, so the consumer file is meant
    # to SHRINK to that grammar rather than to delegate and stay. It cannot do either until a
    # release carrying this module reaches that repo -- the row is the claim, not the landing.
    'pytestout': ('supersedes', 'scripts/gate/_transcript.py'),
    # ADOPTED_BY, AND NOT `supersedes`, BECAUSE BOTH FILES STAY AND BOTH DELEGATE: the reader half of
    # `tests/_config_census.py` moved here under a spelling-complete table, leaving that file its
    # placement machinery, and `tests/test_a_waiver_wider_than_an_ignore_is_declared.py` kept its
    # floors and its bar while its reading moved. Both import from this module today, which is what
    # makes the row checkable rather than a claim -- `supersedes` would name two files that keep every
    # line they have.
    'ruffwaivers': (
        'adopted_by',
        'tests/_config_census.py',
        'tests/test_a_waiver_wider_than_an_ignore_is_declared.py',
    ),
    'seams': ('supersedes', 'scripts/gate/seam_install.py'),
    'selfbuild': ('supersedes', 'scripts/gate/native_install.py'),
    'shadow_build': ('supersedes', 'scripts/gate/native_ab.py'),
    'shards': ('supersedes', 'scripts/gate/_shards.py'),
    'symcov': ('supersedes', 'scripts/repo/_symbol_coverage.py'),
    # THE CENSUS OVER `collectscope`, AND IT IS A RENAME RATHER THAN A CARVING: git records
    # `R052 tests/_collect_census.py -> src/dev_lab/dev/collectcensus.py` in the commit that made
    # this repo stop holding consumers' rows, and the path named here no longer exists. The file that
    # answered this question used to sit in this repo's OWN test tree, which is a consumer of the kit
    # like any other -- the `approxfloors` row below already establishes that. Its rows half,
    # `tests/_collect_census_rows.py`, STAYED and is this repo's own row rather than any other
    # repo's, so the row is not a licence to read that file as a consumer's.
    'collectcensus': ('supersedes', 'tests/_collect_census.py'),
    # 'original' until 2026-09-18, when the assertion-SHAPE reader landed here and took the whole
    # reading half of a consumer's vacuous-assert lint -- its `_called_name`, `_is_assertion`,
    # `_is_vacuous_assert` and its walk. The consumer keeps its own floors and its bar, which is the
    # population half `collect` and `census` already own; what moved is the reading.
    'testfacts': ('supersedes', 'tests/architecture/ratchets/test_no_test_asserts_only_is_not_none.py'),
    'treedirt': ('supersedes', 'scripts/gate/tree_state.py'),
    # `scripts/gate/runner.py` is the tree this was CARVED FROM and it stayed: it shares 0 of its 51
    # names with this module. Naming it `supersedes` is the mistake this kind exists to refuse.
    'verify': ('adopted_by', 'scripts/gate/runner.py'),
    # -- `dev_lab.dev.famtests`, the shared assertion bodies. Each replaces a consumer's whole
    #    test file, which is the class of row that has no import to be found by: a test file that
    #    has not adopted the body yet imports nothing from the kit at all.
    'agentguard': ('supersedes', 'tests/architecture/test_the_agent_guard_is_live.py'),
    'allowguard': ('supersedes', 'tests/architecture/test_no_allow_entry_names_a_denied_shape.py'),
    # THREE consumer files under THREE names, and the third is this repo's own -- a kit guard is a
    # consumer of the kit like any other. They do not agree on the BAR: `test_arch_every_approx...`
    # requires `abs=` unconditionally, the other two only under a stated `rel=`, and the two convict
    # different sets. That disagreement is what made `bar` a member of a published set rather than a
    # constant. NOT consumer-b's `test_absolute_tolerances_state_their_unit.py`, which reads the VALUE of
    # an `abs=` and asks whether it is spelled as a named unit -- the adjacent question, and naming it
    # here would be the over-conviction `named_only` exists to hold.
    'approxfloors': (
        'supersedes',
        'tests/test_arch_every_approx_states_its_floor.py',
        'tests/architecture/test_a_relative_tolerance_carries_its_floor.py',
        'tests/architecture/ratchets/test_approx_rel_requires_abs.py',
    ),
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
    # THREE consumer files under ONE filename, which is the counter-example to this package's own
    # counter-example: the two labs' copies share their nine test-function NAMES line for line and
    # differ in four values. NOT a second spelling of an injected-width body: measured 2026-09-18,
    # `dev.cjk` and `dev.docwidth` publish 12 and 14 names with an EMPTY intersection, the declared
    # set is keyed by FILE here and by `path:line` there, and only the width guard has a ceiling on
    # its escape hatch. The argument is in the module, because it is a fact about the two scanners.
    'trackedcjk': ('supersedes', 'tests/architecture/test_no_cjk_in_tracked_source.py'),
    # THE OTHER HALF OF THAT PAIR, and a separate row for the reasons `trackedcjk` records. The two
    # bodies each refuse the OTHER's ledger shape -- a SITE here, a FILE there -- which is what keeps
    # a consumer from copying one declaration into the other file, where it would pass every arm but
    # orphan every entry. Also NOT `famtests.rulespages`: that pins how many LINES a page has and
    # sums the pins; this caps how long a line IS. One page measured 32 lines at 694 columns.
    'injectedwidth': ('supersedes', 'tests/architecture/test_injected_doc_width_ceiling.py'),
    # TWO consumers in TWO LANGUAGES and they do not agree on the policy: consumer-b BANS the bound with
    # an exemption set it asserts is empty, consumer-a requires it to be DECLARED with its reason
    # because two of its crates are ABI-coupled and unbounding either alone produces a pairing that
    # does not compile. Both right for their repo, so `policy` is a member of a published set.
    # NOT `installdoor`, which reads the same `optional-dependencies` table and asks whether the door
    # DELIVERS the kit -- a floating requirement reaching an install, against a ceiling nobody
    # re-argued. The readings half, `famtests/_upperbounds_readings.py`, is private and has no row.
    'upperbounds': (
        'supersedes',
        'tests/architecture/test_dependencies_take_the_latest.py',
        'tests/architecture/repo/test_no_rust_dependency_carries_an_undeclared_upper_bound.py',
    ),
    # NOT a second spelling of `datedlog`, which CONSTRUCTS `<base>/<yy>/<mm>/<dd>/<kind>/<name>` and
    # cannot write the four-digit, kind-less layout these readers are about. The argument is in the
    # readings half, `famtests/_datedmemory_readings.py`, because it is a fact about the readers.
    'datedmemory': ('supersedes', 'tests/architecture/test_memory_lives_under_a_date.py'),
    'hookinstall': ('supersedes', 'tests/architecture/test_the_declared_hooks_are_installed.py'),
    'noreflection': ('supersedes', 'tests/architecture/ratchets/test_no_reflection_in_production.py'),
    # TWO consumer copies under ONE filename, 91.5% identical in CODE, and a byte diff says the 8.5%
    # is a docstring plus one noun -- the repo's own name, four times. `dev_lab.dev.dep` already
    # published the MECHANISM (`Port`, `mutate`, the two gap sentences, the refusal, the retirement);
    # the ASSERTIONS over it were what stayed forked, which is the class of row that has no import to
    # be found by. NOT a second spelling of `dep` itself: that module OWNS the door -- it composes the
    # argv, refuses, retires and renders -- and this only asserts on what it returned. It plants a holder
    # solely so an ADAPTER can be caught answering "nobody" forever, and asserts nothing about exclusion.
    'depdoor': ('supersedes', 'tests/architecture/test_the_dependency_door_is_wired.py'),
    # NOT a second spelling of `bounded`, which OWNS THE WAIT -- it runs a child under a wall, reaps
    # the tree and prices the width. This owns THE SCAN. Measured 2026-09-18: the two surfaces share
    # no name and no argument type, the refusals are opposite in kind (terminate one live tree vs
    # return a pinnable set before anything runs), and only one of them reads a population and so
    # needs a floor. The argument is in the module, because it is a fact about the scanner.
    'untimedwaits': ('supersedes', 'tests/architecture/gate/test_no_untimed_subprocess.py'),
    'boundedremedy': ('supersedes', 'tests/architecture/test_a_bounded_wait_names_its_remedy.py'),
    # FOUR consumer rosters, not three: consumer-a holds TWO, one for `scripts/` and one for
    # `tests/architecture/`, and they declare DIFFERENT ceilings (40 and 50) over intervals that
    # exclude each other's value. That is why the bars are arguments here and not constants, and why
    # both consumer-a paths are named -- a single row would have read as one repo, one answer.
    #
    # THE CONSUMER TEST FILES ARE NAMED AS WELL AS THE HELPERS, ADDED 2026-09-18, and the reason is
    # that leaving them out made the instrument lie in the FLATTERING direction. Both rows listed only
    # the private helper modules the halves were carved from, so the census's PROVENANCE detector had
    # nothing to match the consumer's own test file against and graded
    # `test_the_migration_boundary_is_declared.py` as CONSULTS -- a row that HAS done the work reading
    # as not-done, which is the one error nobody goes looking for. VERIFIED before being written, at
    # each repo's own tree: both labs' file imports `famtests.placement` AND `famtests.density`, and
    # consumer-a' `test_migration_boundary_density.py` imports both at b44bc330c. Its three siblings
    # there do NOT and are deliberately absent -- naming an unadopted file would be the same lie
    # pointing the other way.
    # A PATH THAT DOES NOT EXIST DOWNGRADES A FINDING TO NO FINDING, added 2026-09-18. Both rows named
    # `tests/architecture/_placement.py`, which is the LABS' spelling; consumer-a' file is one segment
    # deeper at `tests/architecture/layering/_placement.py`, and matching is by SUFFIX, so the row
    # reached neither. That file imports nothing from the kit while `famtests.placement` says adopting
    # it "is an import rather than a rewrite" -- a LIVE FORK, and it graded `untouched` rather than
    # `named_only` purely because the detector was pointed somewhere empty. A stale path does not fail
    # loudly; it is silent in the flattering direction, which is the second time today.
    'density': (
        'supersedes',
        'tests/architecture/_placement.py',
        'tests/architecture/layering/_placement.py',
        'tests/architecture/layering/_helpers.py',
        'tests/architecture/layering/_tests_placement.py',
        'tests/architecture/test_the_migration_boundary_is_declared.py',
        'tests/architecture/layering/test_migration_boundary_density.py',
    ),
    'placement': (
        'supersedes',
        'tests/architecture/_placement.py',
        'tests/architecture/layering/_placement.py',
        'tests/architecture/layering/_helpers.py',
        'tests/architecture/layering/_tests_placement.py',
        'tests/architecture/test_the_migration_boundary_is_declared.py',
        'tests/architecture/layering/test_migration_boundary_density.py',
    ),
    'rostercensus': ('supersedes', 'tests/architecture/test_the_roster_is_re_read_against_the_kit.py'),
    'rulespages': (
        'supersedes',
        'tests/architecture/test_the_rules_pages_are_a_ratchet.py',
        'tests/architecture/ratchets/test_rules_line_ratchet.py',
    ),
    'visibility': ('supersedes', 'tests/architecture/test_this_checkout_is_visible_on_origin.py'),
    # ORIGINAL, and the declaration is refusable in the usual way. The Windows interpreter spelling
    # it replaces was never a consumer MODULE -- it was a hand-written string in two repos'
    # `scripts/deny_rules.py` and in three tracked `settings.json` allow rows, pasted out of this
    # kit's own consumption recipe. There is no fork behind this, only a spelling it takes over, so
    # `supersedes` would name files that keep every line they have. Not `adopted_by` either: no
    # consumer delegates to it yet, and recording an adoption that has not happened is the
    # declaration-that-lies this registry exists to refuse.
    # SUPERSEDES consumer-c's file whole. ONE consumer path and not two, and the second repo is the
    # evidence for the row rather than a member of it: consumer-b cites `NAMED-SETS-NOT-COUNTS` at six
    # modules that merely USE named sets and has NO count-pin guard, so there is no file of its to
    # supersede -- naming one would be the over-conviction `named_only` exists to hold. Checked
    # before writing: `tests/architecture/test_a_pin_is_a_named_set.py` is live in consumer-c today,
    # and it is that repo's last open roster row.
    'countpins': ('supersedes', 'tests/architecture/test_a_pin_is_a_named_set.py'),
}
