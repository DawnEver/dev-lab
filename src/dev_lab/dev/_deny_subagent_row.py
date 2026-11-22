"""The SUBAGENT-NO-PUSH and MAIN-ONLY-DOOR deny rows -- pure DATA, scoped to subagents.

WHY A SCOPE AND NOT A NEW ENGINE. The hook payload carries ``agent_id`` only inside a subagent call
(fork included), so "who is asking" is a field the engine can read, and the rule is one row with
``scope: 'subagent'``. A main session -- even one launched with ``--agent``, which carries
``agent_type`` -- is never judged by it.

WHAT SUBAGENT-NO-PUSH REFUSES: publishing is the main session's. So a subagent may not push (directly or
through the retry wrapper), run a PUBLISHING door the policy table gives the main session alone
(``actor == MAIN`` in :data:`dev_lab.dev.agentpolicy.POLICY`, in :data:`PUBLISHING_MODULES`: a PR's lifecycle,
``integrate promote``, ...; ``forge sync`` is NOT one: it merges and commits locally and never pushes),
and may not skip the hooks (``SKIP=``, PowerShell ``$env:SKIP =``, ``--no-verify``).
A full tier is not this row's: it refuses EVERYONE outside the forge's producer, at the runner
(VERDICTS-FROM-THE-FORGE, :func:`dev_lab.dev.producer.full_suite_refusal`). A targeted ``measure``
stays its own.

WHAT MAIN-ONLY-DOOR REFUSES: every OTHER main-only door (a held login session, a fleet deploy, a consent
grant, ...), which publishes nothing. Until 2026-11-22 the push row refused those too, so ``hpcaccount
deploy-fleet --dry-run`` was answered "commit on your lane and hand the SHA back" -- the remedy of a push nobody
asked for. A refusal names its real cause, so two subjects are two rows; and a verb that only READS
(:data:`READ_ONLY_FLAGS`, and every ``actor == SUBAGENT`` door, which neither pattern derives from) is refused
by neither.

IT IS FIRST IN THE REGISTRY ON PURPOSE: the engine reports the first row that fires, and a subagent
asking to push should be told to hand back its SHA, not how to retry the push.
"""

from __future__ import annotations

import re
from typing import Final

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS
from dev_lab.dev.agentpolicy import MAIN, POLICY, module_verbs

__all__ = ['MAIN_ONLY_DOOR', 'PUBLISHING_MODULES', 'READ_ONLY_FLAGS', 'SUBAGENT_NO_PUSH']

_INTERPRETER = r'\S*python[\w.]*(?:\.exe)?\s+'

#: The modules whose main-only doors PUBLISH (a PR's lifecycle, the trunk's move, a remote branch's deletion):
#: SUBAGENT-NO-PUSH's. Every other main-only ``python -m`` door is MAIN-ONLY-DOOR's.
PUBLISHING_MODULES: Final = frozenset({'dev_lab.dev.forge', 'dev_lab.dev.integrate', 'dev_lab.dev.branchprune'})

#: ``(module, verb) -> flag``: a main-only door that, WITH the flag in its own argument list, only prints what it
#: would do -- no connection opened, nothing started or written -- so any agent may read it. A dry run that still
#: reaches an account over ssh (``hpcaccount forget``, ``retention``) is not one and stays the main session's.
READ_ONLY_FLAGS: Final[dict[tuple[str, tuple[str, ...]], str]] = {
    ('dev_lab.dev.hpcaccount', ('deploy-fleet',)): '--dry-run',
}


def _verb(module: str, verb: tuple[str, ...]) -> str:
    """One verb as a pattern; with its :data:`READ_ONLY_FLAGS` flag in the same segment it is not matched."""
    spelled = r'\s+'.join(re.escape(word) for word in verb) + r'(?![\w-])'
    flag = READ_ONLY_FLAGS.get((module, verb))
    return spelled if flag is None else rf'{spelled}(?![^\n;&|]*\s{re.escape(flag)}(?![\w-]))'


def _main_doors(*, publishing: bool) -> str:
    """The ``python -m`` doors the policy table gives the MAIN session alone, as one alternation (derived).

    *publishing* picks the half: the doors of :data:`PUBLISHING_MODULES`, or every other one.
    """
    alternatives = []
    for module, verbs in module_verbs(MAIN).items():
        if (module in PUBLISHING_MODULES) is not publishing:
            continue
        head = rf'{_INTERPRETER}-m\s+{re.escape(module)}'
        if () in verbs:  # a door that is the whole module: every verb of it is the main session's
            alternatives.append(rf'{head}(?![\w.-])')
            continue
        alternatives.append(rf'{head}\s+(?:{"|".join(_verb(module, verb) for verb in verbs)})')
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
        # Every PUBLISHING door the policy table gives the main session alone (agentpolicy.MAIN): PRs, promote, ...
        rf'|{_main_doors(publishing=True)}'
        rf'|{_main_client_doors()}'
        r'|git(?:\.exe)?\b[^\n]*\s--no-verify\b'
        # PowerShell spells the same skip as an environment assignment.
        r"""|SKIP=|\$env:SKIP\s*=)"""
    ),
    # 'shell': a python heredoc EDITING text that names a push is not a push (O25, 2026-11-17).
    'matches': 'shell',
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
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge issue create --title x --kind need',
        'gh workflow list -R o/r',
    ),
}

MAIN_ONLY_DOOR: dict[str, object] = {
    'id': 'MAIN-ONLY-DOOR',
    'pattern': rf'(?:{_main_doors(publishing=False)})',
    'matches': 'shell',
    'scope': 'subagent',
    'hazard': 'this door is the main session`s alone: it acts on another machine or on shared state under the '
    'user`s word.',
    'remedy': 'Hand the exact command back to the main session, which runs it and reads the result. Reading stays '
    'yours: {python} -m dev_lab.dev.sshhold status, {python} -m dev_lab.dev.hpcaccount drift-fleet, '
    'and hpcaccount deploy-fleet --dry-run.',
    'needs': None,
    'refuses': (
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.sshhold open alice@hpclogin01.example.org --hours 2 --code 123456',
        f"{VENV_PYTHONS[0]} -m dev_lab.dev.sshhold run alice@hpclogin01.example.org 'squeue'",
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.hpcaccount deploy-fleet --account alice',
        f'{VENV_PYTHONS[1]} -m dev_lab.dev.hpcaccount forget --repo u --row k --fleet --dry-run',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.opsserver status forge',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.family join https://example.org/o/r',
    ),
    'permits': (
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.sshhold status',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.hpcaccount deploy-fleet --account alice --dry-run',
        f'{VENV_PYTHONS[1]} -m dev_lab.dev.hpcaccount drift-fleet',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.family check',
        'git commit -m "sshhold open is the main session`s"',
    ),
}
