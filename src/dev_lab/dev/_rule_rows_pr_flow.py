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
        'DOCS-ONLY-CARRIES',
        (
            'A head whose diff from its nearest tested ancestor reaches no test footprint runs nothing: its parts and '
            'review are carried from that ancestor (`forgecarry.docs_only`).'
        ),
        (
            'tests/test_dev_forgecarry.py',
            'tests/test_dev_forgetick.py',
            'tests/test_dev_forgerun.py',
            'tests/test_dev_forgereview.py',
        ),
    ),
)
