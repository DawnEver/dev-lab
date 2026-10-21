"""The rules registry, SECOND half -- pure DATA, the same row shape as ``_rule_rows.py``.

A second file because the first is pinned at its measured size (`tests/test_arch_module_size_alarm.py`)
and a registry that only grows cannot live in one module under a band that only falls.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'REPORTS-LIVE-IN-MEMORY',
        (
            'A report a person or agent WRITES -- an audit, analysis, design, plan, findings or workflow '
            'write-up -- is a dated memory entry under `.claude/memory/<yyyy>/<mm>/<dd>/` in the MEMORY-SHAPE, '
            'never a file under `output/`, which holds only what a program can regenerate (run logs, run '
            'records, measurements, charts, caches). Refused at the agent guard: a Write/Edit or a shell '
            'redirect creating a Markdown file under any `output/`.'
        ),
        ('tests/test_dev_reportplace.py',),
    ),
    (
        'CODE-IN-CODE-ROOTS',
        (
            'Source code lives only under a root the repo DECLARES for code -- an allow-list, walked over the '
            'filesystem rather than the index, so an untracked probe in an output or data directory is refused '
            'instead of accumulating there. A fix belongs in the function that owns the behaviour; a one-off '
            'belongs in scratch.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'SCRATCH-ARCHIVED-OR-PROMOTED',
        (
            'A one-off script lives in scratch for a bounded time and then leaves it: PROMOTED into the function '
            'that owns its behaviour, with tests, or ARCHIVED as evidence beside the memory of the day it '
            'served, with the '
            'finding it produced recorded. A scratch file past its time is refused, never left to rot.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'FORGE-THROUGH-THE-DOOR',
        (
            'Issue and pull-request reads and writes go through `python -m lab_commons.dev.forge` -- '
            '`issue list|view|create|comment|close`, `pr create|view`, the token through `auth login|status` -- '
            'never `gh`, `tea` or a raw API call, so every write the forge receives says which machine and which '
            'agent wrote it. A write the door has no verb for is reported to the integrator, not routed around.'
        ),
        ('tests/test_dev_forgework.py', 'tests/test_dev_hooks.py', 'tests/test_dev_agenthooks.py'),
    ),
    (
        'VERDICT-AS-STATUS',
        (
            'A verdict reaches the forge as a commit STATUS on the exact commit it judged, in a named context, '
            'carrying the verdict line: PASS is success, FAIL is failure, and INCONCLUSIVE publishes nothing; '
            'a commit with no status at all is read UNCLAIMED, never INCONCLUSIVE. A '
            'verdict about a dirty or moving tree names no commit and is not posted, and a failed publish never '
            'changes the verdict or its exit code.'
        ),
        ('tests/test_dev_forgestatus.py', 'tests/test_dev_verify.py'),
    ),
    (
        'ISSUE-IS-INTENT',
        (
            'An issue records INTENT only. Its state -- todo, in progress, ready, done -- is DERIVED from the '
            'refs on origin and the gate status of a lane tip, never kept by hand in a label or a field. A claim '
            'is a stamped comment naming a branch; conflicting claims are reported for the human, and a chat '
            'message or an @-mention is a hint, never a trigger.'
        ),
        ('tests/test_dev_forgeissue.py',),
    ),
    (
        'WORKTREES-STAY-INSIDE',
        (
            'Every checkout of a repository -- a linked worktree, a moved one, a clone made for it -- lives '
            'under `<toplevel>/.claude/worktrees/<name>`, never beside or outside the repository. A tree '
            'outside is outside every scan, ignore rule and search the repository runs over itself.'
        ),
        ('tests/test_dev_worktreeplace.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'NO-REFLECTION',
        (
            'No tracked Python outside attic/ and archived/ calls getattr, hasattr, setattr or delattr, or '
            'defines __getattr__. A field is read by attribute access, a capability by isinstance against a '
            'Protocol, a dataclass by dataclasses.fields/replace, a name-keyed choice by an explicit dict; '
            'routing the probe through vars() or __dict__ is the same probe. An irreducible boundary is a '
            'named allow-set entry carrying its reason.'
        ),
        ('tests/test_arch_production_carries_no_reflection.py',),
    ),
    (
        'PROJECT-FILES-HAVE-ONE-SOURCE',
        (
            'Every project-level file a repository tracks -- ignore and attribute files, the Makefile, hook and '
            'lint configuration, agent hook wiring, CI -- is either rendered from a family base plus the repo`s '
            'declared delta, or named as the repo`s own with the reason. One list says which; a file in neither, '
            'a hand edit to a rendered one, or a delta restating its base is refused.'
        ),
        ('tests/test_dev_famfiles.py', 'tests/test_dev_famconfig.py'),
    ),
    (
        'ONE-BRANCH-PER-SESSION',
        (
            'Each working session maintains exactly ONE long-lived branch and merges its work into it; every '
            'other branch is merged and then deleted, never left behind. A repo`s long-lived branches are '
            'DECLARED -- the trunk plus one branch per declared session or lane owner -- and anything else on '
            'origin or on this box is debt. Unpushed work is reported, never deleted silently.'
        ),
        ('tests/test_dev_branchset.py',),
    ),
    (
        'MERGE-OR-DELETE',
        (
            'A branch that is merged is DELETED; a branch that is not merged is MERGED. There is no third '
            'state: parking work as an `archive/*` tag (or a renamed branch nobody tracks) hides it from '
            'everyone and is debt exactly like an undeclared branch -- `branchset` lists it, deletes it when '
            'its tip is held by a declared branch, and names it to merge otherwise.'
        ),
        ('tests/test_dev_branchset_apply.py',),
    ),
    (
        'MERGE-DEVIATIONS-NAMED',
        (
            'A merge may not lose or rewrite a test in silence. Every test whose body in the merge differs from '
            'what a clean three-way merge would hold -- LOST, ALTERED, or CONFLICTED -- is named in the merge '
            'commit with a one-line reason, and the commit-msg hook refuses COMMITTING a merge with an unnamed '
            'one -- checked once, on the one merge being committed; a push does no audit work. The tests are '
            'the feature inventory; no second list is kept.'
        ),
        ('tests/test_dev_mergeaudit.py',),
    ),
    (
        'AUTO-MODE-RUNS-THE-DOORS',
        (
            'In Claude Code and Codex auto mode the family`s checked doors run unprompted: one narrow allow row '
            'per door, rendered for both clients from one table. Destructive LOCAL cleanup -- merged branches, '
            'clean worktrees, an agent`s own gate run -- goes through a door that re-checks its precondition; '
            'remote deletions are never automatic and stay with a human (pushes: MAIN-SESSION-PUBLISHES). A '
            'worktree is removed, or its branch deleted, only when it is CLEAN (nothing modified, staged or '
            'untracked): work is committed or cleared by a human first, never moved aside by a door.'
        ),
        ('tests/test_dev_autodoors.py', 'tests/test_dev_branchset_apply.py', 'tests/test_dev_worktrees.py'),
    ),
    (
        'INJECTED-TEXT-IS-PROGRESSIVE',
        (
            'Text injected into an agent`s context -- a hook refusal, a door, a rule summary -- is the short '
            'essential within a declared budget, and ends in a pointer to the doc that holds the reasoning '
            'and history. Before any injected text is shortened, its full wording moves into that doc.'
        ),
        ('tests/test_dev_disclosure.py',),
    ),
    (
        'VERDICTS-FROM-THE-FORGE',
        (
            'A verdict is a fact about a sha, produced ONCE, after the push, by the forge serve host that claims '
            'its `tests/<part>` part, and read from the forge. Nobody runs a full suite to push: admission '
            'reads forge parts and no pre-push hook runs a test. A full tier (verify naming no path, a runner`s '
            'gate or heavy) refuses to run outside the producer serve spawned, naming the remedy: push, then read '
            'the part. A developer`s targeted measure needs no claim, and refuses fast rather than queue behind a '
            'run; a duplicate attaches to the run in flight and a judged key is cited.'
        ),
        (
            'tests/test_dev_producer.py',
            'tests/test_dev_verify.py',
            'tests/test_dev_forgeserve.py',
            'tests/test_dev_pushgate.py',
            'tests/test_dev_inflight.py',
            'tests/test_dev_runcache.py',
        ),
    ),
    (
        'MAIN-SESSION-PUBLISHES',
        (
            'A main session publishes without waiting for a user decision: it fast-forwards and pushes its trunk '
            'branches, in its own repo or a sibling, through narrow allow rows rendered as data -- `git merge '
            '--ff-only`, and the push through the repo`s retry wrapper (a raw push only where it has none). A '
            'force push and a remote-branch deletion stay refused by deny rows, and a subagent is refused every '
            'push by SUBAGENT-NO-PUSH.'
        ),
        ('tests/test_dev_autodoors.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'SUBAGENT-NO-PUSH',
        (
            'A subagent never publishes: no push, no skipped hook. It commits on its lane and hands the SHA '
            'back to the main session, which merges and pushes; the forge produces the verdict '
            '(VERDICTS-FROM-THE-FORGE). A targeted measure of the tests it touched stays its own.'
        ),
        ('tests/test_dev_hooks.py', 'tests/test_dev_agenthooks.py'),
    ),
    (
        'DOWNSTREAM-SYNCS-INTEGRATION',
        (
            'A child branch (a lane, a feat branch, a pull-request head) merges ONLY the integration branch; '
            'another child`s work reaches it once, through integration. The owner may opt in to watch named '
            'refs, recorded in the checkout`s own git config (`branch.<child>.labSyncFrom`), never in a file. '
            '`forge sync` merges integration first, then the watched refs, and refuses any other ref by name.'
        ),
        ('tests/test_dev_branchflow.py',),
    ),
    (
        'TRUNK-MOVES-BY-FAST-FORWARD',
        (
            'The trunk moves only by fast-forward to an integration commit whose every required '
            '`tests/<part>` part stands PASS at scope full, through `integrate promote`; it refuses with the '
            'missing parts named, and refuses a trunk that cannot fast-forward rather than merging into it.'
        ),
        ('tests/test_dev_integrate.py', 'tests/test_dev_pushgate.py'),
    ),
    (
        'PRS-TARGET-INTEGRATION',
        (
            'Every pull request targets the integration branch; one opened against the trunk is retargeted '
            'with a comment saying why. Each child branch carries ONE integration comment (or, without a PR, '
            'one `integration` commit status) updated in place by `forge integration`, never a new one per tick.'
        ),
        ('tests/test_dev_branchflow.py',),
    ),
    (
        'ONE-WRITER-PER-SESSION-BRANCH',
        (
            'Every declared session branch (the integration branch included) has one writer at a time, and that '
            'is git`s own, never a host, directory or lease of ours: locally a branch is checked out in at most '
            'one worktree, so the sessions of one host and repo never share one; remotely a plain push is '
            'compare-and-swap, so a writer on a stale tip is refused as a non-fast-forward and must merge first, '
            'and SESSION-HISTORY-ONLY-GROWS refuses the force that would bypass it.'
        ),
        ('tests/test_dev_sessionbranch.py',),
    ),
    (
        'PUBLISH-IS-THE-LOCAL-REF',
        (
            'A push to `refs/heads/<X>` of a declared session branch or the trunk carries exactly the local '
            'branch `<X>`: its local ref, with `HEAD` resolved, is `refs/heads/<X>`. `HEAD:<X>` from another '
            'branch, `<Y>:<X>`, a bare sha and a detached HEAD are refused at pre-push. Any checkout may publish '
            'it; none needs it checked out. Every other local branch `<Y>` is published only as `<Y>`: `<Y>:<Z>` and a '
            'bare push to the upstream git auto-tracked are refused; a detached machine push names no branch.'
        ),
        ('tests/test_dev_sessionbranch.py',),
    ),
    (
        'SESSION-HISTORY-ONLY-GROWS',
        (
            'A push to a declared session branch or the trunk is refused at pre-push unless origin`s tip is an '
            'ancestor of the pushed one: a forced non-fast-forward and a deletion never land.'
        ),
        ('tests/test_dev_sessionbranch.py',),
    ),
    (
        'INTEGRATION-IS-MERGES-ONLY',
        (
            'Every new first-parent commit of the integration branch, from the declared `merges_only_since` '
            'forward, is a two-parent merge naming its branch in a `Merged-Branch:` trailer whose merge audit '
            'passes -- the same judgement the commit-msg hook makes. Refused at pre-push; once `pr_merges_since` '
            'stands, INTEGRATION-TAKES-ONLY-FORGE-MERGES replaces this with the forge`s own merge. A rebase '
            'never lands: it needs a force push, which the PUSH-FORCE deny row refuses.'
        ),
        ('tests/test_dev_sessionbranch.py', 'tests/test_dev_integrate.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'INTEGRATION-TAKES-ONLY-FORGE-MERGES',
        (
            'Where `[tool.lab_commons.integrator] pr_merges_since` is declared, the integration branch moves only '
            'by the forge merging a pull request server-side -- a merge commit, made once every `tests/<part>` '
            'part of its head stands PASS, the head merges cleanly, and the merge audit passes -- and a client '
            'push adding any commit to it is refused at pre-push. A PR still missing a condition stays open and '
            'its one integration comment names what is missing. The ONE bypass is in history: a direct push is '
            'admitted only when EVERY new first-parent commit carries a non-empty `Break-Glass: <reason>` trailer '
            '(an empty reason is refused at commit-msg), and every such commit past the declared start stays an '
            'open `integration` issue naming it and its reason until `pr_merges_since` moves past it.'
        ),
        ('tests/test_dev_sessionbranch.py', 'tests/test_dev_forgemerge.py', 'tests/test_dev_mergeaudit.py'),
    ),
    (
        'PR-REVIEW-IS-ADVISORY',
        (
            'The PR review is the repo-declared command (`[tool.lab_commons.review] command`), run by the forge '
            'inside its integration step on each open, non-draft PR into integration once per head sha, under a '
            'diff-size cap; its stdout is read as the versioned findings JSON and an unknown `schema_version` is '
            'refused by name. The forge holds no model client, prompt or key. It posts a comment plus a '
            '`tests/review` status that is never a part: no merge, promotion or push admission waits on it.'
        ),
        ('tests/test_dev_forgereview.py', 'tests/test_dev_forgeserve.py'),
    ),
    (
        'FORMATS-UPGRADE-ON-READ',
        (
            'A persisted format a tool writes -- a run journal, a record, a state file, a ledger -- READS every '
            'older schema of itself by upgrading it, one declared step per schema, and writes it back at the '
            'current one. Refusal is only for a schema the reader does not know: newer, or never issued. A tool '
            'is redeployed under its own live data as a matter of course, so refusing an older file refuses the '
            'ordinary case and stalls whatever reads it. The steps are declared as DATA beside the version, so '
            'a missing step is visible without running anything.'
        ),
        ('tests/test_arch_formats_upgrade_on_read.py',),
    ),
)
