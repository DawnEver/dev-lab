"""THE MACHINE HOME, HANDED TO rem: ``LAB_COMMONS_HOME`` in the user's Claude settings, set from lab_commons.home.

rem (node, a public plugin) writes each session's task binding into ``<machine home>/state/sessions/`` (D34,
:mod:`dev_lab.dev.taskbinding`). It cannot import Python and must not spell the private home, so it reads ONE neutral
variable, :data:`VARIABLE`, and nothing else; unset, it binds nothing and names this command. The value is never
authored by hand: :func:`wire` copies :func:`lab_commons.home.home` into the ``env`` table of the user-level Claude
settings (never a committed repo file), so lab_commons stays the one source of the path.

Those settings may be ONE file synced to every machine (D41), so the value is written MACHINE-INDEPENDENT:
``~/<relative>`` (:func:`portable`), which each reader expands with its own home directory. A home outside the
user's home directory has no such form and is refused, never written: it belongs in that machine's own environment.

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

__all__ = ['VARIABLE', 'main', 'portable', 'settings_path', 'stale', 'wire']

#: The one variable rem reads the machine home from.
VARIABLE: Final = 'LAB_COMMONS_HOME'


def settings_path() -> Path:
    """The user-level Claude settings: ``$CLAUDE_CONFIG_DIR/settings.json``, else ``~/.claude/settings.json``."""
    root = os.environ.get('CLAUDE_CONFIG_DIR')
    return (Path(root) if root else Path.home() / '.claude') / 'settings.json'


def portable() -> str:
    """The machine home as ``~/<relative>``, the same text on every machine; raises when it has no such form."""
    target = home()
    try:
        relative = target.relative_to(Path.home())
    except ValueError:
        msg = (
            f'the machine home {target.as_posix()!r} lies outside the user home {Path.home().as_posix()!r}: a '
            f'machine-specific path is never written into the user Claude settings, which may be synced to every '
            f'machine (D41); set {VARIABLE} in the environment of this machine instead'
        )
        raise ValueError(msg) from None
    return '~' if relative == Path() else f'~/{relative.as_posix()}'


def _expand(held: str) -> Path | None:
    """*held* expanded with this machine home when it is a ``~`` value; ``None`` for anything else."""
    if held == '~' or held.startswith(('~/', '~\\')):
        return Path.home() / held[2:]
    return None


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
    want = portable()
    if isinstance(held, str) and _expand(held) == home():
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
    settings['env'] = {**env, VARIABLE: portable()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return True


def main(argv: list[str] | None = None) -> int:
    """Report (or with ``--install`` write) the machine home handed to rem."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.remhome', description=__doc__.splitlines()[0])
    parser.add_argument('--install', action='store_true', help=f'write {VARIABLE} into the user Claude settings')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.install:
            emit(f'{VARIABLE}: {"written" if wire() else "already current"} in {settings_path().as_posix()}')
            return 0
        why = stale()
    except ValueError as refused:
        emit(str(refused))
        return 1
    emit(why or f'{VARIABLE} is current in {settings_path().as_posix()}')
    return 1 if why else 0


if __name__ == '__main__':
    raise SystemExit(main())
