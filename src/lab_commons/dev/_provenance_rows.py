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
    # THE TWO ROWS THE `__init__`-ONLY BLINDNESS HID, added 2026-09-18 in the commit that closed it.
    # Neither is new; both were published, imported and unreadable to the ratchet, because
    # `_published` drops any path with a private part and `__init__.py` has one. A guard that cannot
    # SEE a module cannot notice it has no row, which is the failure mode that reads exactly like
    # compliance.
    #
    # `agenthooks` SUPERSEDES the engine that lived in exactly ONE repo. `hooks` authored the deny
    # registry and `hook_adoption` rendered it into the engine's JSON, while the engine itself was
    # motronics' file alone -- so a repo could render a correct `deny-rules.json` and be left with an
    # inert declaration that reads as a guard.
    'agenthooks': ('supersedes', '.claude/hooks/deny-commands.js'),
    # `githooks` SUPERSEDES the copies, and the drift is the measurement rather than the argument:
    # `bump-version.sh` existed in motronics-studio and in wdg-lab, and the two had diverged in ONE
    # direction for months, every fix landing in whichever copy its author's defect hit. ONE path is
    # named, not two: `scripts/hooks/bump-version.sh` is live at the motronics lane `bc8ca7cc6`, and
    # wdg-lab has no copy at `ef5fa9fc` -- checked before writing, because a row naming a path that
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
    # ORIGINAL rather than superseding `installdoor`, and the distinction is the whole row: it
    # asks whether one COMMAND delivers the declared build, this asks whether a repo's DOOR SET was
    # ever looked at and is still what was measured. Nothing anywhere in the family answered the
    # second -- three consumers adopted `installdoor` with three differently-shaped door sets and no
    # tree could see the other two. There is no path to name because there was no prior mechanism.
    'doorcensus': ('original',),
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
    # ORIGINAL rather than superseding motronics' `scripts/gate/dep_sync.py`, and the distinction is
    # the pair's whole point. That script MUTATES an environment and reports what it removed
    # AFTERWARDS; these two never touch one and answer BEFOREHAND, from command text joined to a
    # manifest. Nothing in the family answered "which extras survive" -- `_doorcensus_rows` names it
    # as an ABSENT mechanism rather than implying coverage -- so there is no prior code to name.
    # The TEST-TREE half of the same question, and the one `syncscope`'s docstring names as
    # unmeasurable from a manifest. No prior code in any repo read a test tree for its imports:
    # `testfacts` reads marks and timeouts from the same AST and never an import.
    'collectscope': ('original',),
    'synccensus': ('original',),
    'syncscope': ('original',),
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
    # THREE consumer files under THREE names, and the third is this repo's own -- a kit guard is a
    # consumer of the kit like any other. They do not agree on the BAR: `test_arch_every_approx...`
    # requires `abs=` unconditionally, the other two only under a stated `rel=`, and the two convict
    # different sets. That disagreement is what made `bar` a member of a published set rather than a
    # constant. NOT wdg-lab's `test_absolute_tolerances_state_their_unit.py`, which reads the VALUE of
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
    # TWO consumers in TWO LANGUAGES and they do not agree on the policy: wdg-lab BANS the bound with
    # an exemption set it asserts is empty, motronics requires it to be DECLARED with its reason
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
    # NOT a second spelling of `bounded`, which OWNS THE WAIT -- it runs a child under a wall, reaps
    # the tree and prices the width. This owns THE SCAN. Measured 2026-09-18: the two surfaces share
    # no name and no argument type, the refusals are opposite in kind (terminate one live tree vs
    # return a pinnable set before anything runs), and only one of them reads a population and so
    # needs a floor. The argument is in the module, because it is a fact about the scanner.
    'untimedwaits': ('supersedes', 'tests/architecture/gate/test_no_untimed_subprocess.py'),
    # THE OTHER HALF OF THAT PAIR, and the boundary was settled by measurement rather than by taste.
    # NOT inside `untimedwaits`, which is the SCAN: that one imports `ast`, takes a `Path`, returns a
    # pinnable SET, refuses BEFORE anything runs and needs a floor. This imports `subprocess`/`time`/
    # `os`, SPAWNS A REAL PROCESS TREE, asserts on ELAPSED TIME, refuses ONE LIVE WAIT and needs no
    # floor -- it has a calibration instead. Measured 2026-09-18: the overlap between the two
    # surfaces is EMPTY. NOT on `dev.bounded` either: 293 lines plus this body lands past the 400
    # band, and `famtests` is where a body a CONSUMER'S architecture test is judged by lives.
    # `untimedwaits`' own docstring already pointed at `bounded.wall_reason` for the sized-ceiling
    # claim; the pointer existed and the module it should have pointed at did not. The readings half,
    # `famtests/_boundedremedy_readings.py`, is private and has no row.
    'boundedremedy': ('supersedes', 'tests/architecture/test_a_bounded_wait_names_its_remedy.py'),
    # ORIGINAL, and it is the only kind it could honestly be: no consumer file asserts this, because
    # nobody had a word for the shape until `boundedremedy`'s own `wider_tier in text` clause was
    # driven on an absent tier word and passed in all three repos on 2026-09-18.
    # NOT inside `untimedwaits`, whose walk shape it shares: that one reads CALLS and asks whether a
    # wait declares a ceiling; this reads DATA FLOW inside one body and asks whether an assertion can
    # fail at all. Measured the same day, the two surfaces share `take_scan` and nothing else, and
    # one is entirely about `subprocess` while the other never mentions it. NOT inside `citedtests`
    # either, the nearest neighbour BY SUBJECT -- a declaration that lies -- which reads PROSE
    # against the whole tree where this cannot see across a single function boundary.
    'echoedtoken': ('original',),
    # FOUR consumer rosters, not three: motronics holds TWO, one for `scripts/` and one for
    # `tests/architecture/`, and they declare DIFFERENT ceilings (40 and 50) over intervals that
    # exclude each other's value. That is why the bars are arguments here and not constants, and why
    # both motronics paths are named -- a single row would have read as one repo, one answer.
    #
    # THE CONSUMER TEST FILES ARE NAMED AS WELL AS THE HELPERS, ADDED 2026-09-18, and the reason is
    # that leaving them out made the instrument lie in the FLATTERING direction. Both rows listed only
    # the private helper modules the halves were carved from, so the census's PROVENANCE detector had
    # nothing to match the consumer's own test file against and graded
    # `test_the_migration_boundary_is_declared.py` as CONSULTS -- a row that HAS done the work reading
    # as not-done, which is the one error nobody goes looking for. VERIFIED before being written, at
    # each repo's own tree: both labs' file imports `famtests.placement` AND `famtests.density`, and
    # motronics' `test_migration_boundary_density.py` imports both at b44bc330c. Its three siblings
    # there do NOT and are deliberately absent -- naming an unadopted file would be the same lie
    # pointing the other way.
    # A PATH THAT DOES NOT EXIST DOWNGRADES A FINDING TO NO FINDING, added 2026-09-18. Both rows named
    # `tests/architecture/_placement.py`, which is the LABS' spelling; motronics' file is one segment
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
    # -- `lab_commons.dev.githooks`.
    'bootstrap': ('supersedes', 'scripts/hooks/with-venv.sh'),
}
