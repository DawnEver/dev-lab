"""The SUBAGENT-NO-PUSH deny row -- pure DATA, scoped to subagents.

WHY A SCOPE AND NOT A NEW ENGINE. The hook payload carries ``agent_id`` only inside a subagent call
(fork included), so "who is asking" is a field the engine can read, and the rule is one row with
``scope: 'subagent'``. A main session -- even one launched with ``--agent``, which carries
``agent_type`` -- is never judged by it.

WHAT IT REFUSES: publishing is the main session's. So a subagent may not push (directly or through
the retry wrapper), run any door the policy table gives the main session alone (``actor == MAIN`` in
:data:`dev_lab.dev.agentpolicy.POLICY`: a PR's lifecycle, ``integrate promote``, ...;
``forge sync`` is NOT one: it merges and commits locally and never pushes),
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
from dev_lab.dev.agentpolicy import MAIN, POLICY, module_verbs

_INTERPRETER = r'\S*python[\w.]*(?:\.exe)?\s+'


def _main_doors() -> str:
    """Every ``python -m`` door the policy table gives the MAIN session alone, as one alternation (derived)."""
    alternatives = []
    for module, verbs in module_verbs(MAIN).items():
        head = rf'{_INTERPRETER}-m\s+{re.escape(module)}'
        if () in verbs:  # a door that is the whole module: every verb of it is the main session's
            alternatives.append(rf'{head}(?![\w.-])')
            continue
        spelled = '|'.join(r'\s+'.join(re.escape(word) for word in verb) for verb in verbs)
        alternatives.append(rf'{head}\s+(?:{spelled})(?![\w-])')
    return '|'.join(alternatives)


def _main_client_doors() -> str:
    """Every forge-CLIENT (``gh``) door the policy table gives the MAIN session alone, as one alternation (derived).

    A ``git`` main door (``merge --ff-only``) stays a subagent's: on its own lane it publishes nothing.
    """
    doors = [door.argv for door in POLICY if door.actor == MAIN and door.argv[:1] == ('gh',)]
    return '|'.join(
        r'gh(?:\.exe)?\s+' + r'\s+'.join(re.escape(word) for word in argv[1:]) + r'(?![\w-])' for argv in doors
    )


SUBAGENT_NO_PUSH: dict[str, object] = {
    'id': 'SUBAGENT-NO-PUSH',
    'pattern': (
        r'(?:git(?:\.exe)?(?:\s+-C\s+\S+)*\s+push\b'
        r'|(?:sh\s+)?\S*with-retry\.sh\s+push\b'
        # The family retry verb is a push road too (MAIN-SESSION-PUBLISHES admits it for a main session).
        rf'|{_INTERPRETER}-m\s+dev_lab.dev\.netverb\b[^\n]*\spush\b'
        # Every door the policy table gives the main session alone (agentpolicy.MAIN): PRs, sync, promote, ...
        rf'|{_main_doors()}'
        rf'|{_main_client_doors()}'
        r'|git(?:\.exe)?\b[^\n]*\s--no-verify\b'
        # PowerShell spells the same skip as an environment assignment.
        r"""|SKIP=|\$env:SKIP\s*=)"""
    ),
    'matches': 'command',
    'scope': 'subagent',
    'hazard': 'publishing is the main session`s, and a skipped hook publishes what nobody checked.',
    'remedy': 'Commit on your lane and hand the commit SHA back to the main session, which merges and pushes; '
    'measure the tests you touched: {python} -m dev_lab.dev.verify -- <paths>.',
    'needs': None,
    'refuses': (
        'git push origin HEAD',
        'git -C .claude/worktrees/x push origin lane/x',
        'sh scripts/hooks/with-retry.sh push origin HEAD',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.netverb -- git push origin HEAD',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr create --head pr/x --base integrate/main --title x',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr ready 12',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.integrate promote abc123',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr breakglass 9 --reason x',
        'gh workflow disable ci.yml -R o/r',
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
        f'{VENV_PYTHONS[1]} -m dev_lab.dev.forge sync',
        f'{VENV_PYTHONS[1]} -m dev_lab.dev.forge sync --help',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge pr close-landedness 3',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge issue create --title x',
        'gh workflow list -R o/r',
    ),
}
