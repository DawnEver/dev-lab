"""The rules registry, SECOND half -- pure DATA, the same row shape as ``_rule_rows.py``.

A second file because the first is pinned at its measured size (`tests/test_arch_module_size_alarm.py`)
and a registry that only grows cannot live in one module under a band that only falls.
It is a SIZE split, the one SPLIT-BY-CONCEPT names as debt (`tests/test_arch_modules_split_by_concept.py`);
a new row with a concept of its own goes to a module named for that concept (``_rule_rows_branches.py``).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'REPORTS-LIVE-IN-MEMORY',
        (
            'A report a person or agent WRITES -- an audit, analysis, design, plan, findings or workflow write-up '
            '-- is a dated memory entry under `.claude/memory/<yyyy>/<mm>/<dd>/` in the MEMORY-SHAPE, never a file '
            'under `output/`, which holds only what a program can regenerate (run logs, run records, '
            'measurements, charts, caches), and the agent guard refuses a Write/Edit or a shell redirect creating '
            'a Markdown file under any `output/`.'
        ),
        ('tests/test_dev_reportplace.py',),
    ),
    (
        'CODE-IN-CODE-ROOTS',
        (
            'Source code lives only under a root the repo DECLARES for code -- an allow-list walked over the '
            'filesystem rather than the index, so an untracked probe in an output or data directory is refused '
            'instead of accumulating there -- with a fix in the function that owns the behaviour and a one-off in '
            'scratch.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'SCRATCH-IS-NEVER-COMMITTED',
        (
            'Scratch is the one place an agent may leave a one-off, visible to git status but never committed '
            'beyond its README, and each one-off leaves by promotion into src with tests or by deletion, its '
            'finding recorded in memory as numbers, never by a move into scripts.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_scratch.py'),
    ),
    (
        'STRAY-FILE-REFUSED',
        (
            'An untracked, non-ignored file outside the declared stray roots (scratch, plus what the repo '
            'declares) is a defect found the moment it appears, not at review: a file somebody meant is staged, '
            'an artefact a program wrote goes to the dated output tree and the program is fixed to write there, '
            'a one-off goes to scratch, and the census runs after every shell command and at the end of a turn '
            'and refuses a commit while one exists.'
        ),
        ('tests/test_arch_code_placement.py', 'tests/test_dev_codeplace.py'),
    ),
    (
        'FORGE-THROUGH-THE-DOOR',
        (
            'Issue and pull-request reads and writes go through `python -m lab_commons.dev.forge` (`issue '
            'list|view|create|comment|close`, `pr create|view`, the token through `auth login|status`), never '
            '`gh`, `tea` or a raw API call, so every write the forge receives says which machine and which agent '
            'wrote it, and a write the door has no verb for is reported to the integrator, not routed around.'
        ),
        ('tests/test_dev_forgework.py', 'tests/test_dev_hooks.py', 'tests/test_dev_agenthooks.py'),
    ),
    (
        'VERDICT-AS-STATUS',
        (
            'A verdict reaches the forge as a commit STATUS on the exact commit it judged, in a named context, '
            'carrying the verdict line (PASS is success, FAIL is failure, INCONCLUSIVE publishes nothing, and a '
            'commit with no status at all is read UNCLAIMED, never INCONCLUSIVE), while a verdict about a dirty or '
            'moving tree names no commit and is not posted, and a failed publish never changes the verdict or its '
            'exit code.'
        ),
        ('tests/test_dev_forgestatus.py', 'tests/test_dev_verify.py'),
    ),
    (
        'ISSUE-IS-INTENT',
        (
            'An issue records INTENT only: its state (todo, in progress, ready, done) is DERIVED from the refs on '
            'origin and the gate status of a lane tip, never kept by hand in a label or a field, a claim is a '
            'stamped comment naming a branch, conflicting claims are reported for the human, and a chat message or '
            'an @-mention is a hint, never a trigger.'
        ),
        ('tests/test_dev_forgeissue.py',),
    ),
    (
        'WORKTREES-STAY-INSIDE',
        (
            'Every checkout of a repository -- a linked worktree, a moved one, a clone made for it -- lives under '
            '`<toplevel>/.claude/worktrees/<name>`, never beside or outside the repository, where it would be '
            'outside every scan, ignore rule and search the repository runs over itself.'
        ),
        ('tests/test_dev_worktreeplace.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'NO-REFLECTION',
        (
            'No tracked Python outside attic/ and archived/ calls getattr, hasattr, setattr or delattr, defines '
            '__getattr__, or routes the same probe through vars() or __dict__ -- a field is read by attribute '
            'access, a capability by isinstance against a Protocol, a dataclass by dataclasses.fields/replace, a '
            'name-keyed choice by an explicit dict -- and an irreducible boundary is a named allow-set entry '
            'carrying its reason.'
        ),
        ('tests/test_arch_production_carries_no_reflection.py',),
    ),
    (
        'PROJECT-FILES-HAVE-ONE-SOURCE',
        (
            'Every project-level file a repository tracks -- ignore and attribute files, the Makefile, hook and '
            'lint configuration, agent hook wiring, CI -- is, per one list, either rendered from a family base '
            'plus the repo`s declared delta or named as the repo`s own with the reason, and a file in neither, a '
            'hand edit to a rendered one, or a delta restating its base is refused.'
        ),
        ('tests/test_dev_famfiles.py', 'tests/test_dev_famconfig.py'),
    ),
    (
        'SPLIT-BY-CONCEPT',
        (
            'A module past the band is split along a CONCEPT, and the new module is named for it -- never into a '
            'sibling that only holds the overflow (`rows.py` + `rows_b.py`, `_2`, `_part2`, `_more`): a suffix '
            'that orders rather than names makes every reader learn which half holds what.'
        ),
        ('tests/test_arch_modules_split_by_concept.py',),
    ),
    (
        'AUTO-MODE-RUNS-THE-DOORS',
        (
            'In Claude Code and Codex auto mode the family`s checked doors run unprompted through one narrow allow '
            'row per door, rendered for both clients from one table; destructive LOCAL cleanup (merged branches, '
            'clean worktrees, an agent`s own gate run) goes through a door that re-checks its precondition; remote '
            'deletions are never automatic and stay with a human (pushes: MAIN-SESSION-PUBLISHES); and a worktree '
            'is removed, or its branch deleted, only when it is CLEAN (nothing modified, staged or untracked), '
            'its work committed or cleared by a human first, never moved aside by a door.'
        ),
        ('tests/test_dev_autodoors.py', 'tests/test_dev_branchset_apply.py', 'tests/test_dev_worktrees.py'),
    ),
    (
        'INJECTED-TEXT-IS-PROGRESSIVE',
        (
            'Text injected into an agent`s context -- a hook refusal, a door, a rule summary -- is the short '
            'essential within a declared budget, ending in a pointer to the doc that holds the reasoning and '
            'history, and before any injected text is shortened its full wording moves into that doc.'
        ),
        ('tests/test_dev_disclosure.py',),
    ),
    (
        'VERDICTS-FROM-THE-FORGE',
        (
            'A verdict is a fact about a sha, produced ONCE after the push by the forge serve host that claims its '
            '`tests/<part>` part and read from the forge, so nobody runs a full suite to push (admission reads '
            'forge parts and no pre-push hook runs a test), a full tier (verify naming no path, a runner`s gate or '
            'heavy) refuses to run outside the producer serve spawned and names the remedy -- push, then read the '
            'part -- and a developer`s targeted measure needs no claim and refuses fast rather than queue behind '
            'a run, a duplicate attaching to the run in flight and a judged key being cited.'
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
            'A main session publishes without waiting for a user decision -- it fast-forwards and pushes its trunk '
            'branches, in its own repo or a sibling, through narrow allow rows rendered as data (`git merge '
            '--ff-only`, and the push through the repo`s retry wrapper, a raw push only where it has none) -- '
            'while a force push and a remote-branch deletion stay refused by deny rows and a subagent is refused '
            'every push by SUBAGENT-NO-PUSH.'
        ),
        ('tests/test_dev_autodoors.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'SUBAGENT-NO-PUSH',
        (
            'A subagent never publishes (no push, no skipped hook): it commits on its lane and hands the SHA back '
            'to the main session, which merges and pushes, the forge produces the verdict '
            '(VERDICTS-FROM-THE-FORGE), and a targeted measure of the tests it touched stays its own.'
        ),
        ('tests/test_dev_hooks.py', 'tests/test_dev_agenthooks.py'),
    ),
    (
        'PR-REVIEW-IS-ADVISORY',
        (
            'The PR review is the repo-declared command (`[tool.lab_commons.review] command`), run by the forge -- '
            'which holds no model client, prompt or key -- inside its integration step on each open, non-draft PR '
            'into integration once per head sha under a diff-size cap, its stdout read as the versioned findings '
            'JSON with an unknown `schema_version` refused by name, and it posts a comment plus a `tests/review` '
            'status that is never a part, so no merge, promotion or push admission waits on it.'
        ),
        ('tests/test_dev_forgereview.py', 'tests/test_dev_forgeserve.py'),
    ),
    (
        'FORMATS-UPGRADE-ON-READ',
        (
            # Why the steps are DATA: a missing step is visible without running anything.
            'A persisted format a tool writes -- a run journal, a record, a state file, a ledger -- READS every '
            'older schema of itself by upgrading it, one step per schema declared as DATA beside the version, and '
            'writes it back at the current one, refusing only a schema the reader does not know (newer, or never '
            'issued), because a tool is redeployed under its own live data as a matter of course and refusing an '
            'older file stalls whatever reads it.'
        ),
        ('tests/test_arch_formats_upgrade_on_read.py',),
    ),
)
