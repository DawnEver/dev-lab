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
        'A declaration that lies is the dominant defect: a docstring, a name, a type hint or a status '
        'asserting a property the code does not enforce. Prefer a declaration the code MUST consult, and '
        'prefer changing the CODE to match the declaration.',
        (
            'tests/architecture/docs/test_prose_that_cites_a_registry_is_read_off_it.py',
            'tests/architecture/docs/test_a_cited_test_file_exists.py',
            'tests/architecture/docs/test_a_cited_test_function_exists.py',
        ),
    ),
    (
        'PLANTED-CONTROL',
        'A scope claim needs its own test -- one that PLANTS the thing in the region and calls the REAL '
        'guard. To check a fix: revert the fix, keep the prose, run the suite.',
        (
            'tests/architecture/meta/test_a_scan_style_guard_binds_a_floor.py',
            'tests/architecture/ratchets/test_the_pin_partitions_refuse_a_bad_row.py',
            'tests/architecture/layering/test_the_placement_partitions_refuse_a_bad_row.py',
        ),
    ),
    (
        'FLOOR-ON-EVERY-SCAN',
        'Give every scan a floor: finding NOTHING is vacuous rather than green, so an assertion that '
        'cannot distinguish a clean tree from an unread one is not evidence. If a miss falls back, remove '
        'the FALLBACK -- a claim no test could have failed is worse than no claim.',
        (
            'tests/population_floor.py',
            'tests/architecture/meta/test_a_scan_style_guard_binds_a_floor.py',
            'tests/architecture/gate/test_the_population_floor_rule_is_one_rule.py',
        ),
    ),
    (
        'ESCAPE-HATCH-CEILING',
        'An escape hatch needs a CEILING, not just a reason: pin the RATIO between two operating points, '
        'never the value at one. A waiver that no one must justify is how a check reaches zero without '
        'anything being fixed.',
        (
            'tests/architecture/ratchets/test_suppression_ratchet.py',
            'tests/architecture/ratchets/test_skip_ratchet.py',
            'tests/architecture/ratchets/test_unjustified_bound_ratchet.py',
            'tests/architecture/ratchets/test_disabled_rule_ratchet.py',
        ),
    ),
    (
        'RATCHET-TWO-SIDES',
        'A ratchet has two sides: a capability that disappears, or a waiver nothing uses, is as wrong as '
        'its opposite. A budget freed by a shrink is paid back in the same commit, never banked as slack '
        'for the next arrival.',
        (
            'tests/architecture/ratchets/test_module_alarm.py',
            'tests/architecture/ratchets/_oversized_debt.py',
            'tests/architecture/gate/test_the_tier_partition_is_total.py',
        ),
    ),
    (
        'NAMED-SETS-NOT-COUNTS',
        'Declared data beats a hand-kept list, and a pin is a NAMED SET, never a count: an integer cannot '
        'say which row moved, so a reader cannot tell a delivered capability from a pending one and the '
        'honest-looking repair when it disagrees is to edit the digit.',
        (
            'tests/architecture/ratchets/test_the_pin_partitions_refuse_a_bad_row.py',
            'tests/architecture/gate/_heavy_by_path_pins.py',
            'tests/architecture/docs/test_the_family_table_is_rendered_from_the_registry.py',
        ),
    ),
    (
        'FIX-THE-CAUSE',
        'Fix the CAUSE at the source, at EVERY site -- a patched symptom stops advertising its cause. No '
        '`_legacy`/`_compat` wrappers, no deprecation aliases, no dual entry points; callers and tests '
        'move WITH the code.',
        (
            'tests/architecture/declarations/test_a_module_level_name_has_one_definition.py',
            'tests/architecture/repo/test_no_public_name_has_two_definitions.py',
            'tests/architecture/repo/test_no_module_binds_one_name_twice.py',
        ),
    ),
    (
        'RETIRED-NAMES-REGISTERED',
        'A retired spelling is REGISTERED with its replacement and its reason in the same commit, and it '
        'survives longest in PROSE: name the REPLACEMENT and point at the registry, and prefer naming the '
        'SHAPE of a thing over naming an example of it, because an example is a spelling waiting to be '
        'retired.',
        (
            'tests/architecture/docs/test_retired.py',
            'tests/architecture/docs/test_retired_replacements_resolve.py',
            'tests/architecture/docs/test_retired_self_exclusion.py',
        ),
    ),
    (
        'REGISTRY-OWNS-THE-DECISION',
        'Baggage is generated daily rather than inherited: before branching on a kind, a type or a '
        'vendor, ask which registry owns that decision -- and if none does, the REGISTRY is the '
        'deliverable rather than the branch.',
        (
            'tests/architecture/docs/test_the_family_table_is_rendered_from_the_registry.py',
            'tests/architecture/domain/test_node_kind_is_declared.py',
            'tests/architecture/domain/test_case_family_is_declared.py',
        ),
    ),
    (
        'IMPLEMENT-EVERYTHING',
        'Every combination that CAN run goes through the same path, and no capability guard keeps a '
        'working-but-imprecise one out: return the result plus a machine-readable accuracy tag carrying '
        'the MEASURED deviation, and never fabricate a number. What physically cannot run degrades to a '
        'working path, or RAISES. A warning on an unchanged success return is the forbidden shape -- the '
        'test is whether the CALLER can tell.',
        (
            'tests/architecture/declarations/test_every_capability_row_is_reachable.py',
            'tests/architecture/declarations/test_no_silent_substitution.py',
            'tests/unit/hamilton/registry/test_solver_capabilities.py',
        ),
    ),
    (
        'UNSUPPORTED-RAISES',
        'An unsupported combination RAISES, never silently wrong: capability and method coverage is '
        'DECLARED data, so what cannot run says so in a registry rather than in a branch nobody reads.',
        (
            'tests/architecture/declarations/test_every_capability_row_is_reachable.py',
            'tests/unit/hamilton/registry/test_solver_capabilities.py',
        ),
    ),
    (
        'XFAIL-NOT-SKIP',
        'A known failure is an `xfail` carrying its residual, never a `skip`: a skip is the one '
        'disposition that records nothing, so it makes work that stopped working indistinguishable from '
        'work that was never reachable.',
        (
            'tests/architecture/ratchets/test_skip_ratchet.py',
            'tests/architecture/ratchets/_skip_pins.py',
        ),
    ),
    (
        'BAR-IS-A-CONSTANT',
        'Every bar is a constant naming its statistic, with no per-case override path: a case writes '
        'results, reference values and failure reasons -- never the bar it is judged by. A cell below the '
        'bar is a failure ON RECORD with its residual, never a loosened band, a skip, or a bypass.',
        (
            'tests/integration/acceptance/test_case_declarations.py',
            'tests/unit/contracts/results/test_a_cell_that_meets_the_bar_is_on_record_too.py',
        ),
    ),
    (
        'DOCS-SPLIT',
        'The always-loaded rules files are HARD CONSTRAINTS ONLY and are read on every turn; MECHANISM '
        'lives in a docs tree and a line ratchet keeps the two from merging. A hazard already refused is '
        'recorded as a row naming its live mechanism, never re-argued in prose.',
        (
            'tests/architecture/ratchets/test_rules_line_ratchet.py',
            'tests/architecture/ratchets/test_config_line_ratchet.py',
            'tests/architecture/docs/test_docs_are_bullets_not_wrapped.py',
            'tests/architecture/docs/test_no_prose_markdown_under_source_trees.py',
        ),
    ),
    (
        'MEMORY-SHAPE',
        'A memory entry lives under a dated YYYY/MM/DD path with frontmatter, the index is generated from '
        'what is there rather than curated beside it, and a task lands its state file with the commit '
        'that completes it.',
        (
            'tests/architecture/repo/test_memory_lives_in_dated_directories.py',
            'tests/architecture/docs/test_memory_files_live_under_a_dated_directory.py',
            'tests/architecture/docs/test_memory_index_map.py',
        ),
    ),
    (
        'PUBLIC-SURFACE-DECLARED',
        'A module declares its public surface, and one name has one definition -- a second spelling of '
        'the same name is a defect that only the merged tree can see.',
        (
            'tests/architecture/declarations/test_every_module_declares_its_public_surface.py',
            'tests/architecture/repo/test_no_public_name_has_two_definitions.py',
        ),
    ),
    (
        'MODULE-SIZE-ALARM',
        'A module past the size band MUST be refactored -- a new one, one that GROWS, or a pin for one '
        'that was already fixed. The band is repo data; that there IS one is not.',
        ('tests/architecture/ratchets/test_module_alarm.py',),
    ),
    (
        'LATEST-DEPENDENCIES',
        'A third-party dependency moves to the LATEST, aggressively: a floor is a statement and an upper '
        'bound is a ceiling nobody re-argued. The environment a verdict was measured in is part of the '
        'verdict, so a package moving underneath one invalidates it rather than ageing it.',
        (
            'tests/architecture/repo/test_no_rust_dependency_carries_an_undeclared_upper_bound.py',
            'tests/architecture/declarations/test_one_python_version_source.py',
            'tests/unit/scripts/test_local_envkey.py',
        ),
    ),
    (
        'SHARED-CHECKOUT',
        'A box holds a SHARED, possibly concurrent checkout: there is NO single-agent mode, the remote IS '
        'the only shared medium, pushing is the obligation rather than the last step of landing, and a '
        'verdict cannot be delegated to someone who cannot see the code.',
        (
            'tests/architecture/repo/test_a_working_lane_is_visible_on_origin.py',
            'tests/architecture/repo/test_one_session_owns_one_pushable_branch.py',
            'tests/architecture/repo/test_a_fresh_worktree_is_importable.py',
        ),
    ),
    (
        'VERDICT-BAR-IS-THE-INCREMENT',
        'A verdict answers for the INCREMENT that produced it, not for the tree: a red the increment did '
        'not cause is inventory rather than a blocker. What refuses is INCONCLUSIVE, an unreadable verdict '
        'or no log -- those proved NOTHING, so there is no verdict to carry.',
        (
            'scripts/gate/prepush_gate.py',
            'tests/architecture/gate/test_prepush_gate_refuses_every_inconclusive_run.py',
            'tests/architecture/gate/test_the_message_check_judges_the_push_increment.py',
        ),
    ),
    (
        'REFUSAL-NAMES-THE-REMEDY',
        'Take the remedy a refusal NAMES. Bound every wait, because a budget is a ceiling on the WAIT -- '
        'split or parallelise, never raise it -- and kill a process TREE by its ROOT pid, since stopping a '
        'wrapper leaves its children running.',
        (
            'scripts/gate/runner.py',
            'tests/architecture/gate/test_every_repo_check_has_a_runner.py',
            'tests/architecture/gate/test_the_reaper_never_calls_an_unreadable_box_clean.py',
        ),
    ),
    (
        'NETWORK-RETRY-THEN-REPORT',
        'The forge is a REMOTE service: a network verb goes through the retry wrapper rather than being '
        'called directly, and a write that still fails is REPORTED with its diagnosis instead of hammered.',
        (
            'scripts/hooks/with-retry.sh',
            'tests/architecture/gate/test_git_network_calls_go_through_the_retry_wrapper.py',
        ),
    ),
    (
        'PRODUCTION-ENTRY-POINT',
        'Reproduce a behaviour through the PRODUCTION entry point, never an ad-hoc script handed out '
        'beside it; if a behaviour is not reachable from there, that is a gap to FIX. The boundary is the '
        'SUBJECT, not the tree the code happens to live in.',
        (
            'tests/architecture/layering/test_scripts_hold_no_domain_code.py',
            'tests/architecture/layering/_placement.py',
        ),
    ),
    (
        'NO-LAZY-IMPORT',
        'No lazy imports, except an unavoidable circular or heavy-optional one with its reason written '
        'down: an import graph a cost model reads must be exact, and a deferred import makes it a guess.',
        (('ruff', 'PLC0415'),),
    ),
    (
        'HOOKS-ARE-WIRED',
        'Shipping a hook without wiring it is the declaration-that-lies in tooling form: a declared hook '
        'absent from the directory the tool actually consults must FAIL LOUDLY rather than sit there '
        'reading as protection.',
        (
            'scripts/repo/check_hooks_installed.py',
            'tests/architecture/gate/test_the_declared_hooks_are_installed.py',
        ),
    ),
    (
        'AGENT-GUARD',
        'A hand-written test invocation, a bare network git verb and a stash are refused by the shared '
        'deny machinery rather than by prose, so the refusal is identical in every repo that adopts it.',
        (
            '.claude/hooks/deny-commands.js',
            '.claude/hooks/deny-rules.json',
            'tests/architecture/gate/test_agent_bash_guard.py',
        ),
    ),
    (
        'TOLERANCE-CARRIES-A-UNIT',
        'A relative tolerance is free and an absolute one is not: `epsilon = 1e-10 * L` is a statement '
        'about the unit its inputs are in, so the same call in metres tightens a test by 1000x. Sweep for '
        'absolute tolerances BEFORE a rewrite, state the unit a golden was generated in, and never write a '
        '`rel=` without the `abs=` floor it is combined with.',
        ('tests/architecture/ratchets/test_approx_rel_requires_abs.py',),
    ),
)
