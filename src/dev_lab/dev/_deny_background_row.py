"""The BACKGROUND-SHELL-IS-BOUNDED deny row -- pure DATA, judged only on a Bash call run in the background.

``when: 'background'``: the engine binds the row only when the call carries ``run_in_background``, and then asks
:mod:`dev_lab.dev.shelllife` (``--admit``) for the judgement -- a line starts with ``timeout <n>``, and above
:data:`DEFAULT_LIFETIME_S` carries the USER's grant (user ruling 2026-11-15). This pattern is the judgement only
where no interpreter can be asked. The default is declared HERE: the deny registry may not import the sweep,
which imports the registry through ``stoprun``. Refused rather than rewritten: the hook API's ``updatedInput`` is
dropped for Bash (the engine's own note, ``DENY, NOT REWRITE``).
"""

from __future__ import annotations

from typing import Final

#: THE DEFAULT LIFETIME of an agent's background shell (user demand 2026-11-15), declared once.
DEFAULT_LIFETIME_S: Final = 50 * 60.0

_MINUTES = f'{DEFAULT_LIFETIME_S / 60:.0f}m'

BACKGROUND_BOUNDED: dict[str, object] = {
    'id': 'BACKGROUND-SHELL-IS-BOUNDED',
    # The whole line, not a segment: a bound on a LATER segment leaves the first one unbounded.
    'pattern': r'^(?![ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*timeout[ \t]+(?:-\S+[ \t]+)*\d)',
    'matches': 'line',
    'when': 'background',
    'hazard': f'a background shell outlives its purpose and its session; the reaper stops one at {_MINUTES} '
    'unless the user granted more.',
    'remedy': f"Start the line with timeout {_MINUTES} <command> (compound: timeout {_MINUTES} bash -c '<line>'). "
    'Longer: ask the user for the code; once they approve, python -m dev_lab.ops.consent grant <request.json> '
    '--code <code> (a longer bound names the request).',
    'needs': None,
    'refuses': (
        'until test -f done; do sleep 30; done',
        'python -m dev_lab.dev.forge watch --stream',
        'cd x && timeout 50m make',
        'echo timeout 5m',
    ),
    'permits': (
        'timeout 50m python -m dev_lab.dev.forge watch --stream',
        'timeout 40m sh -c "until test -f done; do sleep 30; done"',
        'timeout -k 10 90m make',
        'LC_ALL=C timeout 300 make',
    ),
}
