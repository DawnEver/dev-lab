"""The rules registry, PR-FLOW part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows of the PR flow (who may open a PR, and onto what). A module named for its concept, not a size split.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'ONE-SESSION-ONE-PR',
        (
            'A development agent focused on one task (`LAB_SESSION`, stamped as a `Lab-Session:` trailer) gathers '
            'its work on one open PR per repo; `forge pr create` never refuses, it tells a second PR of the same '
            'session which open PR the work belongs on, on stderr and as an `Admission:` line in the PR body.'
        ),
        ('tests/test_dev_labsession.py', 'tests/test_dev_pradmit.py', 'tests/test_dev_forgework.py'),
    ),
    (
        'NO-STACKED-PRS',
        (
            'Every PR is cut from and targets integration: `forge pr create` tells a head holding another open '
            "PR's unmerged commits that it is stacked and lands only after that PR, and opens it anyway."
        ),
        ('tests/test_dev_pradmit.py',),
    ),
    (
        'DRAFT-UNTIL-READY',
        (
            'A PR is opened as a draft (`forge pr create`; `--ready` only for finished work) and its author marks it '
            'ready with `forge pr ready <N>` when its own work is done; only a ready PR is reviewed or merged, a draft '
            'runs nothing on either forge -- no part, review or merge-ready (user ruling 2026-11-05) -- and a '
            'push after ready keeps it ready (D53, user ruling 2026-11-01; `forgedraft`); `pr ready` is refused, '
            'naming the failed condition and with no override, unless the checkout is clean and the head is '
            'current (PR-HEAD-IS-CURRENT, user ruling 2026-11-07).'
        ),
        (
            'tests/test_dev_forgedraft.py',
            'tests/test_dev_forgework.py',
            'tests/test_dev_ciworkflows.py',
            'tests/test_dev_forgetick.py',
        ),
    ),
    (
        'FORGE-DOORS-ARE-CONSENT',
        (
            'The forge PR lifecycle verbs (`forge pr create|ready|draft|close-landed|close-superseded`) are checked '
            'doors rendered as allow rows from `agentpolicy.POLICY`; that policy IS the consent, so a main '
            'session runs them itself and never hands one to the user, and the forge refuses the bad case; '
            'every `forge pr` verb the docs tell an agent to run is a door, and a subagent opens or readies no PR '
            '(SUBAGENT-NO-PUSH).'
        ),
        ('tests/test_dev_autodoors.py', 'tests/test_dev_hooks.py'),
    ),
    (
        'DOCS-ONLY-CARRIES',
        (
            'A head whose diff from its nearest tested ancestor reaches no test footprint runs nothing: its parts and '
            'review are carried from that ancestor (`forgecarry.docs_only`); a data-only head (memory, docs) never '
            'cancels the run in flight, it waits and carries every outcome its diff cannot reach.'
        ),
        (
            'tests/test_dev_forgecarry.py',
            'tests/test_dev_forgetick.py',
            'tests/test_dev_forgerun.py',
            'tests/test_dev_forgereview.py',
        ),
    ),
    (
        'PUSHED-HEAD-IS-WATCHED',
        (
            'A pushed head is heard to its verdict, the same on both forges, by ONE hearer: the machine forge hearer '
            '(TASK-HEARS-ITS-FORGE-EVENTS). `forge pr create` and a successful push through the family door print one '
            'line naming the pushed head, that hearer and the idempotent `forgefeed start` door; no Monitor is '
            'armed and no hook journals the push (dev-lab #640). `forge watch <sha>... --stream` still reads a head '
            'on request: one line per status change, exiting on the first listed sha to settle, 0 green, 1 red, 3 '
            'at its deadline.'
        ),
        ('tests/test_dev_pushwatch.py',),
    ),
    (
        'TASK-HEARS-ITS-FORGE-EVENTS',
        (
            'A task hears what it subscribes to without the user relaying it (D79, D81): an issue or PR labelled '
            '`task:<slug>`, and every PR a session of the task opened or pushed. ONE machine hearer (`forgefeed`) '
            'reads each declared repository`s issues and PRs updated since a saved cursor ONCE per tick -- never a '
            'request per thread -- and routes each change to its task`s queue, which each session whose checkout is on '
            'a head of the task (`pr/<task>/<feature>`) reads once through its own cursor; open PRs` commit '
            'statuses are still read per PR. Each is said at the next prompt. '
            'Detail: docs-src/dev/forgefeed.md.'
        ),
        ('tests/test_dev_sessionwatch.py',),
    ),
    (
        'RED-INTEGRATION-MERGES',
        (
            # Why: user rulings 2026-11-06/11-12/11-17 (D18) -- integration may be red; only the trunk must be green.
            'Integration MAY be red and the trunk may not. The forge merges a PR once every hosted part it needs RAN '
            'and stands PASS (absent or pending waits, FAIL refuses; `forgemerge`); a red head merges only as a '
            'break-glass merge, whose test state and every failure subject its base does not carry go ON RECORD in '
            'its comment, audit line and wave summary (`ops.breakglass`, D18). `integrate promote` is the one '
            'gate to the trunk: a part not posted or not PASS refuses it, naming the break-glass door.'
        ),
        ('tests/test_dev_forgemerge.py', 'tests/test_ops_breakglass.py', 'tests/test_dev_integrate.py'),
    ),
)
