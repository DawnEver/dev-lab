"""The ENVIRONMENT-THROUGH-DEP deny row -- pure DATA.

MEASURED 2026-11-26: a bare ``uv sync``, issued through the network door, built a checkout's
plain ``.venv`` with no declared extras, no published side-by-side prefix and no anchor -- and nothing refused it.
``dev_lab.dev.dep`` is the one writer of a checkout's environment; it runs ``uv sync`` itself, retried there, so
neither spelling of a bare sync (raw, or behind ``netverb --``) is a door.
"""

from __future__ import annotations

from dev_lab.dev.venvpath import venv_interpreter

__all__ = ['ENVIRONMENT_THROUGH_DEP']

#: The network door in front of a command, when present: ``<python> -m dev_lab.dev.netverb [opts] --``.
_NETVERB = r'(?:\S*python[\w.]*\s+-m\s+dev_lab\.dev\.netverb\b[^;&|\n]*?\s--\s+)?'
#: ``uv`` by any path (``.exe`` in any case: Windows spells ``uv.EXE``), then its global options
#: (a separate value included) before the verb.
_UV = r'(?:\S*[/\\])?uv(?:\.[eE][xX][eE])?(?:\s+-\S+(?:\s+[^-\s]\S*)?)*?'

ENVIRONMENT_THROUGH_DEP: dict[str, object] = {
    'id': 'ENVIRONMENT-THROUGH-DEP',
    'pattern': _NETVERB + _UV + r'\s+sync\b',
    'matches': 'command',
    'hazard': 'a bare uv sync builds a checkout environment with no declared extras and no published prefix.',
    'remedy': 'Build the environment through its door: {python} -m dev_lab.dev.dep --bootstrap <checkout> '
    '(a new tree), or {python} -m dev_lab.dev.dep --root <checkout> --sync [--extra X].',
    'needs': None,
    'refuses': (
        'uv sync',
        'uv sync --frozen --extra test',
        'uv --directory .claude/worktrees/x sync',
        'C:/x/uv.EXE sync',
        'python -m dev_lab.dev.netverb -- uv sync',
        f'{venv_interpreter(os_name="nt")} -m dev_lab.dev.netverb --attempts 2 -- uv sync --frozen',
    ),
    'permits': (
        'python -m dev_lab.dev.dep --bootstrap .claude/worktrees/x',
        'python -m dev_lab.dev.dep --root . --sync --extra test',
        'uv lock',
        'uv pip list',
        'uv lock --no-sync',
        'git commit -m "uv sync is refused"',
        'python -m dev_lab.dev.netverb -- uv lock',
    ),
}
