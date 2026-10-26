"""The agent deny registry, BARE-INTERPRETER and BARE-PYTHON rows -- pure DATA, every spelling derived from the owner.

USER RULING 2026-10-03: `.claude/settings.json` allows only the checkout's venv interpreter
(:data:`dev_lab.dev.venvpath.VENV_INTERPRETER_GLOB`), yet agents reflexively type `uv run python`
or a bare `python`. Each of those resolves an interpreter somebody else chose -- uv's managed one, the
PATH's -- and a `uv run` may also SYNC the checkout's environment first. This row is the feedback at the
moment of the mistake, and its exit is spelled by :mod:`dev_lab.dev.venvpath`, the ONE owner of
the interpreter spelling; the settings allow row is derived from the same owner
(:func:`dev_lab.dev.allow_adoption.derived_entries`).

A repo's own user-facing CLI behind `uv run` (one consumer reproduces only through `uv run <its cli>`)
is a per-repo OPENING supplied as that repo's ``Remedy.allow`` for this row -- a delta, not a hole here.
`python -m pytest` is left to ``BARE-TEST-INVOCATION``: one shape, one row.

ONE HAZARD, ONE SEVERITY (toolchain plan P3, user 2026-10-23): `uv run` and `uvx` may SYNC an environment
before they run, which is harm, so BARE-INTERPRETER refuses them; a bare `python`/`py` only runs an
interpreter somebody else chose, so BARE-PYTHON says the same exit and lets the call run.
"""

from __future__ import annotations

from dev_lab.dev.venvpath import INTERPRETER_ALLOW_ENTRY, INTERPRETER_RULE, PYTHON_TOKEN, VENV_LAYOUTS

__all__ = ['BARE_INTERPRETER', 'BARE_PYTHON', 'INTERPRETER_REMEDY']

_NT = '/'.join(VENV_LAYOUTS['nt'])
_POSIX = '/'.join(VENV_LAYOUTS['posix'])

#: Each checkout owns its interpreter; bootstrap a missing environment rather than borrowing main. Named by
#: ABSOLUTE path through the engine's token (2026-10-26: the relative spelling failed from another cwd).
INTERPRETER_REMEDY = (
    f"Use {PYTHON_TOKEN}, this worktree's own interpreter (main's is main-only); bootstrap a missing one "
    f'with {PYTHON_TOKEN} -m dev_lab.dev.dep --bootstrap <worktree> (checked doors are '
    f'agent-allowed, not arbitrary installers; allowed: {INTERPRETER_ALLOW_ENTRY}).'
)

BARE_INTERPRETER: dict[str, object] = {
    'id': INTERPRETER_RULE,
    'pattern': r'(?:uv(?:\.exe)?\s+run\b|uvx(?:\.exe)?\b)',
    'matches': 'command',
    'hazard': '`uv run` or `uvx` runs an interpreter somebody else chose and may sync '
    'the checkout environment outside the checked dependency door.',
    'remedy': INTERPRETER_REMEDY,
    'needs': None,
    'refuses': (
        'uv run python x.py',
        'uv run -m dev_lab.dev.verify',
        'uv run --no-sync python -c "print(1)"',
        'uvx python',
        'uv.exe run x.py',
    ),
    'permits': (
        f'{_NT} -m dev_lab.dev.verify',
        'python x.py',
        'uv pip list',
        'git commit -m "uv run here"',
        'grep -n "uv run" src/a.py',
    ),
}

BARE_PYTHON: dict[str, object] = {
    'id': 'BARE-PYTHON',
    'pattern': r'(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?(?![\w./\\-])(?!\s+-m\s+pytest\b)',
    'matches': 'command',
    'hazard': "a bare python/py runs the interpreter PATH chose, not this checkout's venv.",
    'remedy': INTERPRETER_REMEDY,
    'needs': None,
    # A HINT (toolchain plan P3): no environment is mutated, so the hazard is a wrong interpreter, not harm.
    'severity': 'hint',
    'refuses': (
        'python x.py',
        'python3 -m pip list',
        'python3.13 -c "print(1)"',
        'py -3 x.py',
        'python.exe -V',
        'python - <<EOF',
    ),
    'permits': (
        f'{_NT} -m dev_lab.dev.verify',
        f'{_POSIX} x.py',
        f'./{_POSIX} -c "print(1)"',
        f'C:/work/repo/{_NT} -V',
        'pythonic-tool --help',
        'git commit -m "run python here"',
    ),
}
