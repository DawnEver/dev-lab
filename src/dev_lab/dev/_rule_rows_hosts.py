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
        ('tests/test_hpc_scheduler_only_for_serving.py', 'tests/test_ops_configcheck.py'),
    ),
    (
        'SSH-HOST-KEY-DECLARED',
        (
            # Why: 2026-11-20, a new workstation's break-glass and consent doors died on a bare "Host key
            # verification failed" -- no host key was declared anywhere and the refusal named no door.
            "A declared ssh endpoint's host key is declared once (the family's [ssh.host_keys], from a trusted "
            'source, never a keyscan from the machine asking) and every door to it checks that key strictly. '
            'A missing or placeholder key refuses before ssh runs and a mismatch is named, each with the '
            'declaration and how to fill it.'
        ),
        ('tests/test_dev_remote_host_keys.py', 'tests/test_ops_configcheck.py'),
    ),
)
