"""The rules registry, THIRD part -- pure DATA, the same row shape as ``_rule_rows.py``.

The rows of the PR flow (who may open a PR, and onto what). A part of its own rather than a size split:
``_rule_rows_b.py`` sits at its band (`tests/test_arch_module_size_alarm.py`).
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'ONE-SESSION-ONE-PR',
        (
            'One agent session is one PR per repo. The LAUNCHER issues the session id (`LAB_SESSION`, the same for '
            'Claude, codex and every other provider, inherited by every child); the commit-msg hook writes it as a '
            '`Lab-Session:` trailer the agent never writes. A commit without the id (a human, or a path no launcher '
            'started) is never refused: it carries no trailer and is not judged. `Claude-Session:` is prose nothing '
            'reads. `forge pr create` and the pre-push of a NEW `pr/*` refuse a '
            'head sharing a session with another open head, naming the branch it is on. A split is only a declared, '
            'reasoned entry of `pradmit.SPLITS`, under a pinned ceiling that only falls; there is no switch.'
        ),
        ('tests/test_dev_labsession.py', 'tests/test_dev_pradmit.py', 'tests/test_dev_forgework.py'),
    ),
    (
        'NO-STACKED-PRS',
        (
            'Every PR is cut from and targets the integration branch: `forge pr create` refuses a head holding a '
            'commit of the head of another open PR that integration does not hold, so one stalled base never holds a '
            'dozen PRs behind it. The remedy is to wait for that PR to merge, or fold the work into it. The stack '
            'question has one owner, `trialmerge.shares_unmerged`.'
        ),
        ('tests/test_dev_pradmit.py',),
    ),
)
