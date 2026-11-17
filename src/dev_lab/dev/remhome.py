"""THE MACHINE HOME, HANDED TO rem: ``LAB_COMMONS_HOME`` in the user's Claude settings, set from lab_commons.home.

rem (node, a public plugin) writes each session's task binding into ``<machine home>/state/sessions/`` (D34,
:mod:`dev_lab.dev.taskbinding`). It cannot import Python and must not spell the private home, so it reads ONE neutral
variable, :data:`VARIABLE`, and nothing else; unset, it binds nothing and names this command. The value is never
authored by hand: :func:`wire` copies :func:`lab_commons.home.home` into the ``env`` table of the user-level Claude
settings (machine-local, never a committed repo file), so lab_commons stays the one source of the path.

``python -m dev_lab.dev.remhome`` reports whether the settings hold the current home (exit 1 when stale or absent);
``--install`` writes it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Final

from lab_commons.home import home
from lab_commons.log import emit

__all__ = ['VARIABLE', 'main', 'settings_path', 'stale', 'wire']

#: The one variable rem reads the machine home from.
VARIABLE: Final = 'LAB_COMMONS_HOME'


def settings_path() -> Path:
    """The user-level Claude settings: ``$CLAUDE_CONFIG_DIR/settings.json``, else ``~/.claude/settings.json``."""
    root = os.environ.get('CLAUDE_CONFIG_DIR')
    return (Path(root) if root else Path.home() / '.claude') / 'settings.json'


def _read(path: Path) -> dict:
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(found, dict):
        msg = f'{path} is not a JSON object'
        raise TypeError(msg)
    return found


def stale(path: Path | None = None) -> str | None:
    """Why the settings at *path* do not hand rem the current machine home, or ``None`` when they do."""
    path = settings_path() if path is None else path
    env = _read(path).get('env')
    held = env.get(VARIABLE) if isinstance(env, dict) else None
    want = str(home())
    if held == want:
        return None
    said = 'is unset' if held is None else f'is {held!r}'
    return f'{VARIABLE} in {path.as_posix()} {said}, not the machine home {want!r}'


def wire(path: Path | None = None) -> bool:
    """Write the current machine home as :data:`VARIABLE` into the settings at *path*; whether anything changed."""
    path = settings_path() if path is None else path
    if stale(path) is None:
        return False
    settings = _read(path)
    env = settings.get('env') if isinstance(settings.get('env'), dict) else {}
    settings['env'] = {**env, VARIABLE: str(home())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return True


def main(argv: list[str] | None = None) -> int:
    """Report (or with ``--install`` write) the machine home handed to rem."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.remhome', description=__doc__.splitlines()[0])
    parser.add_argument('--install', action='store_true', help=f'write {VARIABLE} into the user Claude settings')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.install:
        emit(f'{VARIABLE}: {"written" if wire() else "already current"} in {settings_path().as_posix()}')
        return 0
    why = stale()
    emit(why or f'{VARIABLE} is current in {settings_path().as_posix()}')
    return 1 if why else 0


if __name__ == '__main__':
    raise SystemExit(main())
