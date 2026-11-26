"""The ``.git/hooks/<stage>`` shim text -- what :mod:`dev_lab.dev.hook_install` writes and compares.

The installer decides WHERE a shim goes and whether the one there is ours; this module owns WHAT a shim
says: the interpreter candidates it probes, the fallback it records, and the refusal it prints when none
imports dev_lab.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

from dev_lab.dev.githooks.runner import IMPORT_ERROR_ENV
from dev_lab.dev.githooks.table import ADVISORY
from dev_lab.dev.venvpath import CANDIDATE_RELATIVE_PATHS
from dev_lab.dev.venvpointer import env_checkout, shell_function

__all__ = ['INSTALL_COMMAND', 'SHIM_MARKER', 'same_shim', 'shim']

#: The line every shim carries: present means ours (installed or stale), absent means FOREIGN.
SHIM_MARKER: Final = '# dev_lab.dev.githooks shim'

#: The one remedy, a constant: the stage list is read from the table at install time, never restated.
INSTALL_COMMAND: Final = 'python -m dev_lab.dev.hook_install --install'


_FALLBACK_LINE: Final = re.compile(r'^fallback=.*$', re.MULTILINE)


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _fallback_word(recorded: Path) -> str:
    """*recorded* as one shell word: a checkout environment's interpreter re-resolves to that checkout's CURRENT one.

    An install run from a legacy ``.venv`` (or an older ``.venvs/<name>``) would otherwise pin that environment in
    every shim, and each commit would execute from it again -- so it never drains.
    """
    root = env_checkout(recorded.parent.parent)
    if root is None:
        return _sh_quote(recorded.as_posix())
    return f'"$(_current_env {_sh_quote(root.as_posix())})/{recorded.parent.name}/{recorded.name}"'


def shim(stage: str, fallback: str | None = None) -> str:
    """The ``.git/hooks/<stage>`` file: this checkout's venv, else the main checkout's, else a family one, else REFUSE.

    Every candidate is PROBED (``import dev_lab.dev.githooks``), its own venv included: a half-built venv is
    passed over, never exec'd into a ``No module named``. A borrowed interpreter (the MAIN checkout's venv, else
    *fallback*: the interpreter running the install, recorded in the file) runs the stage, and the runner
    (:func:`dev_lab.dev.githooks.runner.borrowed_interpreter`) refuses a judged stage there naming the bootstrap
    door, running only the rows that create the venv at an advisory one (dev-lab #639). With no interpreter
    anywhere the commit or push is REFUSED naming the bootstrap and install doors: a commit no hook judged was
    made silently, and a message or a marker it carried cannot be taken back once pushed.
    """
    recorded = Path(fallback if fallback is not None else sys.executable)
    found = ' '.join(
        f'"$(_current_env "${root}")/{"/".join(parts[1:])}"'
        for root in ('top', 'main')
        for parts in CANDIDATE_RELATIVE_PATHS
    )
    return (
        '#!/bin/sh\n'
        f'{SHIM_MARKER} -- installed by `{INSTALL_COMMAND}`; the hooks are declared in TOML\n'
        '# (dev_lab/dev/githooks/base.toml + [tool.dev_lab.hooks] in pyproject.toml).\n'
        'top=$(git rev-parse --show-toplevel) || exit 1\n'
        'main=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")\n'
        f'{shell_function()}\n'
        f'fallback={_fallback_word(recorded)}\n'
        'why=\n'
        f'for found in {found} "$fallback"; do\n'
        '  [ -x "$found" ] || continue\n'
        '  if said=$("$found" -c "import dev_lab.dev.githooks" 2>&1); then\n'
        f'    export {IMPORT_ERROR_ENV}="$why"\n'
        f'    exec "$found" -m dev_lab.dev.githooks run {stage} "$@"\n'
        '  fi\n'
        '  [ -n "$why" ] || why="$found: $(echo "$said" | tail -n 1)"\n'
        'done\n'
        f'{_no_interpreter(stage)}'
    )


#: The door that creates a checkout's venv, run by any interpreter that imports dev_lab.
_BOOTSTRAP: Final = (
    'python -m dev_lab.dev.dep --bootstrap $top (with any interpreter that imports dev_lab, e.g. a sibling venv)'
)
#: The real cause, when a candidate interpreter existed and its import probe failed.
_PROBE_SAID: Final = '${why:+ The import probe said: $why}'


def _no_interpreter(stage: str) -> str:
    """The shim's last lines when nothing could run *stage*: a judged stage is refused; each says the door."""
    if stage in ADVISORY:
        return (
            f'echo "[githooks] {stage}: no venv in $top or $main, no interpreter that imports dev_lab; nothing ran.'
            f' This checkout needs its own venv: {_BOOTSTRAP}, then {INSTALL_COMMAND}.{_PROBE_SAID}" >&2\n'
            'exit 0\n'
        )
    return (
        f'echo "[githooks] {stage}: no venv in $top or $main, no interpreter that imports dev_lab; refused --'
        f' no hook would judge it. Bootstrap the venv ({_BOOTSTRAP}), install the hooks ({INSTALL_COMMAND}),'
        f' then try again.{_PROBE_SAID}" >&2\n'
        'exit 1\n'
    )


def same_shim(text: str, stage: str) -> bool:
    """*text* is the current shim of *stage*, whichever interpreter the install recorded."""
    return _FALLBACK_LINE.sub('', text) == _FALLBACK_LINE.sub('', shim(stage))
