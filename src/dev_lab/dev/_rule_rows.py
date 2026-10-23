"""The rules registry, FIRST half -- pure DATA, one row per universal rule.

A row is ``(id, statement, mechanisms)``. The statement is the constraint IN THE WORDS THE SHARED
SOURCE OWNS: it is authored once, here, and the repo that adopted the rule keeps a rules page that
cites the ID and adds only its own incident evidence. The mechanisms are the tests or lint codes
that refuse a violation, repo-relative to the adopting tree, in the same shape
``tests/architecture/docs/test_enforced_registry.py`` already uses: a path string, or a
``('ruff', CODE)`` pair.

WHICH RULES ARE HERE, and the test is mechanical rather than a judgement call: **delete every domain
noun from the rule -- if it still constrains anything, it is universal.** The rows below survived
that test. What did not stay home: the reference ladder (one vendor first, a second vendor second),
the cross-solver declaration rule, the resource-search-path rule, the adapter's clean-full-model
rule, and this repo's own dependency arrow and case conventions.

THE EVIDENCE DOES NOT LIVE HERE. Each rule exists because something went wrong, and the incident
that produced it -- the date, the measurement, the user quote -- stays in the repo that lived it, as
a note attached to the ID. This file is what the four repos must AGREE about; the reasons they agree
are each repo's own record.

ROWS ARE NEVER DELETED TO MAKE SOMETHING PASS. A row whose mechanism has gone is a red, and the
repair is to restore the mechanism or repoint the row at whatever refuses the hazard now. Deleting
the row is the one repair that turns a guarantee back into prose, and it is the repair a red suite
makes look cheapest.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'DECLARATION-LIES',
        (
            'A declaration that lies is the dominant defect -- a docstring, a name, a type hint or a status '
            'asserting a property the code does not enforce -- so prefer a declaration the code MUST consult, and '
            'prefer changing the CODE to match the declaration.'
        ),
        (
            'tests/architecture/docs/test_prose_that_cites_a_registry_is_read_off_it.py',
            'tests/architecture/docs/test_a_cited_test_file_exists.py',
            'tests/architecture/docs/test_a_cited_test_function_exists.py',
        ),
    ),
    (
        'PLANTED-CONTROL',
        (
            'A scope claim needs its own test that PLANTS the thing in the region and calls the REAL guard, and a '
            'fix is checked by reverting the fix, keeping the prose and running the suite.'
        ),
        (
            'tests/architecture/meta/test_a_scan_style_guard_binds_a_floor.py',
            'tests/architecture/ratchets/test_the_pin_partitions_refuse_a_bad_row.py',
            'tests/architecture/layering/test_the_placement_partitions_refuse_a_bad_row.py',
        ),
    ),
    (
        'FLOOR-ON-EVERY-SCAN',
        (
            'Give every scan a floor, because finding NOTHING is vacuous rather than green and an assertion that '
            'cannot distinguish a clean tree from an unread one is not evidence; if a miss falls back, remove the '
            'FALLBACK, since a claim no test could have failed is worse than no claim.'
        ),
        (
            'tests/population_floor.py',
            'tests/architecture/meta/test_a_scan_style_guard_binds_a_floor.py',
            'tests/architecture/gate/test_the_population_floor_rule_is_one_rule.py',
        ),
    ),
    (
        'ESCAPE-HATCH-CEILING',
        (
            'An escape hatch needs a CEILING, not just a reason -- pin the RATIO between two operating points, '
            'never the value at one -- because a waiver no one must justify is how a check reaches zero without '
            'anything being fixed.'
        ),
        (
            'tests/architecture/ratchets/test_suppression_ratchet.py',
            'tests/architecture/ratchets/test_skip_ratchet.py',
            'tests/architecture/ratchets/test_unjustified_bound_ratchet.py',
            'tests/architecture/ratchets/test_disabled_rule_ratchet.py',
        ),
    ),
    (
        'RATCHET-TWO-SIDES',
        (
            'A ratchet has two sides -- a capability that disappears, or a waiver nothing uses, is as wrong as its '
            'opposite -- and a budget freed by a shrink is paid back in the same commit, never banked as slack '
            'for the next arrival.'
        ),
        (
            'tests/architecture/ratchets/test_module_alarm.py',
            'tests/architecture/ratchets/_oversized_debt.py',
            'tests/architecture/gate/test_the_tier_partition_is_total.py',
        ),
    ),
    (
        'NAMED-SETS-NOT-COUNTS',
        (
            'Declared data beats a hand-kept list, and a pin is a NAMED SET, never a count: an integer cannot '
            'say which row moved, so a reader cannot tell a delivered capability from a pending one and the '
            'honest-looking repair when it disagrees is to edit the digit.'
        ),
        (
            'tests/architecture/ratchets/test_the_pin_partitions_refuse_a_bad_row.py',
            'tests/architecture/gate/_heavy_by_path_pins.py',
            'tests/architecture/docs/test_the_family_table_is_rendered_from_the_registry.py',
        ),
    ),
    (
        'FIX-THE-CAUSE',
        (
            'Fix the CAUSE at the source, at EVERY site, since a patched symptom stops advertising its cause: no '
            '`_legacy`/`_compat` wrappers, no deprecation aliases, no dual entry points, and callers and tests '
            'move WITH the code.'
        ),
        (
            'tests/architecture/declarations/test_a_module_level_name_has_one_definition.py',
            'tests/architecture/repo/test_no_public_name_has_two_definitions.py',
            'tests/architecture/repo/test_no_module_binds_one_name_twice.py',
        ),
    ),
    (
        'RETIRED-NAMES-REGISTERED',
        (
            'A retired spelling is REGISTERED with its replacement and its reason in the same commit, and it survives '
            'longest in PROSE: name the REPLACEMENT and point at the registry, and prefer naming the SHAPE of a thing '
            'over naming an example of it, because an example is a spelling waiting to be retired.'
        ),
        (
            'tests/architecture/docs/test_retired.py',
            'tests/architecture/docs/test_retired_replacements_resolve.py',
            'tests/architecture/docs/test_retired_self_exclusion.py',
        ),
    ),
    (
        'REGISTRY-OWNS-THE-DECISION',
        (
            'Baggage is generated daily rather than inherited: before branching on a kind, a type or a '
            'vendor, ask which registry owns that decision -- and if none does, the REGISTRY is the '
            'deliverable rather than the branch.'
        ),
        (
            'tests/architecture/docs/test_the_family_table_is_rendered_from_the_registry.py',
            'tests/architecture/domain/test_node_kind_is_declared.py',
            'tests/architecture/domain/test_case_family_is_declared.py',
        ),
    ),
    (
        'IMPLEMENT-EVERYTHING',
        (
            'Every combination that CAN run goes through the same path with no capability guard keeping a '
            'working-but-imprecise one out -- it returns the result plus a machine-readable accuracy tag carrying '
            'the MEASURED deviation, never a fabricated number -- while what physically cannot run degrades to a '
            'working path or RAISES, and a warning on an unchanged success return is the forbidden shape, because '
            'the CALLER must be able to tell.'
        ),
        (
            'tests/architecture/declarations/test_every_capability_row_is_reachable.py',
            'tests/architecture/declarations/test_no_silent_substitution.py',
            'tests/unit/hamilton/registry/test_solver_capabilities.py',
        ),
    ),
    (
        'UNSUPPORTED-RAISES',
        (
            'An unsupported combination RAISES, never silently wrong: capability and method coverage is '
            'DECLARED data, so what cannot run says so in a registry rather than in a branch nobody reads.'
        ),
        (
            'tests/architecture/declarations/test_every_capability_row_is_reachable.py',
            'tests/unit/hamilton/registry/test_solver_capabilities.py',
        ),
    ),
    (
        'XFAIL-NOT-SKIP',
        (
            'A known failure is an `xfail` carrying its residual, never a `skip`: a skip is the one '
            'disposition that records nothing, so it makes work that stopped working indistinguishable from '
            'work that was never reachable.'
        ),
        (
            'tests/architecture/ratchets/test_skip_ratchet.py',
            'tests/architecture/ratchets/_skip_pins.py',
        ),
    ),
    (
        'BAR-IS-A-CONSTANT',
        (
            'Every bar is a constant naming its statistic with no per-case override path -- a case writes results, '
            'reference values and failure reasons, never the bar it is judged by -- and a cell below the bar is a '
            'failure ON RECORD with its residual, never a loosened band, a skip, or a bypass.'
        ),
        (
            'tests/integration/acceptance/test_case_declarations.py',
            'tests/unit/contracts/results/test_a_cell_that_meets_the_bar_is_on_record_too.py',
        ),
    ),
    (
        'DOCS-SPLIT',
        (
            'The always-loaded rules files are HARD CONSTRAINTS ONLY, read on every turn, while MECHANISM lives in '
            'a docs tree kept apart from them by a line ratchet, and a hazard already refused is recorded as a '
            'row naming its live mechanism, never re-argued in prose.'
        ),
        (
            'tests/architecture/ratchets/test_rules_line_ratchet.py',
            'tests/architecture/ratchets/test_config_line_ratchet.py',
            'tests/architecture/docs/test_docs_are_bullets_not_wrapped.py',
            'tests/architecture/docs/test_no_prose_markdown_under_source_trees.py',
        ),
    ),
    (
        'MEMORY-SHAPE',
        (
            'Memory keeps as much as possible and removes redundancy by MERGING, never deleting -- an entry leaves '
            'only by being folded into a live entry that names it in `merged_from`, keeping its measurements and '
            'refuted hypotheses -- and each entry lives under a dated YYYY/MM/DD path with frontmatter, the index '
            'is generated from what is there rather than curated beside it, and a task lands its state file with '
            'the commit that completes it.'
        ),
        (
            'tests/architecture/repo/test_memory_lives_in_dated_directories.py',
            'tests/architecture/docs/test_memory_files_live_under_a_dated_directory.py',
            'tests/architecture/docs/test_memory_index_map.py',
            'tests/architecture/docs/test_memory_leaves_only_by_merging.py',
        ),
    ),
    (
        'MONTHLY-PLANS-CARRIED',
        (
            'Every month holding a memory entry carries `YYYY/MM/SUMMARY-YYYY-MM.md`, whose `## Plans` section '
            'lists every plan the previous summary left open or partial, and an entry closes only by naming its '
            'evidence.'
        ),
        ('tests/test_famtests_monthsummary.py',),
    ),
    (
        'PUBLIC-SURFACE-DECLARED',
        (
            'A module declares its public surface, and one name has one definition -- a second spelling of '
            'the same name is a defect that only the merged tree can see.'
        ),
        (
            'tests/architecture/declarations/test_every_module_declares_its_public_surface.py',
            'tests/architecture/repo/test_no_public_name_has_two_definitions.py',
        ),
    ),
    (
        'MODULE-SIZE-ALARM',
        (
            'A module past the size band MUST be refactored -- a new one, one that GROWS, or a pin for one that '
            'was already fixed -- and while the band is repo data, that there IS one is not.'
        ),
        ('tests/architecture/ratchets/test_module_alarm.py',),
    ),
    (
        'LATEST-DEPENDENCIES',
        (
            'A third-party dependency moves to the LATEST, aggressively -- a floor is a statement and an upper '
            'bound is a ceiling nobody re-argued -- and since the environment a verdict was measured in is part of '
            'the verdict, a package moving underneath one invalidates it rather than ageing it.'
        ),
        (
            'tests/architecture/repo/test_no_rust_dependency_carries_an_undeclared_upper_bound.py',
            'tests/architecture/declarations/test_one_python_version_source.py',
            'tests/unit/scripts/test_local_envkey.py',
        ),
    ),
    (
        'SHARED-CHECKOUT',
        (
            'A box holds a SHARED, possibly concurrent checkout: there is NO single-agent mode, the remote IS '
            'the only shared medium, pushing is the obligation rather than the last step of landing, and a '
            'verdict cannot be delegated to someone who cannot see the code.'
        ),
        (
            # THE SHARED MECHANISM FIRST, and that ordering is the correction of 2026-09-16: the
            # three rows this replaces named one consumer's paths, which resolve in exactly one checkout
            # on earth, so the registry's own docstring already called it "a shared row that grades
            # every repo against one repo's paths". `dev.checkout` asks git the question in any of
            # them.
            'src/dev_lab/dev/checkout.py',
            'tests/test_dev_checkout.py',
        ),
    ),
    (
        'VERDICT-BAR-IS-THE-INCREMENT',
        (
            'A verdict answers for the INCREMENT that produced it, not the tree, so a red it did not cause is '
            'inventory; lane and integration pushes are admitted with no result (parts are produced FROM pushed '
            'shas), while the trunk needs every tests/<part> part of HEAD on the forge a PASS of scope full and is '
            'refused, with no local fallback, when a part is missing, unsettled, failing or incremental, or the '
            'forge is unreadable.'
        ),
        (
            'src/dev_lab/dev/pushgate.py',
            'tests/test_dev_pushgate.py',
            'tests/architecture/gate/test_the_message_check_judges_the_push_increment.py',
        ),
    ),
    (
        'REFUSAL-NAMES-THE-REMEDY',
        (
            'Take the remedy a refusal NAMES, bound every wait because a budget is a ceiling on the WAIT (split or '
            'parallelise, never raise it), and kill a process TREE by its ROOT pid, since stopping a wrapper '
            'leaves its children running.'
        ),
        (
            # The bounded wait, the width the refusal must consult before it names a remedy, and
            # the ONE tree killer -- all three shared, so the citation is true in every checkout.
            'src/dev_lab/dev/bounded.py',
            'src/lab_commons/proc.py',
            'tests/test_dev_bounded.py',
        ),
    ),
    (
        'NETWORK-RETRY-THEN-REPORT',
        (
            'The forge is a REMOTE service: a network verb goes through the retry wrapper rather than being '
            'called directly, and a write that still fails is REPORTED with its diagnosis instead of hammered.'
        ),
        (
            'scripts/hooks/with-retry.sh',
            'tests/architecture/gate/test_git_network_calls_go_through_the_retry_wrapper.py',
        ),
    ),
    (
        'PRODUCTION-ENTRY-POINT',
        (
            'Reproduce a behaviour through the PRODUCTION entry point, never an ad-hoc script handed out beside '
            'it, and treat a behaviour not reachable from there as a gap to FIX, the boundary being the SUBJECT, '
            'not the tree the code happens to live in.'
        ),
        (
            'src/dev_lab/dev/famtests/placement.py',
            'tests/architecture/layering/test_scripts_hold_no_domain_code.py',
        ),
    ),
    (
        'NO-LAZY-IMPORT',
        (
            'No lazy imports, except an unavoidable circular or heavy-optional one with its reason written '
            'down: an import graph a cost model reads must be exact, and a deferred import makes it a guess.'
        ),
        (('ruff', 'PLC0415'),),
    ),
    (
        'HOOKS-ARE-WIRED',
        (
            'Shipping a hook without wiring it is the declaration-that-lies in tooling form: a declared hook '
            'absent from the directory the tool actually consults must FAIL LOUDLY rather than sit there '
            'reading as protection.'
        ),
        (
            'src/dev_lab/dev/hook_install.py',
            'tests/test_dev_hook_install.py',
        ),
    ),
    (
        'INSTALL-DOOR-DELIVERS-THE-DECLARATION',
        (
            # Why: the paths that mutate an environment are not the set named install, and two doors that differ by
            # one flag differ by a whole environment, which is how the defect hides.
            'PIN + FRESHNESS (user ruling 2026-10-17): the COMMITTED uv.lock is what an environment is, so every '
            'path that mutates one -- a bootstrap, a served venv, a host refresh, or a git hook spelled as a '
            'project run, an install door nobody declared -- is `uv sync --frozen` from the lock of the commit or '
            'does not touch the environment at all; the `lock` pre-push row refuses a hold below the newest with '
            'no reason and, on integration or trunk, a lock not at the newest (the forge relocks integration); and '
            'which commands re-resolve is MEASURED per tool, never read off a flag name.'
        ),
        ('tests/test_dev_installdoor.py', 'tests/test_dev_lockcheck.py'),
    ),
    (
        'AGENT-GUARD',
        (
            'A hand-written test invocation, a bare network git verb and a stash are refused by the shared '
            'deny machinery rather than by prose, so the refusal is identical in every repo that adopts it.'
        ),
        (
            '.claude/hooks/deny-commands.js',
            '.claude/hooks/deny-rules.json',
            'tests/architecture/gate/test_agent_bash_guard.py',
        ),
    ),
    (
        'TOLERANCE-CARRIES-A-UNIT',
        (
            'A relative tolerance is free and an absolute one is not (`epsilon = 1e-10 * L` is a statement about '
            'the unit its inputs are in, so the same call in metres tightens a test by 1000x): sweep for absolute '
            'tolerances BEFORE a rewrite, state the unit a golden was generated in, and never write a `rel=` '
            'without the `abs=` floor it is combined with.'
        ),
        ('tests/architecture/ratchets/test_approx_rel_requires_abs.py',),
    ),
    (
        'UNITS-GO-THROUGH-PINT',
        (
            'A unit is never spelled into a NAME but lives in the VALUE as a pint Quantity -- one rule, because '
            'once a name cannot carry a unit the value must, so `--slot-pitch-mm=12.5` typed as a bare float has '
            'nowhere left to keep its unit but pint -- and renaming such a flag without typing it DELETES the '
            'unit, which is worse than leaving it, while a name whose value IS already a Quantity is not a '
            'violation, since there the name merely repeats the unit.'
        ),
        (
            'tests/test_dev_units.py',
            'tests/test_no_name_carries_a_unit.py',
            # THE VALUE HALF, added 2026-09-16. The clause above about renaming-without-typing was
            # STATED here and enforced by nothing, so the name scan's cheapest green was the lossy
            # repair it warns against. `dev_lab.dev.quantity_values` is the mechanism, and it is
            # listed on THIS row rather than under a new ID because the row already argues the two
            # halves are one rule.
            'tests/test_dev_quantity_values.py',
        ),
    ),
    (
        'NO-CJK-IN-TRACKED-SOURCE',
        (
            'No tracked content may contain a CJK character, except under `.claude/memory/`, `attic/`, the '
            'repo-root `archived/`, and a `<stem>.zh.md` beside its English `<stem>.md` (an orphaned translation '
            'is refused by name), and a population too large for one commit is a RATCHET, not a loosened rule: a '
            'repo declares its files still carrying CJK as a NAMED SET that may only shrink, where a declared file '
            'with no CJK left is an ORPHANED waiver, refused like an undeclared one.'
        ),
        ('tests/test_dev_cjk.py',),
    ),
    (
        'INJECTED-DOC-WIDTH-CEILING',
        (
            'Every document injected into an agent -- `AGENTS.md`/`CLAUDE.md`, `.claude/rules/**` -- is capped per '
            'LINE at 120 columns, the ceiling the family already uses for code, declared as the same shrink-only '
            'named set the CJK ratchet uses, because a line-COUNT ratchet is blind to line length and a rewrite '
            'can double a page width while lowering its line count and read as an improvement.'
        ),
        ('tests/test_dev_docwidth.py',),
    ),
    (
        'ENV-MUTATION-THROUGH-THE-DOOR',
        (
            'No verdict may cite an environment it did not run in, so a dependency mutation goes through the '
            'shared door and is decided by STATE (which target environment is mutated, and whether a verdict is in '
            'flight for THAT environment), never by matching command TEXT: a mutation DURING a run is PREVENTED '
            'by exclusion, one BETWEEN runs is DETECTED by the key and remedied by RETIRING the verdict anchors, '
            'each worktree owns its environment (agents bootstrap and sync their own through the door without '
            'human approval, never mutating main from a lane), the box ledger stays machine-wide independently of '
            'environment exclusion, and a repo declaring no verdict anchors has that gap RENDERED, never silently '
            'skipped.'
        ),
        ('tests/test_dev_dep.py', 'tests/test_dev_dep_target.py'),
    ),
    (
        'ONE-BOX-ONE-LOCK',
        (
            # Why: a claim inside a kernel limit is never idle-but-held and never exceeded; a waiter starting anyway
            # is the harm, and blocking forever is a crash rendered as a hang; a reused pid would make a dead holder
            # immortal.
            'Every run on a machine DECLARES its demand -- cores, memory, a wall and tool seats -- on the ONE '
            'machine-wide box ledger every repo and session reaches (lab_commons.box, never a lock named in one '
            'tree), is admitted by the one rule on the MEASURED room (free now, less what held claims have not '
            'taken yet, less its [reserve] margins), and runs INSIDE a kernel limit sized to that claim that kills '
            'it past its memory or wall; a waiter holds nothing and gives up at its own queue ceiling, refused '
            'naming the dimension short and every holder with its deadline; a recorded holder is identified by '
            'more than its pid; and nothing is reserved, lent or preempted (user ruling 2026-10-14), priority '
            'ordering but never claiming.'
        ),
        (
            'tests/test_box.py',
            'tests/test_box_run_enforced.py',
            'tests/test_liveness.py',
        ),
    ),
)
