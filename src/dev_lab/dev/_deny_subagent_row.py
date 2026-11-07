"""The SUBAGENT-NO-PUSH deny row -- pure DATA, scoped to subagents.

WHY A SCOPE AND NOT A NEW ENGINE. The hook payload carries ``agent_id`` only inside a subagent call
(fork included), so "who is asking" is a field the engine can read, and the rule is one row with
``scope: 'subagent'``. A main session -- even one launched with ``--agent``, which carries
``agent_type`` -- is never judged by it.

WHAT IT REFUSES: publishing is the main session's. So a subagent may not push (directly or through
the retry wrapper), run any door the policy table gives the main session alone (``actor == MAIN`` in
:data:`dev_lab.dev.agentpolicy.POLICY`: a PR's lifecycle, ``forge sync``, ``integrate promote``, ...),
and may not skip the hooks (``SKIP=``, PowerShell ``$env:SKIP =``, ``--no-verify``).
A full tier is not this row's: it refuses EVERYONE outside the forge's producer, at the runner
(VERDICTS-FROM-THE-FORGE, :func:`dev_lab.dev.producer.full_suite_refusal`). A targeted ``measure``
stays its own.

IT IS FIRST IN THE REGISTRY ON PURPOSE: the engine reports the first row that fires, and a subagent
asking to push should be told to hand back its SHA, not how to retry the push.
"""

from __future__ import annotations

import re

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS
from dev_lab.dev.agentpolicy import MAIN, module_verbs

_INTERPRETER = r'\S*python[\w.]*(?:\.exe)?\s+'


def _main_doors() -> str:
    """Every ``python -m`` door the policy table gives the MAIN session alone, as one alternation (derived)."""
    alternatives = []
    for module, verbs in module_verbs(MAIN).items():
        spelled = '|'.join(r'\s+'.join(re.escape(word) for word in verb) for verb in verbs if verb)
        alternatives.append(rf'{_INTERPRETER}-m\s+{re.escape(module)}\s+(?:{spelled})(?![\w-])')
    return '|'.join(alternatives)


SUBAGENT_NO_PUSH: dict[str, object] = {
    'id': 'SUBAGENT-NO-PUSH',
    'pattern': (
        r'(?:git(?:\.exe)?(?:\s+-C\s+\S+)*\s+push\b'
        r'|(?:sh\s+)?\S*with-retry\.sh\s+push\b'
        # The family retry verb is a push road too (MAIN-SESSION-PUBLISHES admits it for a main session).
        rf'|{_INTERPRETER}-m\s+dev_lab.dev\.netverb\b[^\n]*\spush\b'
        # Every door the policy table gives the main session alone (agentpolicy.MAIN): PRs, sync, promote, ...
        rf'|{_main_doors()}'
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
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.netverb -- git push origin HEAD',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr create --head pr/x --base integrate/main --title x',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr ready 12',
        f'{VENV_PYTHONS[1]} -m dev_lab.dev.forge sync',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.integrate promote abc123',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr breakglass 9 --reason x',
        'SKIP=ruff git commit -m "x"',
        'git commit --no-verify -m "x"',
        "$env:SKIP='ruff'; git commit -m 'x'",
        "$env:SKIP = 'ruff'",
    ),
    'permits': (
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py measure tests/test_x.py',
        'git commit -m "push the gate later"',
        'git log --oneline -5',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.netverb -- git fetch origin',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr view 12',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge queue',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr close-landedness 3',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge issue create --title x',
    ),
}
