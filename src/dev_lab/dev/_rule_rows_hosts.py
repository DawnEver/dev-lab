"""The rules registry's HOST rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about what a deploy may place on a host, decided by the host's declared role.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'SCHEDULER-ONLY-FOR-SERVING',
        (
            # Why: user, 2026-11-20 -- "why would a research host need cron?"; a crontab call on a research deploy
            # refused it on a cluster that forbids crontab, though it wanted zero lines.
            'A scheduler (cron line, timer, scheduled task) exists only to tick a SERVING role queue. A role '
            'deploy steps are DERIVED from its role declaration (serves); a role that does not serve has no '
            'scheduler step, no tick and no serving gate of any kind, and nothing reads or writes its scheduler. '
            'Our marked lines left on such an account are dropped through the explicit door (`deploy --remove`).'
        ),
        ('tests/test_hpc_scheduler_only_for_serving.py',),
    ),
)
