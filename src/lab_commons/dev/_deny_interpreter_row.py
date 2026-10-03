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
    f"Run the checkout's own venv interpreter: {_NT} <args> on Windows, {_POSIX} <args> on POSIX "
    f'(settings.json allows {INTERPRETER_ALLOW_ENTRY}). In a worktree with no .venv of its own, run '
    f"the MAIN checkout's: <main>/{_NT} <args> -- `git rev-parse --path-format=absolute --git-common-dir` "
    f'prints <main>/.git. A repo CLI the repo declares (its own opening) stays allowed.'
)

BARE_INTERPRETER: dict[str, object] = {
    'id': INTERPRETER_RULE,
    'pattern': (
        r'(?:uv(?:\.exe)?\s+run\b|uvx(?:\.exe)?\b'
        r'|(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?(?![\w./\\-])(?!\s+-m\s+pytest\b))'
    ),
    'matches': 'command',
    'hazard': (
        'a bare `python`/`py`, `uv run` or `uvx` runs an interpreter somebody else chose -- the PATH`s, or '
        'uv`s managed one -- not this checkout`s venv, and `uv run` may sync the SHARED environment first. '
        'The allow list names only the venv interpreter, so the reflex spelling is also the one that '
        'stalls on a permission prompt (user ruling 2026-10-03).'
    ),
    'remedy': INTERPRETER_REMEDY,
    'needs': None,
    'refuses': (
        'uv run python scripts/x.py',
        'uv run -m lab_commons.dev.verify',
        'uv run --no-sync python -c "print(1)"',
        'uvx python',
        'python scripts/x.py',
        'python3 -m pip list',
        'python3.13 -c "print(1)"',
        'py -3 scripts/x.py',
        'python.exe -V',
        'python - <<EOF',
    ),
    'permits': (
        '.venv/Scripts/python.exe -m lab_commons.dev.verify',
        '.venv/bin/python scripts/x.py',
        './.venv/bin/python -c "print(1)"',
        'C:/work/repo/.venv/Scripts/python.exe -V',
        'pythonic-tool --help',
        'git commit -m "run python here"',
        'grep -rn "uv run" src',
    ),
}
