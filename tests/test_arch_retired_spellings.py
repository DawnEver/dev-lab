"""RETIRED-NAMES-REGISTERED: a retired spelling is registered HERE, and the live tree never says it again.

THE REGISTRY IS :data:`RETIRED_SPELLINGS`, and this file is the one place a retired spelling may appear.
Each row names the REPLACEMENT and the decision that retired it, so a reader who meets the old word in a
dated memory entry can find what it became. Dated memory (``.claude/memory/``) is history and is never
rewritten, so it is outside the scan; everything else a person or agent reads -- source, tests, the
developer docs, the always-loaded rules -- is in it.

A retired spelling survives longest in PROSE: a docstring explaining the rename, an example in a page.
That is why the scan reads every tracked text file in those roots, not just identifiers.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Final

import pytest
from _arch_corpus import assert_floor, docs_pages, module_names, rel, rules_pages, source_modules, suite_modules

from dev_lab.dev import branchprune, pushwatch, sessionprs

#: dev-lab's own tables, moved from ``[tool.lab_commons]`` to ``[tool.dev_lab]`` (plan A3); ``schedule``,
#: ``tools``, ``hpc``, ``tests`` and ``artefacts`` stay, because lab-commons code reads them.
MOVED_TABLES: Final = (
    'areas', 'automode', 'branchset', 'carry', 'ci', 'components', 'dep', 'doors', 'ephemeral_refs', 'forge',
    'hooks', 'integrator', 'parts', 'placement', 'requests', 'review', 'stoprun', 'verify', 'worktrees',
)  # fmt: skip

#: Retired spelling -> (its replacement, the decision that retired it).
RETIRED_SPELLINGS: Final = {
    **dict.fromkeys(
        ('remhome', 'remconfig', 'only_manual_tasks_updated'),
        (
            (
                'dev_lab.dev.remretired (the leftovers refused, `migrate` per repo, `uninstall` per machine) and '
                'dev_lab.dev.memory (memory write and search); rem`s todo list is an entry like any other'
            ),
            'user rulings 2026-11-23: memory stays in each repo root; the rem plugin is archived and not installed',
        ),
    ),
    'forgeroute.reconcile': (
        'alarms on the host card (forge queue); the audit of a break-glass wave in the wave ledger',
        'user ruling 2026-11-19: issues never record events (break-glass, starved, integration rows)',
    ),
    **dict.fromkeys(
        ('prwatcher', 'SESSION-HEARS-ITS-PRS'),
        (
            'forgefeed and TASK-HEARS-ITS-FORGE-EVENTS: one notification-feed read per forge, routed to tasks',
            'D79 (user, 2026-11-18): the hearer is named for what it reads, and a task, not a session, subscribes',
        ),
    ),
    **dict.fromkeys(
        (
            'RETIRED_WIRING',
            'PUSHWATCH_COMMAND',
            'SESSIONPRS_COMMAND',
            'PUSHSTOP_COMMAND',
            'SWEEP_COMMAND',
            'PRESSURE_COMMAND',
            'STRAY_COMMAND',
            'HANDBACK_COMMAND',
            'JOURNALDOOR_COMMAND',
            'TASKBIND_COMMAND',
            'WALLSPOST_COMMAND',
            'WALLSSTOP_COMMAND',
            'RECLAIM_COMMAND',
            'REAPER_COMMAND',
            'VENVFOLLOW_COMMAND',
            'FORGEAUTH_COMMAND',
            'AUTOMODE_COMMAND',
            'SCRATCHSTOP_COMMAND',
            'SCRATCHSNAP_COMMAND',
            'DEVHOSTSTOP_COMMAND',
            'PRWATCHER_START_COMMAND',
            'PRWATCHER_INBOX_COMMAND',
        ),
        (
            'agent_wiring.WIRING rows run by dev_lab.dev.hookdispatch; settings carry dispatch_command(event)',
            'dev-lab #640 (W1): one dispatcher per hook event; the renderer owns every launcher row',
        ),
    ),
    'serve = false': (
        "the family layer's [roles.<forge>] binding (dev_lab.dev.roles); a host serves the repos bound to its grant",
        'user ruling 2026-11-16, re-placed by D73 2026-11-18: who performs each role is a fact of the family instance',
    ),
    **dict.fromkeys(
        ('dev_lab.dev.producers', 'producercheck', 'producer_from', 'producer_at', 'UndeclaredProducer'),
        (
            'dev_lab.dev.roles (roles_for, roles_at, Unbound) and dev_lab.dev.rolecheck',
            'toolchain D73 2026-11-18: the family layer binds each role to an executor kind; a repo declares none',
        ),
    ),
    **dict.fromkeys(
        ('ci_merges', 'CI_MERGER'),
        (
            "roles_at(root).kind('merge') == 'ci' (dev_lab.dev.roles)",
            'toolchain D73 2026-11-18: the merge.yml opt-in is the family binding merge = "ci"',
        ),
    ),
    'SERVED_KEY': (
        'ciworkflowshape.ROLE_KEY / BY_KEY: a job renders where the family binds its role to its kind (role_jobs)',
        'toolchain D73 2026-11-18: one render rule by role replaces the judge-only served mark',
    ),
    '[tool.dev_lab.protection] producer': (
        "the family layer's [roles.<forge>] (dev_lab.dev.roles.retired_placement refuses the key by name)",
        'toolchain D73 2026-11-18: a repo declares no placement, migrated once',
    ),
    **dict.fromkeys(
        (
            'forgereview_pointer',
            'actionsartifact',
            'trusted_bundle',
            'PREPARE_WORKFLOW',
            'review_runs',
            'RunsUnread',
            'run_pulls_listed',
            'forge review prepare',
            'BUNDLE_CONTEXT',
        ),
        (
            'reviewbundle.fetched + reviewbundle.prepare on the judge host (forgereview_bundle.fetch_from)',
            'toolchain D77 2026-11-18: the judge fetches each head and prepares its own bundle; no CI job or pointer',
        ),
    ),
    **dict.fromkeys(
        ('check-case-conflict', 'check-json', 'check-merge-conflict', 'check-toml'),
        (
            'the one `filechecks` hook row (`dev_lab.dev.filechecks all`; a check is skipped or narrowed by name)',
            (
                'toolchain H3 2026-11-16: ten per-check rows cost ten interpreters per commit (check-ast stays: it '
                'is pre-commit-hooks` own id, which the famconfig fixtures spell)'
            ),
        ),
    ),
    **dict.fromkeys(
        (
            'pushstop',
            'unwatched_refusal',
            'red_refusal',
            'stop_refusal',
            'record_deadline',
            'deadline_reached',
            'pushed_by',
            'pushed_at',
            'arm_line',
            'said_after',
            'watch_session_command',
            'post_push',
            'post-push',
        ),
        (
            'forgefeed, the one hearer of a task (D79); push doors print pushwatch.heard_line',
            'dev-lab #640 unwired the push journal, its Stop gate, the shell-line hooks and post-push; deleted after',
        ),
    ),
    **dict.fromkeys(
        ('stop_block', 'devhost-stop'),
        (
            'devhost session-start, a once-per-session SessionStart notice (agent_wiring.WIRING)',
            'one trigger per check (2026-11-16): machine-file drift cannot change within a turn; no Stop re-reads it',
        ),
    ),
    **dict.fromkeys(
        ('worktree_outputs', 'home_outputs', 'archive-outputs', 'outputs not moved home'),
        (
            (
                'a removed worktree is deleted with its output/ (reclaim, worktrees --remove); results of record '
                'live in the run store'
            ),
            'NO-BACKUP-COPIES (user 2026-11-23): moving a tree outputs into the main checkout was a backup',
        ),
    ),
    **dict.fromkeys(
        (
            'worktree_archive',
            'worktree-archive',
            'save_work',
            'current_archive',
            'archive_home',
            'archive_door',
            'ARCHIVE_TO',
        ),
        (
            (
                'dev_lab.dev.worktree_outputs (outputs home only); unlanded work is listed with its doors '
                '(reclaim.unlanded_work, UNLANDED_DOORS); worktrees --remove removes a clean tree'
            ),
            'D31 (user 2026-11-17, restating 2026-11-05): a worktree is merged or cleaned, never parked in output/',
        ),
    ),
    'steward': ('integrator', 'user decision 2026-10-20 (lab-commons PR #175): the role keeps its name'),
    'PR-REVIEW-IS-ADVISORY': (
        'PR-REVIEW-IS-ONE-SHOT-ADVICE',
        'user ruling 2026-10-26 (review redesign), then 2026-11-06: one review per PR, advice, only security blocks',
    ),
    'PR-REVIEW-BLOCKS-ON-HIGH-OR-SECURITY': (
        'PR-REVIEW-IS-ONE-SHOT-ADVICE',
        'user ruling 2026-11-06: the review is a one-shot independent acceptance with advice; only security blocks',
    ),
    **dict.fromkeys(
        ('lock/fresh', 'LOCK_CONTEXT', 'LOCK_REMEDY', 'lock_verdict'),
        (
            'lock/lag (dev_lab.dev.forgeheadgate), with lockcheck.unrendered folded into it',
            'user ruling 2026-11-14 (issue #575): one lock freshness fact on a PR head, never two',
        ),
    ),
    **dict.fromkeys(
        (
            'forgereview_rounds',
            'forgereview_judge',
            'forgereview_dispose',
            'AdjudicationRefused',
            'FAMILY_MAX_ROUNDS',
            'review dispose',
            'review adjudicate',
            'review-claims',
            'capped_waiver',
            'capped_line',
        ),
        (
            'forgereview_advice / forgereview_identity / reviewcap.unreviewed_waiver / forge review again',
            'user ruling 2026-11-06: one review per PR -- no rounds, no re-judging, no claims to adjudicate',
        ),
    ),
    **dict.fromkeys(
        ('split the PR', 'held over the cap', 'structure-level review'),
        (
            'review again after growth; Scope.unread lists what the budget left out',
            'user ruling 2026-11-06: a PR is never split for its review; one session, one task, one PR',
        ),
    ),
    **dict.fromkeys(
        ('review_blocks', 'review_hold'),
        (
            'reviewgate.review_missing',
            'user ruling 2026-10-31 (every PR must get a review): one predicate, nothing advisory',
        ),
    ),
    **dict.fromkeys(
        ('disposition_text', 'DisposeRefused', 'review-disposition'),
        (
            'nothing: findings are advice (user ruling 2026-11-06)',
            'user ruling 2026-10-31, retired with the claims 2026-11-06: a one-shot review disposes of nothing',
        ),
    ),
    **dict.fromkeys(
        ('secret-env', 'ANTHROPIC_API_KEY', 'login anthropic'),
        (
            '--keys-env AI_LAB_KEYS_<TASK> (dev_lab.dev.taskkeys)',
            'user-approved design 2026-11-05: a task carries ONE key bundle; dev-lab names no provider',
        ),
    ),
    **dict.fromkeys(
        ('NO-PUSH-ONTO-A-LANDED-PR', 'landedpush'),
        (
            'NO-PUSH-ONTO-A-CLOSED-PR (closedpush) and LANDED-BRANCH-CONTINUES (prcontinue)',
            "user-approved design 2026-11-07: a merged PR's branch is continued in a new PR; only a closed one refuses",
        ),
    ),
    'review capped, merge waits': (
        'forgereview_claim.UNREVIEWED_STATUS (not reviewed, merges unreviewed)',
        'user ruling 2026-11-05: a capped review no longer holds the merge; it merges WARNED',
    ),
    'OVER_CAP_TAKEOVER': ('Scope.unread', 'D123 2026-10-31, then 2026-11-06: an oversize head is sliced, never held'),
    **dict.fromkeys(
        ('breakglass enrol', 'wave_hours =', 'max_merges =', '--max-merges'),
        (
            'consent enrol; a breakglass.wave consent credential whose params are hours and max_merges',
            'user-approved design 2026-11-07: the wave TOTP check moved onto consent credentials; no code path stays',
        ),
    ),
    **{
        f'tool.lab_commons.{table}': (
            f'tool.dev_lab.{table}',
            'plan A3 2026-10-27: a table only dev-lab reads lives under [tool.dev_lab]; no fallback reads the old one',
        )
        for table in MOVED_TABLES
    },
    **dict.fromkeys(
        ('FORMATS-UPGRADE-ON-READ', 'test_arch_formats_upgrade_on_read'),
        (
            'FORMATS-MIGRATE-ONCE (tests/test_arch_formats_migrate_once.py)',
            'user ruling 2026-11-11 (consumer-a D51/D52): migrate stored records once, refuse the rest',
        ),
    ),
    **dict.fromkeys(
        (
            '_dep_pending',
            'when-free',
            'when_free',
            'update_waits',
            'TransientlyHeldError',
            'performPendingUpdate',
            'dev-lab-pending-bootstrap',
        ),
        (
            'dep --bootstrap publishes beside the live env (venvcurrent); a watch yields on venvpointer.superseded',
            'dev-lab #641 (epic #648): an environment is published beside the live one, so nothing queues or replays',
        ),
    ),
    **dict.fromkeys(
        ('taskbinding bind', 'taskbinding status', 'binding_gap', 'BIND_PROMPT'),
        (
            'the branch pr/<slug>/<feature> names the task (taskledger.task_of); python -m dev_lab.dev.task status',
            'H4 2026-11-16: a stale venv failed the binder and blocked every prompt; rem owns binding, the gate reads',
        ),
    ),
    **dict.fromkeys(
        ('servetask', 'servelanes', 'serve_lanes', 'serve_refusal', 'hpc_checkouts', 'RETIRED_SERVE_KEYS'),
        (
            (
                'nothing: a workstation deploy keeps its checkouts current and deletes the retired Task '
                '(dev_lab.dev.workstation.RETIRED_TASK); `workstation serve` is refused by name (RETIRED_VERBS)'
            ),
            "user ruling 2026-11-16: a workstation never serves a merge's parts; only Actions and the HPC produce",
        ),
    ),
    **dict.fromkeys(
        ('delete_tags', 'judge_tag', 'TAG_DOOR', '_held_by_tag'),
        (
            (
                'branchprune delete: a LOSSY branch is MERGED, or LANDED by a declared `git merge -s ours` PR and '
                'deleted; `delete-tag` and `delete --approved` are refused by name (branchprune.RETIRED)'
            ),
            'user ruling D22 2026-11-17: no tags -- either merge or delete (dev-lab O23)',
        ),
    ),
    **dict.fromkeys(
        ('codeplace stray', 'stray-check'),
        (
            'python -m dev_lab.dev.strays hook|check (the STRAY-FILE-REFUSED census is its own module)',
            'D40 2026-11-17: codeplace reached the 300-code-line band holding two rules; the stray rule split out',
        ),
    ),
    'load_division': (
        'dev_lab.dev.hpcaccount.division.division_of (the reached Machine is the one reader of the division)',
        'D40 2026-11-17: a second reader of a raw [hpc] table no production path builds',
    ),
    **dict.fromkeys(
        ('UncensusedSiteError', 'hook_table_from', 'declares_groups', 'overdue_declared', 'page_path'),
        (
            'nothing: no caller in dev-lab or any family repo',
            'D40 2026-11-17: dead public names removed (a never-raised error and four uncalled readers)',
        ),
    ),
    'Ref.of(': (
        'artefactstores.ref_of_entry (the Ref is lab_commons.compute.store.Ref; .key is .ref)',
        'L3 Ref half 2026-11-19: one Ref for artefacts and large objects; run_id_of / manifest_of are functions',
    ),
    'RETIRED_FILES': (
        "each checkout's own `retired` rows in [tool.dev_lab.placement], passed to strays.retired_copies",
        "2026-11-17: the leaf scan's remedy -- a consumer's tree path is that consumer's data, never the leaf's",
    ),
    '_adopt_plain_venv': (
        'dev_lab.dev.venvcurrent.publish sets a plain .venv aside; migrate removes .venv-current once',
        '2026-11-17: a held legacy .venv never drained; the follow retries the drain from the current environment',
    ),
    **dict.fromkeys(
        ('drift.STRAYS_IN_HOME', 'drift.STRAYS_IN_ROOT', 'old_copies'),
        (
            'dev_lab.dev.oldcopies (STRAYS_IN_HOME, STRAYS_IN_ROOT, left_behind): one list, reported and deleted',
            '2026-11-22, user ruling "deleting is the DEFAULT": the old copies became a retention rule',
        ),
    ),
    **dict.fromkeys(
        (
            'taskbinding',
            'session_binding',
            'bound_sessions',
            'take_task_pending',
            'bound_task_extras',
            'UnmigratedBindingError',
            'RETIRED_BINDINGS',
            'remplugin',
            'binder_door',
            'taskcarry',
        ),
        (
            (
                'dev_lab.dev.taskledger: ledger() (the global tasks repo) and task_of(cwd) (the task its branch '
                'pr/<slug>/<feature> names); forgefeed.take_task_unread; depneeds.task_extras'
            ),
            'user ruling 2026-11-23: the task ledger is one global repo and the binding store is cancelled',
        ),
    ),
    **dict.fromkeys(
        ('monthsummary', 'MONTHLY-PLANS-CARRIED', 'is_month_summary', 'MONTH_SUMMARY'),
        (
            'nothing: a plan lives in the task ledger (python -m dev_lab.dev.task) and dated memory entries',
            'user ruling 2026-11-24: the month summary files are retired entirely',
        ),
    ),
    'taskguard': (
        'dev_lab.dev.ledgerguard (LEDGER-WRITES-THROUGH-ITS-DOOR): one guard of the task files and ledger dir',
        '2026-11-24 fold: two guards of one ledger became one',
    ),
    'tick.RERENDER': (
        'dev_lab.dev.hpcaccount.grantslice.RERENDER, beside the grant refusal it completes',
        '2026-11-22: the grant slice owns its refusal and its remedy',
    ),
}

#: Floor on the files read, set under the 2026-10-25 measurement (several hundred): an unread tree is a
#: refusal, not a pass.
PROSE_FLOOR: Final = 100

_THIS: Final = Path(__file__).resolve()


def _pattern(spelling: str) -> re.Pattern[str]:
    return re.compile(rf'\b{re.escape(spelling)}', re.IGNORECASE)


def _hits(text: str) -> list[str]:
    return [old for old in RETIRED_SPELLINGS if _pattern(old).search(text)]


def _corpus() -> tuple[Path, ...]:
    files = (*source_modules(), *suite_modules(), *docs_pages(), *rules_pages())
    return tuple(path for path in files if path.resolve() != _THIS)


def test_no_live_file_spells_a_retired_name() -> None:
    corpus = _corpus()
    assert_floor(len(corpus), PROSE_FLOOR, 'retired-spelling')
    found = {
        f'{rel(path)}: {old} -> {RETIRED_SPELLINGS[old][0]}'
        for path in corpus
        for old in _hits(path.read_text(encoding='utf-8', errors='replace'))
    }
    assert not found, f'retired spellings in the live tree (name the replacement): {sorted(found)}'


def test_planted_retired_spelling_is_found() -> None:
    """PLANTED CONTROL: the matcher sees the old word in prose, any case, and not inside another word."""
    assert _hits('the Steward merges nothing') == ['steward']
    assert _hits('the integrator merges nothing') == []


def test_every_row_names_its_replacement_and_decision() -> None:
    blank = sorted(old for old, (new, why) in RETIRED_SPELLINGS.items() if not new.strip() or not why.strip())
    assert blank == []


def test_the_retired_push_entry_points_are_absent() -> None:
    """dev-lab #640 unwired them; deleted, no shim. Their spellings live only here, so their absence is pinned here.

    PLANTED CONTROL: the live neighbours of each stay -- the module that kept its parsing, the pre-push verb.
    """
    assert importlib.util.find_spec('dev_lab.dev.pushstop') is None
    assert importlib.util.find_spec('dev_lab.dev.pushwatch') is not None
    assert 'said_after' not in module_names(sessionprs)
    assert 'record_pushed' in module_names(sessionprs)
    assert {'arm_line', 'record_deadline', 'pushed_by', 'pushed_at'}.isdisjoint(module_names(pushwatch))
    assert 'post_push' not in module_names(branchprune)
    with pytest.raises(SystemExit) as refused:
        branchprune.main(['post-push'])
    assert refused.value.code == 2, 'argparse refuses the retired verb by name'
