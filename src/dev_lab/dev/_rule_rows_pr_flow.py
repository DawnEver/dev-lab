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
            'ready with `forge pr ready <N>` when its own work is done; only a ready PR is reviewed or merged, and a '
            'push after ready keeps it ready (D53, user ruling 2026-11-01; `forgedraft`).'
        ),
        ('tests/test_dev_forgedraft.py', 'tests/test_dev_forgework.py'),
    ),
    (
        'FORGE-DOORS-ARE-CONSENT',
        (
            'The forge PR lifecycle verbs (`forge pr create|ready|draft|close-landed|close-superseded`) are checked '
            'doors rendered as allow rows from `autodoors.VERB_DOORS`; that policy IS the consent, so a main '
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
            'A pushed head is watched to its verdict and the session acts on it, the same on both forges: '
            '`forge watch <sha>... --stream` prints one line per status change and exits on the first listed sha '
            'to settle, 0 green, 1 red, 3 at its deadline, to run as a Monitor; `forge pr create` and a successful '
            'push through the family door print that exact command; a `PostToolUse` hook journals the push and '
            'adds one reminder line when its head has no live `forge watch`; and a `Stop` hook (ruling '
            '2026-11-04) refuses to end a turn while a journalled head is pending with no live watcher, naming '
            'the watch to arm, or red, naming where to read it (once).'
        ),
        ('tests/test_dev_pushwatch.py',),
    ),
)
