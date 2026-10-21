"""The rules registry's BRANCH-FLOW rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about how a branch is created, published, synced, merged into integration and retired.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
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
            'it; none needs it checked out. Every other local branch `<Y>` is published only as `<Y>`.'
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
            'stands, INTEGRATION-TAKES-ONLY-FORGE-MERGES replaces this with the forge`s own merge.'
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
)
