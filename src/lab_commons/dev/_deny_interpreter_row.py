"""The agent deny registry, BARE-INTERPRETER row -- pure DATA, every spelling derived from the owner.

USER RULING 2026-10-03: `.claude/settings.json` allows only the checkout's venv interpreter
(:data:`lab_commons.dev.venvpath.VENV_INTERPRETER_GLOB`), yet agents reflexively type `uv run python`
or a bare `python`. Each of those resolves an interpreter somebody else chose -- uv's managed one, the
PATH's -- and a `uv run` may also SYNC the shared environment first. This row is the feedback at the
moment of the mistake, and its exit is spelled by :mod:`lab_commons.dev.venvpath`, the ONE owner of
the interpreter spelling; the settings allow row is derived from the same owner
(:func:`lab_commons.dev.allow_adoption.derived_entries`).

A repo's own user-facing CLI behind `uv run` (one consumer reproduces only through `uv run <its cli>`)
is a per-repo OPENING supplied as that repo's ``Remedy.allow`` for this row -- a delta, not a hole here.
`python -m pytest` is left to ``BARE-TEST-INVOCATION``: one shape, one row.
"""

from __future__ import annotations

from lab_commons.dev.venvpath import INTERPRETER_ALLOW_ENTRY, INTERPRETER_RULE, VENV_LAYOUTS

__all__ = ['BARE_INTERPRETER', 'INTERPRETER_REMEDY']

_NT = '/'.join(VENV_LAYOUTS['nt'])
_POSIX = '/'.join(VENV_LAYOUTS['posix'])

#: The exit, spelled from the owner: the concrete interpreter per platform, and the worktree fallback.
INTERPRETER_REMEDY = (
    f"Run the checkout's venv interpreter: {_NT} <args> ({_POSIX} on POSIX); in a worktree without one, "
    f'<main>/{_NT} <args>. Allowed: {INTERPRETER_ALLOW_ENTRY}; a repo-declared CLI stays allowed.'
)

BARE_INTERPRETER: dict[str, object] = {
    'id': INTERPRETER_RULE,
    'pattern': (
        r'(?:uv(?:\.exe)?\s+run\b|uvx(?:\.exe)?\b'
        r'|(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?(?![\w./\\-])(?!\s+-m\s+pytest\b))'
    ),
    'matches': 'command',
    'hazard': 'a bare python/py, `uv run` or `uvx` runs an interpreter somebody '
    'else chose, and `uv run` may sync the shared environment.',
    'remedy': INTERPRETER_REMEDY,
    'needs': None,
    'refuses': (
        'uv run python x.py',
        'uv run -m lab_commons.dev.verify',
        'uv run --no-sync python -c "print(1)"',
        'uvx python',
        'python x.py',
        'python3 -m pip list',
        'python3.13 -c "print(1)"',
        'py -3 x.py',
        'python.exe -V',
        'python - <<EOF',
    ),
    'permits': (
        f'{_NT} -m lab_commons.dev.verify',
        f'{_POSIX} x.py',
        f'./{_POSIX} -c "print(1)"',
        f'C:/work/repo/{_NT} -V',
        'pythonic-tool --help',
        'git commit -m "run python here"',
        'grep -n "uv run" src/a.py',
    ),
}
