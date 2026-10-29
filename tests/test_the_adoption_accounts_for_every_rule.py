"""dev-lab ADOPTS the shared registry -- the repo that AUTHORS it, held to it.

WHY THIS FILE MATTERS MORE THAN IT LOOKS. The registry was authored here, so every mechanism it
first carried was a path in ANOTHER repo's tree, and the module promised that "a second adopter
inherits the statements and must supply the mechanism for its own tree" while offering no way to
supply one. Measured 2026-09-15: driven against its own tree, lab-commons refused its OWN registry
with 70 failures. `Adoption` is what closed that, and this file is the proof it works -- a real
checkout, with a real git-tracked mechanism list, none of it borrowed from the authoring rows.

THE SOURCE OF A RULE MAY NOT BE ITS WORST ADOPTER, which is what this file is for. When it was first
written it enforced ONE rule of 28 and declared 27 absent. Raised 2026-09-15 to 16 enforced and 12
absent, and again the same day to 18 and 10, by BUILDING the missing mechanisms in this tree
(`tests/test_arch_*.py`) rather than by re-describing the ones another repo has.

THE TWO SETS ARE BOTH PINNED BY NAME, and the pin is the ceiling. A rule added to the registry must
be typed into one of the two or `assert_adopted` reds -- so the absent set cannot grow by accident,
and `_ABSENT_CEILING` forces the hand that shrinks it to lower the number in the same edit.

WHAT THIS PROVES, STATED PRECISELY, because overclaiming it would be the defect it guards: every
rule is ACCOUNTED FOR -- enforced with each named mechanism TRACKED in this tree and, for a lint
mechanism, selected and not globally ignored -- or declared absent. It does NOT run those mechanisms
and cannot say they pass; that is the suite's business.

THE ABSENT RULES ARE ABSENT FOR A REASON, AND THE REASONS ARE NOT THE SAME KIND -- and the set is
NINE rather than the ten it was until 2026-09-21, because NETWORK-RETRY-THEN-REPORT was CLOSED that
day by the arrival of ``dev.dep_observe``, whose two transports are ``run_network_verb`` calls.
:data:`_ABSENT_CEILING` came down with it, which is the only direction it has ever moved. Three name
machinery this repo does not have (a gate runner, a hook directory, a production entry point) --
adoptable, and unbuilt. Three are about a SUBJECT this library does not have (an accuracy matrix, an
acceptance bar, a capability registry): a library with no solvers has
nothing to declare unsupported. One is a shape no file in this tree can reach: the push obligation
is a fact about origin. And one is CIRCULAR rather than merely unbuilt -- HOOKS-ARE-WIRED cannot be
closed by shipping a hook and a guard in the same edit, because the guard would then pass by
construction.

WHAT THE 2026-09-15 SECOND RAISE CLOSED, and how, because the CHEAP close was available for both and
was the wrong one. TOLERANCE-CARRIES-A-UNIT was declared VIOLATED here, not merely unenforced: seven
bare `pytest.approx` calls with no `abs=` floor, so a guard would have RED on the repo that authors
the rule. It would have been one edit to write the guard with those seven pinned as a waived set,
and that is a loosened band arriving through the pin. It was closed instead by seven real edits, a
floor per site chosen from the quantity it measures. MEMORY-SHAPE had no subject at all -- no
`.claude/memory/` existed -- and the cheap close there was a guard over an absent directory, which
passes while reading as protection; it was closed by writing a real first entry and giving the scan
a floor of ONE, so an empty tree refuses instead of passing.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.profile import RepoProfile
from dev_lab.dev.rules import RULES, Adoption, assert_adopted, guard, lint, unadopted, waived

_ROOT = Path(__file__).resolve().parents[1]

_PROFILE = RepoProfile(
    app_name='dev-lab',
    package='dev_lab',
    root=_ROOT,
    lint_config='pyproject.toml',
)

#: Rules this repo refuses a violation of TODAY, each with the mechanism in THIS tree that does the
#: refusing. A rule usually names more than one file, because the guard and the control that proves
#: it can still fail are different claims and either can rot alone.
_ENFORCED = {
    'REPORTS-LIVE-IN-MEMORY': (guard('tests/test_dev_reportplace.py'),),
    'CODE-IN-CODE-ROOTS': (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_codeplace.py')),
    'SCRATCH-IS-NEVER-COMMITTED': (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_scratch.py')),
    'STRAY-FILE-REFUSED': (guard('tests/test_arch_code_placement.py'), guard('tests/test_dev_codeplace.py')),
    'DECLARATION-LIES': (
        guard('tests/test_arch_public_surface.py'),
        guard('tests/test_arch_rules_pages.py'),
    ),
    'DOCS-SPLIT': (guard('tests/test_arch_rules_pages.py'),),
    'SPLIT-BY-CONCEPT': (guard('tests/test_arch_modules_split_by_concept.py'),),
    'ESCAPE-HATCH-CEILING': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_the_adoption_accounts_for_every_rule.py'),
    ),
    'ENV-MUTATION-THROUGH-THE-DOOR': (guard('tests/test_dev_dep.py'),),
    # ENFORCED rather than declared absent, and the distinction is worth the line. This repo declares
    # no floating requirement -- it IS the kit -- so the cheap reading is "no subject here". But the
    # guard does not merely sit in this tree: it READS this manifest and these door files, so the day
    # a bare `git+` requirement lands here the CI `uv sync` it already scans stops being inert and
    # reds. A rule whose subject can arrive without anyone noticing is the one to enforce before it does.
    'INSTALL-DOOR-DELIVERS-THE-DECLARATION': (guard('tests/test_dev_installdoor.py'),),
    'FIX-THE-CAUSE': (guard('tests/test_arch_one_name_one_definition.py'),),
    # The door stamps provenance (forgework), and the rows refusing every OTHER write client are
    # proved row by row and through the real engine. Installing that engine here is AGENT-GUARD's
    # open half, so this tree proves the refusal exists; a consumer with the guard wired runs it.
    'FORGE-THROUGH-THE-DOOR': (
        guard('tests/test_dev_forgework.py'),
        guard('tests/test_dev_hooks.py'),
        guard('tests/test_dev_agenthooks.py'),
    ),
    # The two coordination rules are enforced by the doors that implement them: the status door and
    # verify's publish for VERDICT-AS-STATUS, the derived-state door for ISSUE-IS-INTENT.
    'VERDICT-AS-STATUS': (guard('tests/test_dev_forgestatus.py'), guard('tests/test_dev_verify.py')),
    'ISSUE-IS-INTENT': (guard('tests/test_dev_forgeissue.py'),),
    # The branch flow is enforced by its doors (integrate / forge sync / forge integration), proved on real
    # repositories against both forge backends.
    'TRUNK-MOVES-BY-FAST-FORWARD': (guard('tests/test_dev_integrate.py'), guard('tests/test_dev_pushgate.py')),
    'ONE-WRITER-PER-SESSION-BRANCH': (guard('tests/test_dev_sessionbranch.py'),),
    'SESSION-HISTORY-ONLY-GROWS': (guard('tests/test_dev_sessionbranch.py'),),
    'INTEGRATION-IS-MERGES-ONLY': (guard('tests/test_dev_sessionbranch.py'), guard('tests/test_dev_integrate.py')),
    'PUBLISH-IS-THE-LOCAL-REF': (guard('tests/test_dev_sessionbranch.py'),),
    'ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES': (guard('tests/test_dev_sessionbranch.py'),),
    'INTEGRATION-TAKES-ONLY-FORGE-MERGES': (
        guard('tests/test_dev_sessionbranch.py'),
        guard('tests/test_dev_forgemerge.py'),
    ),
    'PRS-TARGET-INTEGRATION': (guard('tests/test_dev_branchflow.py'),),
    'PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY': (guard('tests/test_dev_forgereview.py'),),
    'DOWNSTREAM-SYNCS-INTEGRATION': (guard('tests/test_dev_branchflow.py'),),
    'FLOOR-ON-EVERY-SCAN': (
        guard('tests/test_arch_every_scan_binds_a_floor.py'),
        guard('tests/_arch_corpus.py'),
    ),
    # THE RESOLVED HALF, added 2026-09-21. The manifest arm above refuses a CEILING in the
    # declaration, which is the half a reading of the text can answer. This names the half the text
    # cannot: what a checkout actually RESOLVED, judged against the sources, plus the environment
    # that a verdict really ran in. MEASURED that day -- three repos, three frozen shas of this same
    # library, and nothing in any declaration that could have shown it.
    'LATEST-DEPENDENCIES': (
        guard('tests/test_arch_dependencies.py'),
        guard('tests/test_dev_depversions.py'),
        guard('tests/test_famtests_latestversions.py'),
    ),
    'MEMORY-SHAPE': (
        guard('tests/test_arch_memory_lives_in_a_dated_directory.py'),
        guard('tests/_arch_corpus.py'),
    ),
    'MODULE-SIZE-ALARM': (guard('tests/test_arch_module_size_alarm.py'),),
    'RETIRED-NAMES-REGISTERED': (guard('tests/test_arch_retired_spellings.py'), guard('tests/_arch_corpus.py')),
    'NAMED-SETS-NOT-COUNTS': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_arch_skips_are_a_named_set.py'),
        guard('tests/test_the_adoption_accounts_for_every_rule.py'),
    ),
    # CLOSED 2026-09-21, and the reason it carried was the thing that had to change rather than the
    # rule. It read "nothing here calls a network verb, so a retry wrapper would guard nothing", and
    # that was TRUE of this tree until `dev.dep_observe` gave the kit a refresher that does: both of
    # its transports are `run_network_verb` calls, and the arm below refuses a transport that reaches
    # for its source directly. A rule declared absent because its SUBJECT is absent stops being
    # absent the moment the subject lands -- and the reason is replaced rather than left standing.
    'NETWORK-RETRY-THEN-REPORT': (
        guard('tests/test_dev_netverb.py'),
        guard('tests/test_dev_dep_observe.py'),
    ),
    'INJECTED-DOC-WIDTH-CEILING': (guard('tests/test_dev_docwidth.py'),),
    'INJECTED-TEXT-IS-PROGRESSIVE': (guard('tests/test_dev_disclosure.py'),),
    'NO-CJK-IN-TRACKED-SOURCE': (guard('tests/test_dev_cjk.py'),),
    'NO-LAZY-IMPORT': (lint('PLC0415'),),
    'NO-REFLECTION': (guard('tests/test_arch_production_carries_no_reflection.py'),),
    'ONE-BRANCH-PER-SESSION': (guard('tests/test_dev_branchset.py'),),
    'MERGE-OR-DELETE': (guard('tests/test_dev_branchset_apply.py'),),
    'VERDICTS-FROM-THE-FORGE': (
        guard('tests/test_dev_producer.py'),
        guard('tests/test_dev_verify.py'),
        guard('tests/test_dev_forgeserve.py'),
        guard('tests/test_dev_pushgate.py'),
        guard('tests/test_dev_inflight.py'),
        guard('tests/test_dev_runcache.py'),
    ),
    'MERGE-DEVIATIONS-NAMED': (guard('tests/test_dev_mergeaudit.py'),),
    'MERGE-RESOLUTION-DECLARED': (guard('tests/test_dev_mergeresolution.py'),),
    'AUTO-MODE-RUNS-THE-DOORS': (guard('tests/test_dev_autodoors.py'),),
    'MAIN-SESSION-PUBLISHES': (guard('tests/test_dev_autodoors.py'), guard('tests/test_dev_hooks.py')),
    # Incident 2026-10-17 (Ada): a redeploy from journal schema 1 to 2 under 17 live schema-1 runs, refused
    # by the reader, stopped every serve tick of four accounts.
    'FORMATS-UPGRADE-ON-READ': (guard('tests/test_arch_formats_upgrade_on_read.py'),),
    # Incident 2026-10-21: 28 open consumer-a PRs, one session spread over several, one stalled base holding a dozen.
    'ONE-SESSION-ONE-PR': (guard('tests/test_dev_labsession.py'), guard('tests/test_dev_pradmit.py')),
    'NO-STACKED-PRS': (guard('tests/test_dev_pradmit.py'),),
    # Incident 2026-10-27: a hand-rolled Remove-Item -Recurse over a worktree list deleted a main checkout.
    'RECURSIVE-DELETE': (guard('tests/test_dev_delete_row.py'),),
    'DOCS-ONLY-CARRIES': (guard('tests/test_dev_forgecarry.py'), guard('tests/test_dev_forgetick.py')),
    # User ruling 2026-10-29 (D83): a pushed head nobody watches goes red unseen -- advised, never blocked.
    'PUSHED-HEAD-IS-WATCHED': (guard('tests/test_dev_pushwatch.py'),),
    'PLANTED-CONTROL': (guard('tests/test_arch_every_scan_binds_a_floor.py'),),
    'REFUSAL-NAMES-THE-REMEDY': (
        # The rule's OTHER two halves, added 2026-09-16 with `dev.bounded`: a wall that terminates
        # the process TREE rather than the direct child, and a refusal that must consult the WIDTH
        # before it may name a tier as the remedy. The box guard covers only the admission refusal.
        guard('tests/test_dev_bounded.py'),
    ),
    'PUBLIC-SURFACE-DECLARED': (guard('tests/test_arch_public_surface.py'),),
    'SUBAGENT-NO-PUSH': (guard('tests/test_dev_hooks.py'), guard('tests/test_dev_agenthooks.py')),
    'TOLERANCE-CARRIES-A-UNIT': (guard('tests/test_arch_every_approx_states_its_floor.py'),),
    'TRACKED-CITES-NO-EPHEMERAL': (guard('tests/test_famtests_ephemeralrefs.py'),),
    'MONTHLY-PLANS-CARRIED': (guard('tests/test_famtests_monthsummary.py'),),
    'RATCHET-TWO-SIDES': (
        guard('tests/test_arch_module_size_alarm.py'),
        guard('tests/test_arch_dependencies.py'),
    ),
    'REGISTRY-OWNS-THE-DECISION': (guard('tests/test_arch_registry_data_is_separate.py'),),
    'UNITS-GO-THROUGH-PINT': (
        guard('tests/test_dev_units.py'),
        guard('tests/test_no_name_carries_a_unit.py'),
    ),
    'VERDICT-BAR-IS-THE-INCREMENT': (guard('tests/test_dev_verdict.py'),),
    'XFAIL-NOT-SKIP': (guard('tests/test_arch_skips_are_a_named_set.py'),),
    # Prevention is the deny row (proved through the real engine); detection is the family body run
    # over this checkout's own `git worktree list`.
    'PROJECT-FILES-HAVE-ONE-SOURCE': (guard('tests/test_dev_famfiles.py'), guard('tests/test_dev_famconfig.py')),
    'WORKTREES-STAY-INSIDE': (guard('tests/test_dev_worktreeplace.py'), guard('tests/test_dev_hooks.py')),
}

#: Rules this repo does NOT yet refuse a violation of, BY NAME with the reason. A mapping rather than
#: a bare set: an exemption with no recorded reason is indistinguishable from a hole somebody widened
#: during a red suite, and a reason makes that repair a sentence somebody has to write.
_ABSENT_REASONS = {
    'ONE-BOX-ONE-LOCK': (
        'MOVED, not dropped: the box ledger (`lab_commons.box`) and its guards (`tests/test_box.py`, '
        '`tests/test_box_run_enforced.py`, `tests/test_liveness.py`) stayed in lab-commons, the runtime, at the '
        '2026-10-22 split. dev-lab claims the box through verify and holds no ledger of its own to refuse.'
    ),
    'AGENT-GUARD': (
        'HALF-CLOSED 2026-09-16, and the remaining half is NAMED rather than deferred. The rule says '
        'the refusal is IDENTICAL in every repo that adopts it, and the shared half of that now '
        'exists here: `dev_lab.dev.hooks` holds the universal rows and this repo supplies its '
        'own remedies, driven against this tree by '
        'tests/test_the_deny_adoption_ships_only_remedied_rules.py. What is still absent is the '
        'INSTALLATION -- no .claude/settings.json here points a PreToolUse matcher at an engine, so '
        'a bare test line typed in this repo is still not refused. Rendering the rules a repo may '
        'ship and WIRING them are two changes, and claiming the rule on the first would be the '
        'declaration that lies. The 2026-09-15 reason (that the rules had no subject here) is now '
        'false, and was replaced rather than left standing'
    ),
    'BAR-IS-A-CONSTANT': 'no acceptance bar: this library produces no measurement to judge',
    'HOOKS-ARE-WIRED': (
        'no declared hooks, so there is nothing whose absence could fail loudly -- and a wiring guard '
        'over a hook created in the same edit passes by construction rather than by holding'
    ),
    'IMPLEMENT-EVERYTHING': 'no combination matrix and no accuracy tag: the subject is absent',
    'PRODUCTION-ENTRY-POINT': 'a library with no CLI has no production entry point to reproduce through',
    'SHARED-CHECKOUT': 'the push obligation is a fact about origin, not about any file here',
    'UNSUPPORTED-RAISES': 'no capability registry: there is no unsupported combination to refuse',
}

_ABSENT = frozenset(_ABSENT_REASONS)

#: The ceiling on the absent set, MEASURED 2026-09-15 after the raise (it was 27) and lowered to 9
#: on 2026-09-16 when REFUSAL-NAMES-THE-REMEDY was CLOSED rather than re-described: the reason it
#: carried -- "no runner and no wait to bound" -- stopped being true the moment a bounded wait whose
#: refusal names its holder landed (today ``lab_commons.box``). It may only go DOWN: closing a gap
#: deletes a name above AND lowers this number, so the number cannot quietly track an absent set
#: that grew.
#:
#: LOWERED AGAIN TO 8, 2026-09-21, for NETWORK-RETRY-THEN-REPORT and by exactly the same mechanism:
#: its reason ("nothing here calls a network verb") was true of this tree until ``dev.dep_observe``
#: gave the kit a refresher that calls two, so the rule moved into ``_ENFORCED`` and the ceiling came
#: down in the same edit. The number has never gone up, and neither has the reason for it.
#: 8 -> 9 on 2026-10-22, and it is a MOVE rather than a widening: ONE-BOX-ONE-LOCK is enforced where the
#: box lives (lab-commons), and this repo, split out of it, has no box to enforce it over.
#: 9 -> 8 on 2026-10-25: RETIRED-NAMES-REGISTERED closed by its registry and scan
#: (``tests/test_arch_retired_spellings.py``), when the integrator rename came over from lab-commons.
_ABSENT_CEILING = 8


def _adoption() -> Adoption:
    return Adoption(app_name='dev-lab', mechanisms=_ENFORCED, declared_absent=_ABSENT)


def test_the_adoption_accounts_for_every_rule() -> None:
    """THE CHECK. Every rule is either enforced here with a live mechanism, or named as a gap."""
    assert_adopted(_PROFILE, _adoption())


def test_the_two_sets_account_for_the_registry_exactly() -> None:
    """A rule added to the registry must be typed into one of the sets, or this reds before the check."""
    accounted = set(_ENFORCED) | _ABSENT
    live = {rule.id for rule in RULES}
    assert accounted == live, (
        f'rules neither enforced nor declared absent here: {sorted(live - accounted)}; names that are '
        f'not rules: {sorted(accounted - live)}. A new universal rule is a decision this repo has to '
        f'make for itself, not a line that appears in a list it never read.'
    )


def test_the_absent_set_may_only_shrink() -> None:
    """The ceiling on the escape hatch: closing a gap lowers the number in the same edit."""
    assert len(_ABSENT) <= _ABSENT_CEILING, (
        f'{len(_ABSENT)} rules are declared absent, above the {_ABSENT_CEILING} ceiling. An escape hatch '
        f'needs a CEILING rather than a reason: a waiver that no one must justify is how a check reaches '
        f'zero without anything being fixed.'
    )


def test_every_gap_carries_its_reason() -> None:
    """A waiver with no reason recorded is a hole that reads as a decision."""
    silent = sorted(name for name, why in _ABSENT_REASONS.items() if not why.strip())
    assert silent == [], f'declared absent with no reason recorded: {silent}'


def test_the_gap_is_visible_rather_than_silent() -> None:
    """`waived` and `unadopted` are different facts, and this is the one that is on record."""
    adoption = _adoption()
    assert unadopted(RULES, adoption) == (), 'the check above would already red; keep the two in step'
    assert set(waived(RULES, adoption)) == _ABSENT
