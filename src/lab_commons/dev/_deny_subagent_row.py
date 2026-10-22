"""The SUBAGENT-NO-PUSH deny row -- pure DATA, scoped to subagents.

WHY A SCOPE AND NOT A NEW ENGINE. The hook payload carries ``agent_id`` only inside a subagent call
(fork included), so "who is asking" is a field the engine can read, and the rule is one row with
``scope: 'subagent'``. A main session -- even one launched with ``--agent``, which carries
``agent_type`` -- is never judged by it.

WHAT IT REFUSES: publishing is the main session's. So a subagent may not push (directly or through
the retry wrapper) and may not skip the hooks (``SKIP=``, PowerShell ``$env:SKIP =``, ``--no-verify``).
A full tier is not this row's: it refuses EVERYONE outside the forge's producer, at the runner
(VERDICTS-FROM-THE-FORGE, :func:`lab_commons.dev.producer.full_suite_refusal`). A targeted ``measure``
stays its own.

IT IS FIRST IN THE REGISTRY ON PURPOSE: the engine reports the first row that fires, and a subagent
asking to push should be told to hand back its SHA, not how to retry the push.
"""

from __future__ import annotations

from lab_commons.dev._deny_forge_rows import VENV_PYTHONS

_INTERPRETER = r'\S*python[\w.]*(?:\.exe)?\s+'

SUBAGENT_NO_PUSH: dict[str, object] = {
    'id': 'SUBAGENT-NO-PUSH',
    'pattern': (
        r'(?:git(?:\.exe)?(?:\s+-C\s+\S+)*\s+push\b'
        r'|(?:sh\s+)?\S*with-retry\.sh\s+push\b'
        # The family retry verb is a push road too (MAIN-SESSION-PUBLISHES admits it for a main session).
        rf'|{_INTERPRETER}-m\s+lab_commons\.dev\.netverb\b[^\n]*\spush\b'
        r'|git(?:\.exe)?\b[^\n]*\s--no-verify\b'
        # PowerShell spells the same skip as an environment assignment.
        r"""|SKIP=|\$env:SKIP\s*=)"""
    ),
    'matches': 'command',
    'scope': 'subagent',
    'hazard': 'publishing is the main session`s, and a skipped hook publishes what nobody checked.',
    'remedy': 'Commit on your lane and hand the commit SHA back to the main session, which merges and pushes; '
    'a targeted measure of the tests you touched is yours.',
    'needs': None,
    'refuses': (
        'git push origin HEAD',
        'git -C .claude/worktrees/x push origin lane/x',
        'sh scripts/hooks/with-retry.sh push origin HEAD',
        f'{VENV_PYTHONS[0]} -m lab_commons.dev.netverb -- git push origin HEAD',
        'SKIP=ruff git commit -m "x"',
        'git commit --no-verify -m "x"',
        "$env:SKIP='ruff'; git commit -m 'x'",
        "$env:SKIP = 'ruff'",
    ),
    'permits': (
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py measure tests/test_x.py',
        'git commit -m "push the gate later"',
        'git log --oneline -5',
        f'{VENV_PYTHONS[0]} -m lab_commons.dev.netverb -- git fetch origin',
    ),
}
