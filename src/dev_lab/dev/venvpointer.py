"""WHICH ENVIRONMENT A NEW LAUNCH TAKES: the one reader of ``ROOT/.venv-current`` (dev-lab #632).

THE RULE is authored once, in the shipped ``venv_resolver.js`` (dev-lab #641): every JS door requires it, its
``--shell`` rendering is the block ``githooks/with-venv.sh`` carries (:func:`shell_function` reads it there for the
git hook shims and the remote deploy lines), and this module is its Python twin -- tests hold all three to one answer.
Dependency-free so :mod:`dev_lab.dev.venvpath` can resolve through it; :mod:`dev_lab.dev.venvcurrent` builds,
publishes and reclaims.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

__all__ = [
    'ALIAS',
    'HOME',
    'POINTER',
    'READ_TRIES',
    'current',
    'named',
    'shell_function',
    'shell_interpreter',
    'superseded',
]

#: The one file whose content names the current environment (a directory name under :data:`HOME`).
POINTER: Final = '.venv-current'
#: Where every environment lives, side by side.
HOME: Final = '.venvs'
#: The alias kept for external tools: a junction/symlink to the current environment; the legacy layout's directory.
ALIAS: Final = '.venv'
#: Windows refuses to open a file in the instant ``os.replace`` swaps it: the read is retried this often.
READ_TRIES: Final = 50


def named(root: Path) -> Path | None:
    """The environment the pointer names, when the pointer exists and names a directory under :data:`HOME`."""
    name = _read(Path(root) / POINTER)
    if not name or name in {'.', '..'} or any(char in name for char in '/\\:'):
        return None
    env = Path(root) / HOME / name
    return env if env.is_dir() else None


def _read(pointer: Path) -> str:
    """The pointer's content, ``''`` when absent; a sharing violation mid-swap is retried, never read as absent."""
    for _ in range(READ_TRIES):
        try:
            return pointer.read_text(encoding='utf-8').split('\n', 1)[0].strip()
        except PermissionError:
            time.sleep(0.01)
        except OSError:
            return ''
    return ''


def current(root: Path) -> Path:
    """The environment a NEW launch in checkout *root* runs from: the pointer's, else the legacy ``.venv``."""
    return named(root) or Path(root) / ALIAS


def superseded(prefix: str | Path) -> bool:
    """Whether a newer environment than *prefix* (a checkout's ``.venvs/<name>`` or ``.venv``) is now current."""
    prefix = Path(prefix)
    if prefix.parent.name == HOME:
        root = prefix.parent.parent
    else:
        return False  # a legacy .venv or no checkout's env: nothing was published beside it
    return current(root).resolve() != prefix.resolve()


#: The rendered POSIX twin's home and markers (``node venv_resolver.js --shell``).
_SHELL_HOME: Final = Path(__file__).with_name('githooks') / 'with-venv.sh'
_BEGIN: Final = '# BEGIN venv_resolver.js --shell\n'
_END: Final = '\n# END venv_resolver.js --shell'


def shell_function() -> str:
    """The one-line POSIX definition of ``_current_env ROOT``, as ``venv_resolver.js --shell`` renders it."""
    text = _SHELL_HOME.read_text(encoding='utf-8')
    return text[text.index(_BEGIN) + len(_BEGIN) : text.index(_END)]


def shell_interpreter(root: str) -> str:
    """One POSIX shell word: *root*'s current environment's interpreter, resolved by the one rule.

    The resolver is defined inside the word's own command substitution, so the word stands anywhere in a line: a
    cron entry, an ``&&`` chain, ``flock``'s argv.
    """
    return f'"$({shell_function()}; _current_env {root})/bin/python"'
