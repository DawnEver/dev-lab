---
name: family-architecture-enforcement-needs-runtime-evidence
description: Read-only audit separates shared rule adoption, scan completeness, parser reach and blocking execution
metadata:
  type: research
---

# Family architecture enforcement needs runtime evidence

Stage: read-only research at fixed public default 87301811d8edc251c017fe0bd38411c2f671719d. No production change, test execution, installation, new limit or directory reorganization is qualified here. The research branch normally fast-forwarded to that source before recording this entry. Consumer-private observations are intentionally excluded from this public provider record.

## Conclusion

The public kit is not one automatic whole-repository architecture suite. Most reusable assertions require explicit consumer invocation and corpus facts. The shared registry proves structural adoption, not collection, semantic coverage or execution. A counted scan is not necessarily a complete scan; visible warnings and expected failures are not blocking constraints. These distinctions must remain explicit when reporting architecture health.

The complete registry below contains 81 public contracts: 72 declared enforced by the kit's own adoption mapping, eight explicitly absent here, and one automatic pytest rule. These are declaration readings, NOT 81 tested/accepted contracts. Every registry row and every family module was inventoried statically; this does not claim every algorithm or consumer has been proved correct.

Canonical public follow-up: DawnEver/dev-lab#599, "Enforce shared architecture contracts through actual collection, scope and blocking checks". This existing issue is the sole backlog for this investigation; no duplicate issue/todo is created.

## Current mechanism and concrete gaps

### Automatic collection is much narrower than the registry

`pyproject.toml:72-73` registers `dev_lab_family`. `src/dev_lab/pytest_family.py:23-25` defers to `famtests.alwayson.append_rows`. The checks table in `famtests/alwayson.py:95` contains only NO-CJK-IN-TRACKED-SOURCE. `famtests/__init__.py:20-33` explicitly describes all other bodies as consumer-parametrized assertions, not automatically collected tests. A shared implementation alone therefore does not establish adoption.

The CJK owner has real planted dirty/clean/orphan/nonrepo controls in `tests/test_famtests_alwayson.py`; its entry point is explicitly checked. However, `alwayson._toplevel:125` maps Git OSError/timeout to None and `append_rows:136-137` silently appends nothing when that value differs from the root. This conflates an intended checkout whose repository probe failed with a legitimate non-repository fixture. A future focused control must distinguish these cases before repair. Ordinary pytest can also disable autoload; no mandatory-plugin verification was found in the examined production door. Explicit disabling in planted fixtures is not evidence of an actual normal-run bypass.

### Registry declarations are not runtime certificates

`rules.unresolved:378-402` checks that a TestPath is tracked and a lint selector is enabled/not globally ignored. `assert_adopted:493-530` also accounts for unknown, absent and unadopted IDs. It does not prove that a named file contains a collected test, invokes its advertised assertion, scans the claimed population, avoids whole-function xfail/skip, or was part of an accepted run. A tracked helper is legal as part of an evidence tuple, so blindly requiring every named file to be a test would also be incorrect.

The adoption owner states this limitation itself in `tests/test_the_adoption_accounts_for_every_rule.py`. That honesty does not supply the missing runtime certificate. A correct extension should connect each contract to its actual collected blocking nodes while retaining helpers as dependencies, not pretend every path is a node. Exact-source execution receipts remain separate facts.

Absence reasons also need actual-subject evidence. The public `_ABSENT_REASONS` at `tests/test_the_adoption_accounts_for_every_rule.py:226-253` still says HOOKS-ARE-WIRED has "no declared hooks", while the same default `pyproject.toml:143,149,157,163,168` declares pre-commit/pre-push hooks and `test_dev_hook_install.py` supplies real planted installation controls. PRODUCTION-ENTRY-POINT still says "a library with no CLI", despite current public `python -m` command doors. These are stale-reason candidates, not permission to delete absence rows and claim mechanisms accepted. Conversely the AGENT-GUARD reason's lack of tracked PreToolUse wiring still matches the inspected tracked settings event map (empty); it must not be marked closed just because a reusable engine exists. The scalar absent ceiling of eight does not prove that each reason remains true.

### Corpus count does not prove corpus identity

`tests/_arch_corpus.py:66-73` has separate source and test enumerators. The local module-size guard (`tests/test_arch_module_size_alarm.py:48,105-107`) reads source_modules only; it is not a test-module size guard. Public default contains 546 source Python modules and 454 test Python modules, while `_arch_corpus:31-32` still has one-sided floors of 18. Those floors reject catastrophic collapse but cannot prove that a large omitted subtree was read. `_existing:62-63` silently removes missing tracked files.

A floor is still useful, but it is not set equality. Needed controls include a nonempty omitted subtree while both counts remain above the floor, equal-sized substituted path sets, a missing tracked member and an unreadable member. Where source-specific scope is intentional, retain it and name it honestly; do not indiscriminately impose production public-surface/dependency semantics on test fixtures.

There is no family directory-width/depth assertion in the current package. The kit's own tests root has 451 direct Python files. This is a concrete layout reading, not a breach of a hard family band that does not currently exist. Introducing a shared policy requires an explicit authored-module/file unit, generated/archive exceptions, semantic-grouping positive controls and a decision about warning versus blocking. Depth must not acquire an invented historical hard bar.

### Parser failures and aliases are inconsistent across bodies

`approxfloors.take_scan:186-215` receives a caller-supplied corpus and skips OSError/SyntaxError at :209. Its owner explicitly asserts an aliased approx call is invisible (`tests/test_famtests_approxfloors.py:96-99`). A declaration of that limitation is not enforcement of the semantic contract. The new intended controls must accept equivalent legal aliases and reject the actual unfloored call through them, while preserving both legitimate `ratio` and `unconditional` policies. An unrelated function with the same short name must remain a negative control.

`untimedwaits.untimed_waits` similarly skips OSError/SyntaxError and missing roots; `echoedtoken.echoed_tokens` skips OSError/SyntaxError. Function/site floors can remain satisfied while the omitted file contains the only violation. By contrast, countpins explicitly raises on unparseable files (`famtests/countpins.py:172-174` and `tests/test_famtests_countpins.py:183`), and direct hostnode/platformskips AST readers naturally surface parse errors. This is a concrete inconsistency to close, not a claim that every body currently fails open.

The all-file exception-boundary audit also found manifest parse/read omission in `upperbounds.py:148`, comment-only fallback after syntax failure in `_citedtests_readings.py:102`, and no Python fragments after syntax failure in `venvspelling.py:151`. These can hide a violating member while other members keep floors satisfied. They require exact per-file controls and explicit treatment of genuine fixture/data inputs, not a global suffix exemption. By contrast, `onboarding.py` converts malformed TOML into an explicit gap, and `latestversions.py`/`boundedremedy.py` return inside expected-refusal planted controls; those returns are not scanner fail-open findings. Return/continue syntax alone is not a verdict.

Do not solve parser coverage by rejecting aliases or legitimate language choices. Track expected/read/unread identities through the real scanner, fail closed on unread input, and plant syntax/read failures alongside enough clean files that a count floor alone would pass. No tolerance/count threshold needs weakening.

### Warnings, expected failure and language boundaries

Warning visibility is not blocking. A whole-test strict xfail only detects an unexpected pass; it does not prevent a new offender from joining historical failing residuals. A future qualification contract must plant a new offender beside legacy debt and require a real failure while preserving the exact named residual and existing bar. This research found no function-level xfail/skip decorators in the kit's `tests/test_arch_*.py` files by that bounded AST reading; module/class marks and all consumers require separate evidence.

Python AST scanners do not automatically constrain JS, Rust, TOML or shell files. Some public readers are deliberately format-specific: upperbounds covers declaration ecosystems, configuration readers exact artifacts, CJK tracked text, and reflection tracked Python. A universal statement must either name those boundaries or have real language-specific mechanisms; a broad rule name is not a multilingual analyzer. Data/export length must remain distinct from authored program complexity.

### Blocking parts and selected evidence

`jobparts.py:259-268` invokes actual pytest collection. `platformparts.py:495-505` maps failed parts to FAIL and incomplete/missing evidence to INCONCLUSIVE; these are genuine blocking decisions for the required population. GitHub policy explicitly removes non-hosted heavy parts (`jobparts.off_gate:290-292`, `ci_base.toml:45-48`), so that gate does not certify those omitted contracts. Base architecture checks should not acquire an unnecessary resource marker that silently changes their gate placement.

The native-session sixteen-owner replay genuinely passed 266 tests, including a built-wheel smoke, but did not select `test_arch_the_dev_inventory_lists_every_module.py`. The subsequent actual complete-owner Actions 43723900711 measured exact default 873: canonical FAIL, 1 failed / 5 passed in 4.21 seconds, environment e29a74da8f4dcf3a. The real diagnostic named BOTH jobmeasure and native_session as absent from the documented inventory; the earlier static suspicion named only the latter and is superseded by that receipt. Independent factual checkpoint 67dc1787e01ed54fe56f20904416bc82a503710a adds exactly those two bullets without changing original tests or runtime behavior; its follow-up replay remains NOT_RUN in this research. The 266 actual passes are not erased, and the omitted-owner failure must not be represented as full architecture acceptance.

## Recommendation and tradeoffs

1. Keep structural adoption, scan completeness and runtime qualification as different facts. Enhance the chain with actual collected blocking identities and exact-source receipts, without treating helper paths as executable nodes.
2. First plant empty helper, warning-only, expected-failure, uncollected and genuinely blocking contract cases through the actual door. This is narrower than inventing a universal source resolver.
3. Fix the concrete scanner reach problems with legal alias positives and syntax/read-failure negatives, preserving policies and bars. Count floors remain supplemental, never substitutes for the expected/read set relation.
4. Distinguish automatic-plugin nonrepo exemption from repository-probe failure. Preserve real pytester/nonrepo fixtures and the shared data owner.
5. Agree width/depth units and enforcement before any layout moves; reuse an existing narrow measurement where possible. No arbitrary flattening, new depth threshold, blanket exemption or whole-test xfail is a repair.
6. Run each affected complete owner and the actual blocking architecture population after composition. An AST inventory is a map for that work, not its PASS certificate.

Tradeoff: a runtime contract-to-node certificate adds explicit bookkeeping, but deriving nodes from actual collection keeps it bounded and prevents declaring file existence as execution. Exact corpus sets cost more than one count but catch partial unread trees the scalar cannot distinguish. The research does not propose a cross-language symbolic resolver or a universal new plugin for every repo-shaped policy.

## Complete public contract inventory

Each row below is read directly from the seven registry data owners and the kit's own adoption mapping. `declared enforced` means named mechanism data only. A lint mechanism is a selector, not a complete-source execution receipt. `declared absent` retains the exact public reason rather than assuming a missing local mechanism is implemented elsewhere and accepted.

| Contract ID | Public data owner | Kit declaration and named mechanisms |
|---|---|---|
| DECLARATION-LIES | _rule_rows.py | declared enforced: (guard('tests/test_arch_public_surface.py'), guard('tests/test_arch_rules_pages.py')) |
| PLANTED-CONTROL | _rule_rows.py | declared enforced: (guard('tests/test_arch_every_scan_binds_a_floor.py'),) |
| FLOOR-ON-EVERY-SCAN | _rule_rows.py | declared enforced: (guard('tests/test_arch_every_scan_binds_a_floor.py'), guard('tests/_arch_corpus.py')) |
| ESCAPE-HATCH-CEILING | _rule_rows.py | declared enforced: (guard('tests/test_arch_module_size_alarm.py'), guard('tests/test_the_adoption_accounts_for_every_rule.py')) |
| RATCHET-TWO-SIDES | _rule_rows.py | declared enforced: (guard('tests/test_arch_module_size_alarm.py'), guard('tests/test_arch_dependencies.py')) |
| NAMED-SETS-NOT-COUNTS | _rule_rows.py | declared enforced: (guard('tests/test_arch_module_size_alarm.py'), guard('tests/test_arch_skips_are_a_named_set.py'), guard('tests/test_the_adoption_accounts_for_every_rule.py')) |
| FIX-THE-CAUSE | _rule_rows.py | declared enforced: (guard('tests/test_arch_one_name_one_definition.py'),) |
| RETIRED-NAMES-REGISTERED | _rule_rows.py | declared enforced: (guard('tests/test_arch_retired_spellings.py'), guard('tests/_arch_corpus.py')) |
| REGISTRY-OWNS-THE-DECISION | _rule_rows.py | declared enforced: (guard('tests/test_arch_registry_data_is_separate.py'),) |
| IMPLEMENT-EVERYTHING | _rule_rows.py | declared absent: no combination matrix and no accuracy tag: the subject is absent |
| UNSUPPORTED-RAISES | _rule_rows.py | declared absent: no capability registry: there is no unsupported combination to refuse |
| XFAIL-NOT-SKIP | _rule_rows.py | declared enforced: (guard('tests/test_arch_skips_are_a_named_set.py'),) |
| BAR-IS-A-CONSTANT | _rule_rows.py | declared absent: no acceptance bar: this library produces no measurement to judge |
| DOCS-SPLIT | _rule_rows.py | declared enforced: (guard('tests/test_arch_rules_pages.py'),) |
| PUBLIC-SURFACE-DECLARED | _rule_rows.py | declared enforced: (guard('tests/test_arch_public_surface.py'),) |
| MODULE-SIZE-ALARM | _rule_rows.py | declared enforced: (guard('tests/test_arch_module_size_alarm.py'),) |
| LATEST-DEPENDENCIES | _rule_rows.py | declared enforced: (guard('tests/test_arch_dependencies.py'), guard('tests/test_dev_depversions.py'), guard('tests/test_famtests_latestversions.py')) |
| SHARED-CHECKOUT | _rule_rows.py | declared absent: the push obligation is a fact about origin, not about any file here |
| VERDICT-BAR-IS-THE-INCREMENT | _rule_rows.py | declared enforced: (guard('tests/test_dev_verdict.py'),) |
| REFUSAL-NAMES-THE-REMEDY | _rule_rows.py | declared enforced: (guard('tests/test_dev_bounded.py'),) |
| NETWORK-RETRY-THEN-REPORT | _rule_rows.py | declared enforced: (guard('tests/test_dev_netverb.py'), guard('tests/test_dev_dep_observe.py')) |
| PRODUCTION-ENTRY-POINT | _rule_rows.py | declared absent: a library with no CLI has no production entry point to reproduce through |
| NO-LAZY-IMPORT | _rule_rows.py | declared enforced: (lint('PLC0415'),) |
| HOOKS-ARE-WIRED | _rule_rows.py | declared absent: no declared hooks, so there is nothing whose absence could fail loudly -- and a wiring guard over a hook created in the same edit passes by construction rather than by holding |
| INSTALL-DOOR-DELIVERS-THE-DECLARATION | _rule_rows.py | declared enforced: (guard('tests/test_dev_installdoor.py'),) |
| AGENT-GUARD | _rule_rows.py | declared absent: HALF-CLOSED 2026-09-16, and the remaining half is NAMED rather than deferred. The rule says the refusal is IDENTICAL in every repo that adopts it, and the shared half of that now exists here: `dev_lab.dev.hooks` holds the universal rows and this repo supplies its own remedies, driven against this tree by tests/test_the_deny_adoption_ships_only_remedied_rules.py. What is still absent is the INSTALLATION -- no .claude/settings.json here points a PreToolUse matcher at an engine, so a bare test line typed in this repo is still not refused. Rendering the rules a repo may ship and WIRING them are two changes, and claiming the rule on the first would be the declaration that lies. The 2026-09-15 reason (that the rules had no subject here) is now false, and was replaced rather than left standing |
| TOLERANCE-CARRIES-A-UNIT | _rule_rows.py | declared enforced: (guard('tests/test_arch_every_approx_states_its_floor.py'),) |
| UNITS-GO-THROUGH-PINT | _rule_rows.py | declared enforced: (guard('tests/test_dev_units.py'), guard('tests/test_no_name_carries_a_unit.py')) |
| NO-CJK-IN-TRACKED-SOURCE | _rule_rows.py | automatic: famtests.alwayson (CJK only) |
| INJECTED-DOC-WIDTH-CEILING | _rule_rows.py | declared enforced: (guard('tests/test_dev_docwidth.py'),) |
| ENV-MUTATION-THROUGH-THE-DOOR | _rule_rows.py | declared enforced: (guard('tests/test_dev_dep.py'),) |
| ONE-BOX-ONE-LOCK | _rule_rows.py | declared absent: MOVED, not dropped: the box ledger (`lab_commons.box`) and its guards (`tests/test_box.py`, `tests/test_box_run_enforced.py`, `tests/test_liveness.py`) stayed in lab-commons, the runtime, at the 2026-10-22 split. dev-lab claims the box through verify and holds no ledger of its own to refuse. |
| MEMORY-SHAPE | _rule_rows_memory.py | declared enforced: (guard('tests/test_arch_memory_lives_in_a_dated_directory.py'), guard('tests/_arch_corpus.py'), guard('tests/test_dev_memoryadds.py')) |
| MONTHLY-PLANS-CARRIED | _rule_rows_memory.py | declared enforced: (guard('tests/test_famtests_monthsummary.py'),) |
| REPORTS-LIVE-IN-MEMORY | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_reportplace.py'),) |
| CODE-IN-CODE-ROOTS | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_codeplace.py')) |
| SCRATCH-IS-NEVER-COMMITTED | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_scratch.py')) |
| STRAY-FILE-REFUSED | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_codeplace.py')) |
| WRITES-STAY-IN-THE-TREE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_writeroots.py'), guard('tests/test_dev_tmpsweep.py')) |
| FORGE-THROUGH-THE-DOOR | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_forgework.py'), guard('tests/test_dev_hooks.py'), guard('tests/test_dev_agenthooks.py')) |
| VERDICT-AS-STATUS | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_forgestatus.py'), guard('tests/test_dev_verify.py')) |
| ISSUE-IS-INTENT | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_forgeissue.py'),) |
| WORKTREES-STAY-INSIDE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_worktreeplace.py'), guard('tests/test_dev_hooks.py')) |
| NO-REFLECTION | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_production_carries_no_reflection.py'),) |
| PROJECT-FILES-HAVE-ONE-SOURCE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_famfiles.py'), guard('tests/test_dev_famconfig.py')) |
| SPLIT-BY-CONCEPT | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_modules_split_by_concept.py'),) |
| AUTO-MODE-RUNS-THE-DOORS | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_autodoors.py'),) |
| INJECTED-TEXT-IS-PROGRESSIVE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_disclosure.py'),) |
| VERDICTS-FROM-THE-FORGE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_producer.py'), guard('tests/test_dev_verify.py'), guard('tests/test_dev_forgeserve.py'), guard('tests/test_dev_pushgate.py'), guard('tests/test_dev_inflight.py'), guard('tests/test_dev_runcache.py')) |
| MAIN-SESSION-PUBLISHES | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_autodoors.py'), guard('tests/test_dev_hooks.py')) |
| SUBAGENT-NO-PUSH | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_hooks.py'), guard('tests/test_dev_agenthooks.py')) |
| PR-REVIEW-IS-ONE-SHOT-ADVICE | _rule_rows_b.py | declared enforced: (guard('tests/test_dev_forgereview.py'),) |
| FORMATS-MIGRATE-ONCE | _rule_rows_b.py | declared enforced: (guard('tests/test_arch_formats_migrate_once.py'),) |
| ONE-BRANCH-PER-SESSION | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_branchset.py'),) |
| MERGE-OR-DELETE | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_branchset_apply.py'),) |
| RECURSIVE-DELETE | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_delete_row.py'),) |
| MERGE-DEVIATIONS-NAMED | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_mergeaudit.py'),) |
| MERGE-RESOLUTION-DECLARED | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_mergeresolution.py'),) |
| DOWNSTREAM-SYNCS-INTEGRATION | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_branchflow.py'),) |
| TRUNK-MOVES-BY-FAST-FORWARD | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_integrate.py'), guard('tests/test_dev_pushgate.py')) |
| PRS-TARGET-INTEGRATION | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_branchflow.py'),) |
| ONE-WRITER-PER-SESSION-BRANCH | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'),) |
| PUBLISH-IS-THE-LOCAL-REF | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'),) |
| PR-HEAD-IS-CURRENT | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_prcurrent.py'),) |
| BASE-HOLDS-THE-MILESTONE | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_milestonebase.py'),) |
| VERSION-TAG-NEEDS-APPROVAL | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_milestonebase.py'),) |
| NO-PUSH-ONTO-A-CLOSED-PR | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_closedpush.py'),) |
| LANDED-BRANCH-CONTINUES | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_prcontinue.py'), guard('tests/test_dev_branchreview.py')) |
| SESSION-HISTORY-ONLY-GROWS | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'),) |
| INTEGRATION-IS-MERGES-ONLY | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'), guard('tests/test_dev_integrate.py')) |
| INTEGRATION-TAKES-ONLY-FORGE-MERGES | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'), guard('tests/test_dev_forgemerge.py')) |
| ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES | _rule_rows_branches.py | declared enforced: (guard('tests/test_dev_sessionbranch.py'),) |
| TRACKED-CITES-NO-EPHEMERAL | _rule_rows_citations.py | declared enforced: (guard('tests/test_famtests_ephemeralrefs.py'),) |
| WALLS-ARE-RECORDED | _rule_rows_feedback.py | declared enforced: (guard('tests/test_dev_walls.py'), guard('tests/test_dev_hooks.py')) |
| ONE-SESSION-ONE-PR | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_labsession.py'), guard('tests/test_dev_pradmit.py')) |
| NO-STACKED-PRS | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_pradmit.py'),) |
| DRAFT-UNTIL-READY | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_forgedraft.py'),) |
| FORGE-DOORS-ARE-CONSENT | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_autodoors.py'), guard('tests/test_dev_hooks.py')) |
| DOCS-ONLY-CARRIES | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_forgecarry.py'), guard('tests/test_dev_forgetick.py')) |
| PUSHED-HEAD-IS-WATCHED | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_pushwatch.py'),) |
| SESSION-HEARS-ITS-PRS | _rule_rows_pr_flow.py | declared enforced: (guard('tests/test_dev_sessionwatch.py'),) |

## Family engine inventory

The following rows identify each public family-body module, its public readers/assertions and test files with direct static imports. Direct import is useful ownership evidence, not proof a particular branch ran. Private reading helpers are listed after this table. No consumer-private repository data is included.

| Public family body | Public entry points (not receipts) | Directly importing test files |
|---|---|---|
| agentguard | assert_node_is_available:100, decision_for:123, shipped_rules:143, reason_for:149, assert_the_guard_is_live:166, assert_committed_rules_are_rendered:183, assert_doors_name_live_rules:207, assert_every_rule_is_accounted_for:230, assert_the_shipped_set_is_pinned:247, assert_refused_by:266, assert_sanctioned:293 | tests/test_famtests_agentguard.py |
| allowguard | probe_command:126, allow_entries:141, contradictions:160, assert_no_allow_contradicts:234, assert_the_scan_can_still_see:271 | tests/test_famtests_allowguard.py |
| alwayson | cjk_pattern:46, exclude_pathspecs:51, candidates:67, check_no_cjk:81, rows:98, append_rows:130 | tests/test_famtests_alwayson.py |
| approxfloors | is_approx:123, approx_calls:151, unfloored:156, take_scan:186, assert_every_tolerance_states_its_floor:218, assert_the_scanner_still_convicts:270 | tests/test_famtests_approxfloors.py |
| boundedremedy | assert_the_wall_terminates_the_tree:121, assert_a_run_inside_the_wall_is_left_alone:195, assert_the_reaper_refuses_its_own_lineage:217, assert_the_reaper_kills_what_is_not_ours:239, assert_each_state_names_its_own_remedy:272, assert_the_pool_vars_are_the_named_set:335 | tests/test_famtests_boundedremedy.py |
| boxneeds | unmarked:212, assert_box_bodies_are_marked:226 | tests/test_famtests_boxneeds.py |
| branchset | assert_the_pr_flow_is_declared:40 | tests/test_famtests_branchset_prflow.py |
| citedtests | take_scan:122, assert_no_dangling_path_citation:189, assert_no_dangling_function_citation:217, assert_the_prose_half_is_reached:248, assert_every_exemption_is_real:269, assert_the_readers_still_convict:293 | tests/test_famtests_citedtests.py |
| configrender | assert_every_base_is_accounted_for:79, assert_artefact_is_rendered:97, assert_delta_is_not_a_fork:126, assert_no_rule_is_reopened:139, assert_modes_are_as_agreed:177, assert_no_base_line_left_undeclared:200, assert_render_round_trips:216, assert_every_section_is_owned:246 | tests/test_famtests_configrender.py; tests/test_famtests_own_repo_bodies.py; tests/test_the_kit_meets_its_own_makefile_contract.py; tests/test_the_kit_renders_its_own_gitignore.py |
| countpins | module_constants:102, count_pins:124, take_scan:162, assert_no_constant_is_a_count_pin:214, assert_the_grader_still_convicts:264 | tests/test_famtests_countpins.py |
| datedmemory | assert_trees_are_the_named_set:92, assert_every_entry_is_dated:113, assert_silent_entries_are_the_named_set:142, assert_dates_agree:166, assert_the_readers_still_convict:182 | tests/test_famtests_datedmemory.py |
| density | noun_pattern:87, code_only:123, code_and_delegation:134, nouns_in:205, measure_density:222, justified:273, meter_readings:292, assert_readings_convict:320, assert_the_meter_still_convicts:363 | tests/test_arch_module_size_alarm.py; tests/test_famtests_density.py |
| depdoor | no_other_process:122, scripted_keys:127, assert_this_repo_declares_its_verdict_anchors:138, assert_a_port_declaring_no_anchors_renders_the_gap:170, assert_the_door_refuses_while_a_verdict_is_in_flight:200, assert_a_verdict_in_another_environment_does_not_refuse:244, assert_a_moved_key_retires_a_planted_anchor:278, assert_an_unmoved_key_retires_nothing:320, assert_the_anchor_reader_has_a_floor_and_a_ceiling:361 | tests/test_famtests_depdoor.py |
| devdocs | shingles:69, copied_fraction:75, family_subjects:88, residue_problems:129, local_pages:156, assert_local_dev_pages_are_residues:164, assert_the_index_holds_the_live_table:194 | tests/test_famtests_devdocs.py; tests/test_famtests_own_repo_bodies.py; tests/test_the_dev_docs_tree_is_shared_by_reference.py |
| echoedtoken | echoed_tokens:203, take_scan:246, assert_no_clause_checks_its_own_echo:256, assert_the_scanner_still_convicts:287 | tests/test_famtests_echoedtoken.py |
| ephemeralrefs | assert_no_tracked_file_cites_ephemeral:23, assert_the_scanner_still_convicts:83 | tests/test_famtests_ephemeralrefs.py |
| famfiles | assert_every_project_file_is_accounted_for:41, assert_every_managed_file_is_rendered:66 | tests/test_dev_famfiles.py |
| hookinstall | assert_stages_are_declared:52, assert_declared_hooks_are_installed:67, assert_hooks_dir_is_the_one_git_consults:88, assert_the_guard_can_go_both_ways:119, assert_a_foreign_hook_is_not_installed:132 | tests/test_dev_hook_install.py; tests/test_the_declared_hooks_are_installed.py |
| hostnode | host_node_uses:94, assert_no_host_node:99, engine_leaks:134, assert_engine_is_dev_only:145 | tests/test_famtests_hostnode.py |
| injectedtext | assert_refusals_fit:29, assert_the_budget_still_convicts:50, row_fields:66, assert_rows_fit:74, assert_the_row_budgets_still_convict:99 | tests/test_dev_disclosure.py |
| injectedwidth | take_scan:95, assert_widths_are_the_named_set:117, assert_every_document_handed_in_was_read:170, assert_the_declaration_is_the_shape_the_ratchet_keys_on:217, assert_the_scanner_still_convicts:244 | tests/test_famtests_injectedwidth.py |
| latestversions | take_scan:137, assert_dependencies_are_latest:163, assert_the_reader_still_convicts:376 | tests/test_famtests_latestversions.py |
| localadmission | offenders_in:107, take_scan:124, assert_no_local_admission:138, assert_the_scanner_still_convicts:149 | tests/test_famtests_localadmission.py |
| lockpin | assert_the_lock_is_pinned:31 | tests/test_dev_lockcheck.py |
| monthsummary | plans:60, month_problems:87, assert_every_month_carries_its_plans:110, assert_the_reader_still_convicts:121 | tests/test_famtests_monthsummary.py |
| noreflection | reflection_sites:168, scanned_files:180, assert_no_reflection:185 | tests/test_arch_production_carries_no_reflection.py; tests/test_dev_codeplace.py |
| onboarding | assert_repo_is_onboarded:44, onboarding_gaps:62, assert_the_forge_takes_pull_requests:121 | tests/test_famtests_onboarding.py |
| placement | assert_ceiling_is_bounded:91, assert_minimum_is_bounded:129, placed_files:163, assert_every_file_is_placed:218, assert_no_stale_debt:267 | tests/test_famtests_placement.py |
| platformskips | platform_skips:68, assert_no_platform_skips:73 | tests/test_famtests_platformskips.py |
| principlespage | assert_principles_page_is_rendered:21 | tests/test_dev_principles.py |
| remedypaths | relative_interpreters:38, assert_remedies_name_absolute_interpreters:43, assert_a_planted_relative_remedy_is_convicted:56 | tests/test_famtests_remedypaths.py |
| restatedrules | restated:45, assert_no_restated_rules:52 | tests/test_famtests_restatedrules.py |
| reviewcommand | assert_the_review_declares_only_its_difference:20 | tests/test_famtests_reviewcommand.py |
| rostercensus | kit_directory:97, assert_reach:126, stale_moves:182, assert_no_stale_moves:201, named_only_paths:221, assert_waiver_is_the_named_set:226, assert_every_waived_row_adopted:259, assert_the_grader_still_convicts:286 | tests/test_famtests_rostercensus.py |
| rulespages | tracked_only:70, page_lines:86, ratchet_breaks:109, budget_overrun:133, assert_rules_ratchet:157 | tests/test_arch_rules_pages.py; tests/test_famtests_rulespages.py |
| sharedsettings | redefinitions_in:106, assert_no_package_redefines_a_shared_setting:113, assert_a_planted_redefinition_is_convicted:136 | tests/test_famtests_sharedsettings.py |
| sizesplits | size_splits:30, assert_no_new_size_splits:41 | tests/test_arch_modules_split_by_concept.py |
| storedreadings | assert_stored_readings_are_live:142, assert_history_is_dated:194, assert_the_reader_still_convicts:251 | tests/test_famtests_storedreadings.py |
| tempprefix | unowned_temp_calls:82, assert_every_temp_entry_carries_the_prefix:100, assert_the_scan_finds_a_planted_call:113 | tests/test_dev_writeroots.py |
| trackedcjk | take_scan:109, assert_no_undeclared_cjk:131, assert_the_declaration_is_the_shape_the_ratchet_keys_on:176, assert_the_exemptions_match_a_path_segment:206, assert_every_translation_has_its_source:238, assert_no_tracked_non_ascii:257, assert_the_scanner_still_convicts:276, assert_the_source_is_itself_clean:345 | tests/test_famtests_injectedwidth.py; tests/test_famtests_trackedcjk.py |
| untimedwaits | untimed_waits:116, take_scan:184, assert_every_wait_is_bounded:194, assert_every_exemption_is_real:222, assert_the_scanner_still_convicts:261 | tests/test_famtests_untimedwaits.py |
| upperbounds | take_scan:125, assert_no_undeclared_upper_bound:156, assert_the_reader_still_convicts:239 | tests/test_famtests_upperbounds.py |
| venvspelling | scannable_text:137, spellings_in:172, assert_only_the_resolver_spells_a_venv_interpreter:195, assert_the_resolver_is_still_consulted:236, assert_a_planted_recipe_is_convicted:270 | tests/test_famtests_venvspelling.py |
| visibility | commit:104, plant_checkout:111, assert_readable:136, assert_one_pushable_branch:172, assert_local_only_branches:192, assert_origin_branch_set:215, assert_the_remote_is_the_authority:230, assert_the_planted_debris_is_named:263 | tests/test_dev_autodoors.py; tests/test_dev_automode.py; tests/test_dev_branchset.py; tests/test_dev_branchset_apply.py; tests/test_dev_branchset_discard.py; tests/test_dev_reclaim.py; tests/test_dev_reclaimrun.py; tests/test_dev_worktree_archive.py; tests/test_dev_worktrees.py; tests/test_famtests_visibility.py |
| worktreeplace | assert_every_worktree_stays_inside:24 | tests/test_dev_worktreeplace.py |

Private/index source files also read: __init__.py, _boundedremedy_readings.py, _citedtests_readings.py, _configrender_readings.py, _datedmemory_readings.py, _placement_readings.py, _storedreadings_readings.py, _upperbounds_readings.py.

## Files checked and research boundaries

All seven `_rule_rows*.py` registry sources included by `rules.RULES`; `rules.py`; `pytest_family.py`; `pyproject.toml`; every Python file under `dev/famtests` including private reading helpers; the adoption owner; all `tests/test_arch_*.py` source; the explicit family owner files cited above; `_arch_corpus.py`; `jobparts.py`, `platformparts.py` and `ci_base.toml`. Relevant mechanisms were read as source/AST only. Full algorithmic correctness, every consumer's declarations, non-Python domain architecture and current live CI outcomes are not certified by this inventory.

The older ignored output narrative is a historical noncanonical artifact. Machine census/JSON/log evidence remains ignored; this dated project memory is the public narrative record. Follow-up work belongs in the existing issue backlog, not a second plan file. No new issue or external action has been taken by this investigation.
