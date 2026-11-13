"""The rules registry's BRANCH-FLOW rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about how a branch is created, published, synced, merged into integration and retired.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'ONE-BRANCH-PER-SESSION',
        (
            'Each working session maintains exactly ONE long-lived branch and merges its work into it, every other '
            'branch is merged and then deleted, never left behind, a repo`s long-lived branches are DECLARED (the '
            'trunk plus one branch per declared session or lane owner) so anything else on origin or on this box '
            'is debt, and unpushed work is reported, never deleted silently.'
        ),
        ('tests/test_dev_branchset.py',),
    ),
    (
        'MERGE-OR-DELETE',
        (
            'A merged branch is DELETED and an unmerged one is MERGED, no third state: an `archive/*` tag or '
            'untracked rename hides work and is debt like an undeclared branch -- `branchset` lists it, deletes it '
            'when a declared branch holds its tip, else names it to merge; a worktree is a lease for one task, so '
            'a tree unlocked, unoccupied, with no TRACKED change and its content landed on the trunk or a declared '
            'session is reclaimed by `branchset --apply` and the session debris hook, each kept tree listed with '
            'its reason: what git does not track goes with it, its run outputs moved home and verified first.'
        ),
        ('tests/test_dev_branchset_apply.py', 'tests/test_dev_reclaim.py'),
    ),
    (
        'RECURSIVE-DELETE',
        (
            'A recursive delete outside regenerable scratch (system temp, an `output/` tree) goes through its '
            'door -- `branchset --apply`, whose reclaim refuses a main checkout and keeps real work, for a '
            'worktree or branch, else the user -- and the agent guard refuses the raw verb in both shells '
            '(`rm -r`, `Remove-Item -Recurse`, `rmdir /s`, `git worktree remove`, `git clean -x/-d`, '
            '`shutil.rmtree`); earned 2026-10-27, when a hand-built list deleted a main checkout.'
        ),
        ('tests/test_dev_delete_row.py',),
    ),
    (
        'MERGE-DEVIATIONS-NAMED',
        (
            'A merge may not lose or rewrite a test in silence: every test whose body in the merge differs from '
            'what a clean three-way merge would hold (LOST, ALTERED, or CONFLICTED) is named in the merge commit '
            'with a one-line reason, the commit-msg hook refuses COMMITTING a merge with an unnamed one (checked '
            'once, on the one merge being committed; a push does no audit work), and the tests are the feature '
            'inventory, with no second list kept.'
        ),
        ('tests/test_dev_mergeaudit.py',),
    ),
    (
        'MERGE-RESOLUTION-DECLARED',
        (
            'A conflicted merge commit lists every conflicted file once as `<path>: <class> -- <why>`, the class '
            'one of newer-structure, simpler-side, one-source, deleted-as-baggage, renamed-to-reality, '
            'both-needed or kept-capability, each grounded in a principle, every principle placed '
            '(`mergeresolution.GROUNDS`), every class with its why; the conflicted set is recomputed '
            'from the parents` trees, never trusted from the message; the FORGE enforces it, refusing to merge a PR '
            'whose head adds a merge commit that leaves one undeclared or declares one the parents do not '
            'conflict on (remedy: redo that merge, a message cannot be amended), and the commit-msg '
            'hook makes the same judgement early on the merge being committed.'
        ),
        ('tests/test_dev_mergeresolution.py',),
    ),
    (
        'DOWNSTREAM-SYNCS-INTEGRATION',
        (
            'A child branch (a lane, a feat branch, a pull-request head) merges ONLY the integration branch, so '
            'another child`s work reaches it once, through integration, unless the owner opts in to watch named '
            'refs recorded in the checkout`s own git config (`branch.<child>.labSyncFrom`), never in a file, and '
            '`forge sync` merges integration first, then the watched refs, refusing any other ref by name.'
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
            'Every pull request targets the integration branch, one opened against the trunk is retargeted with a '
            'comment saying why, and each child branch carries ONE integration comment (or, without a PR, one '
            '`integration` commit status) updated in place by `forge integration`, never a new one per tick.'
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
            'A push to `refs/heads/<X>` of a declared session branch or the trunk carries exactly the local branch '
            '`<X>` (its local ref, with `HEAD` resolved, is `refs/heads/<X>`), so `HEAD:<X>` from another branch, '
            '`<Y>:<X>`, a bare sha and a detached HEAD are refused at pre-push, any checkout may publish it '
            'without having it checked out, every other local branch `<Y>` is published only as `<Y>`, and a '
            'bare sha or a detached HEAD lands on no branch but the forge`s own pushers` (`MACHINE_BRANCHES`).'
        ),
        ('tests/test_dev_sessionbranch.py',),
    ),
    (
        'PR-HEAD-IS-CURRENT',
        (
            'A push creating or updating a `pr/*` branch is refused at pre-push when its tip does not contain '
            '`origin/<integration>` fetched afresh (a fetch that fails refuses with its reason), or when its lock '
            'pins a floated sibling past the one lag window `lock/lag` reads (`locklag.within_window`); '
            '`forge pr ready` refuses on the same '
            'judgement and on uncommitted tracked changes. Each refusal names `forge sync`, which merges '
            'integration and relocks the floated siblings in one sync (user ruling 2026-11-07; `prcurrent`).'
        ),
        ('tests/test_dev_prcurrent.py', 'tests/test_dev_branchflow.py', 'tests/test_dev_forgedraft.py'),
    ),
    (
        'BASE-HOLDS-THE-MILESTONE',
        (
            'A push that creates or updates `refs/heads/<X>` is refused at pre-push unless its tip contains the '
            'newest milestone held locally: the highest `v<major>.<minor>.<patch>[.devN]` tag, a release above its '
            'dev tags, dev tags such as `v0.2.13.dev1` on the integration branch included and a legacy `-unverified` '
            'suffix read as its base (user ruling 2026-11-13: every agent iterates on a base holding the newest '
            'milestone); no version tag holds nothing, '
            'and the remedy is `python -m dev_lab.dev.forge sync`.'
        ),
        ('tests/test_dev_milestonebase.py',),
    ),
    (
        'VERSION-TAG-NEEDS-APPROVAL',
        (
            'A `v*` tag is added only on promotion to the trunk or at the user`s request: from an '
            'agent session, a push creating one on origin is refused at pre-push unless `DEV_LAB_TAG_APPROVED` '
            'holds the user`s own words (the `--approved` pattern of `branchset --discard`).'
        ),
        ('tests/test_dev_milestonebase.py',),
    ),
    (
        'NO-PUSH-ONTO-A-CLOSED-PR',
        (
            'A push that creates or updates `refs/heads/<X>` (the integration branch and the trunk aside) is refused '
            'at pre-push when the forge`s newest PR with head `<X>` into the integration branch was closed UNMERGED: '
            'no PR would ever carry the push. The refusal names the remedy (a new PR from `<X>`, or a new branch '
            'name), and a forge that cannot be read refuses, never passes unchecked. A merged PR`s branch passes: '
            'the forge continues it (LANDED-BRANCH-CONTINUES).'
        ),
        ('tests/test_dev_closedpush.py',),
    ),
    (
        'LANDED-BRANCH-CONTINUES',
        (
            'A merged PR is an immutable record of what was reviewed and tested at its head, never reused: a push '
            'onto its branch is carried by a CONTINUATION PR the forge opens from the same branch (Gitea: the serve '
            'tick; GitHub: the `continue.yml` push job), titled and bodied `continues #<N>`. Its review reads only '
            'the increment since the last landed head, its predecessors` findings are carried in ONE per-branch '
            'review record, and a carried finding neither resolved nor deferred with a reason holds `tests/review` '
            'at failure.'
        ),
        ('tests/test_dev_prcontinue.py', 'tests/test_dev_branchreview.py'),
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
            'passes (the same judgement the commit-msg hook makes), refused at pre-push, until `pr_merges_since` '
            'stands and INTEGRATION-TAKES-ONLY-FORGE-MERGES replaces this with the forge`s own merge.'
        ),
        ('tests/test_dev_sessionbranch.py', 'tests/test_dev_integrate.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'INTEGRATION-TAKES-ONLY-FORGE-MERGES',
        (
            'Where `[tool.dev_lab.integrator] pr_merges_since` is declared, the integration branch moves only '
            'by the forge merging a PR server-side once review and security stand, the head merges cleanly and '
            'the merge audit passes (`tests/<part>` parts gate only promotion to the trunk; a PR missing one '
            'stays open, its one integration comment naming what is missing). A client push adding a commit is '
            'refused at pre-push; the ONE bypass is a direct push whose EVERY new first-parent commit carries a '
            'non-empty `Break-Glass: <reason>` trailer (empty refused at commit-msg), each such commit past the '
            'declared start staying an open `integration` issue naming it and its reason until `pr_merges_since` '
            'moves past it.'
        ),
        ('tests/test_dev_sessionbranch.py', 'tests/test_dev_forgemerge.py', 'tests/test_dev_mergeaudit.py'),
    ),
    (
        'ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES',
        (
            'A push that creates or updates `refs/heads/<X>` on origin is refused at pre-push unless the branch '
            'set its pushed tip declares admits `<X>` (the trunk, a `sessions` branch, or a branch in an '
            '`ephemeral` namespace, default `pr/*`): a session publishes its one `pr/<feature>` branch and its '
            'fan-out `lane/` `feat/` `fix/` branches stay local. Deletions and tags are not judged, so an '
            'existing undeclared origin branch takes no new push and is deleted by a human.'
        ),
        ('tests/test_dev_sessionbranch.py',),
    ),
)
