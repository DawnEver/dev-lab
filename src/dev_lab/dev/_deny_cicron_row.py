"""The CI-CRON-NEEDS-CONSENT deny row -- pure DATA, derived from the user's ``hpcaccount`` doors in the policy table.

User ruling 2026-11-16: ``hpcaccount drift`` and ``drift-fleet`` are read-only (no file written, no crontab touched),
so every agent runs them; ``ci-pause``, ``ci-pause-fleet``, ``ci-resume`` and ``ci-resume-fleet`` rewrite a cluster
account's crontab, so an agent is refused them EVERY time. The refused verbs are the USER
doors whose ``deny`` is this row (:func:`refused_verbs`), never a second list. The doors the refusal names: the user
runs the verb, or approves a consent plan whose subject is the cluster and its account list and gives its code -- the
granted step then runs the verb with ``--credential <id>``, which this row ADMITS: the verb redeems the credential
against the subject it derives before any crontab change (:mod:`dev_lab.dev.hpcaccount.cicron`), so the grant check
in the verb, not this guard, is what enforces the consent. Codex keeps refusing the credential form (D15: a prefix
rule cannot see an argument), so it is not a ``permits`` near-miss, which every engine must admit; the Claude-side
admission is pinned in ``tests/test_dev_cicron_row.py``.
"""

from __future__ import annotations

import re
from typing import Final

from dev_lab.dev.agentpolicy import POLICY, USER

__all__ = ['CI_CRON_NEEDS_CONSENT', 'MODULE', 'RULE_ID', 'refused_verbs']

RULE_ID: Final = 'CI-CRON-NEEDS-CONSENT'
MODULE: Final = 'dev_lab.dev.hpcaccount'


def refused_verbs() -> tuple[str, ...]:
    """The ``hpcaccount`` verbs the policy table gives the USER alone under this row, longest first (regex order)."""
    verbs = {door.argv[3] for door in POLICY if door.deny == RULE_ID and door.actor == USER}
    return tuple(sorted(verbs, key=lambda verb: (-len(verb), verb)))


_VERBS = '|'.join(re.escape(verb) for verb in refused_verbs())

CI_CRON_NEEDS_CONSENT: dict[str, object] = {
    'id': RULE_ID,
    'pattern': rf'\S*python[\w.]*(?:\.exe)?\s+-m\s+{re.escape(MODULE)}\s+(?:{_VERBS})(?![\w-])'
    r'(?![^;&|\n]*\s--credential(?:[\s=]|$))',
    'matches': 'command',
    'hazard': "pausing or resuming CI rewrites a cluster account's crontab; an agent never does it on its own "
    '(user ruling 2026-11-16).',
    'remedy': 'Read first: python -m dev_lab.dev.hpcaccount drift-fleet. Then the user runs it, or approves a '
    'consent plan on the cluster plus its account list (python -m dev_lab.dev.consent grant), then runs it with '
    '--credential <id>.',
    'needs': None,
    'refuses': tuple(f'python -m {MODULE} {verb} --cluster c1' for verb in refused_verbs()),
    'permits': (
        f'python -m {MODULE} drift-fleet --cluster c1',
        f'python -m {MODULE} drift --from /srv/clone --host h',
        f'python -m {MODULE} --help',
        f'python -m {MODULE} ci-pause-fleetx',
        'git commit -m "ci-pause-fleet asks the user first"',
    ),
}
