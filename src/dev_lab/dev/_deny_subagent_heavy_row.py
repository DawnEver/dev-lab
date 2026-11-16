"""The HEAVY-IS-THE-MAIN-SESSIONS deny row -- pure DATA, scoped to subagents.

User ruling 2026-11-16: the MAIN session alone coordinates heavy testing. It requests full or heavy runs on the
repo's declared producer and reads the verdicts; a subagent develops and measures only the files it touches.

DETECTION is SUBAGENT-NO-PUSH's: ``scope: 'subagent'``, which the engine binds only when the hook payload carries a
non-empty ``agent_id`` (sent only inside a subagent call, forks included). A main session is never judged here, so
its producer requests stay open, and its LOCAL heavy stays refused where it already was -- at the runner, for
everyone outside the producer (VERDICTS-FROM-THE-FORGE, :func:`dev_lab.dev.producer.full_suite_refusal`). This row
duplicates none of that: it only names the subagent's door before the runner is ever reached.
"""

from __future__ import annotations

from dev_lab.dev._deny_forge_rows import VENV_PYTHONS

_INTERPRETER = r'\S*python[\w.]*(?:\.exe)?\s+'

HEAVY_IS_THE_MAIN_SESSIONS: dict[str, object] = {
    'id': 'HEAVY-IS-THE-MAIN-SESSIONS',
    'pattern': (
        # A heavy or full local selection: the family runner, or a consumer gate runner.
        rf'(?:{_INTERPRETER}-m\s+dev_lab\.dev\.verify\b[^\n]*\s--with-heavy\b'
        rf'|(?:{_INTERPRETER})?\S*scripts/gate/runner\.py\s+(?:gate|heavy)(?![\w-])'
        rf'|(?:{_INTERPRETER})?\S*scripts/gate/runner\.py\b[^\n]*\s--with-heavy\b'
        # A request on the producer: the forge's, or a cluster submit.
        rf'|{_INTERPRETER}-m\s+dev_lab\.dev\.forge\s+request(?![\w-])'
        rf'|{_INTERPRETER}-m\s+lab_commons\.hpc\s+(?:run\s+)?submit(?![\w-]))'
    ),
    'matches': 'command',
    'scope': 'subagent',
    'hazard': 'heavy testing is the main session`s: it requests runs on the producer and reads the verdicts, '
    'and no local machine runs heavy tests.',
    'remedy': 'Hand the request to the main session: commit on your lane and hand back the SHA; '
    'measure only the tests you touched: {python} -m dev_lab.dev.verify -- <paths>.',
    'needs': None,
    'refuses': (
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.verify --with-heavy -- tests/test_x.py',
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py gate',
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py heavy tests/x.py',
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py measure --with-heavy tests/x.py',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge request tests --sha 0123abc',
        'python -m lab_commons.hpc submit -c job.toml',
        'python -m lab_commons.hpc run submit --sha 0123abc',
    ),
    'permits': (
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.verify -- tests/x.py',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.verify --lock-wait "40 min" -- tests/test_heavy.py',
        f'{VENV_PYTHONS[0]} scripts/gate/runner.py measure tests/test_gate.py',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge queue',
        f'{VENV_PYTHONS[0]} -m dev_lab.dev.forge requests',
        'python -m lab_commons.hpc gather -c job.toml --wait',
        'git commit -m "forge request later; heavy belongs to main"',
    ),
}
