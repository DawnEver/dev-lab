"""WHICH ENVIRONMENT A NEW LAUNCH TAKES: the one reader of ``ROOT/.venv-current`` (dev-lab #632).

THE RULE is authored once, in the shipped ``venv_resolver.js`` (dev-lab #641): every JS door requires it, its
``--shell`` rendering is the block ``githooks/with-venv.sh`` carries (:func:`shell_function` reads it there for the
git hook shims and the remote deploy lines), and this module is its Python twin -- tests hold all three to one answer.
Dependency-free so :mod:`dev_lab.dev.venvpath` can resolve through it; :mod:`dev_lab.dev.venvcurrent` builds,
publishes and reclaims.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Final

__all__ = [
    'HOME',
    'POINTER',
    'READ_TRIES',
    'RETIRED_ALIAS',
    'current',
    'current_interpreter',
    'env_checkout',
    'named',
    'shell_function',
    'shell_interpreter',
    'superseded',
]

#: The one file whose content names the current environment (a directory name under :data:`HOME`).
POINTER: Final = '.venv-current'
#: Where every environment lives, side by side.
HOME: Final = '.venvs'
#: The retired spelling: once a junction to the current environment, before that the legacy layout's directory.
#: Nothing reads it; :func:`dev_lab.dev.venvcurrent.retire_alias` removes it once, ``hpcaccount drift`` reports it.
RETIRED_ALIAS: Final = '.venv'
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
    """The environment a NEW launch in checkout *root* runs from: the one the pointer names.

    Pointing at nothing, the answer is the pointer itself: a file, so no interpreter resolves under it and every
    miss names :data:`POINTER` as its cause (the door: ``dev_lab.dev.dep --bootstrap``).
    """
    return named(root) or Path(root) / POINTER


def env_checkout(prefix: str | Path) -> Path | None:
    """The checkout whose environment *prefix* is (a ``ROOT/.venvs/<name>``), else ``None``."""
    prefix = Path(prefix)
    return prefix.parent.parent if prefix.parent.name == HOME else None


def superseded(prefix: str | Path) -> bool:
    """Whether another environment than *prefix* (a checkout's ``.venvs/<name>`` or ``.venv``) is now current.

    A legacy ``.venv`` directory is superseded once the pointer names another environment, so what runs from it
    yields and the directory drains; ``.venv`` as the alias of the current environment is not.
    """
    root = env_checkout(prefix)
    return root is not None and current(root).resolve() != Path(prefix).resolve()


def current_interpreter(executable: str | Path | None = None) -> str:
    """*executable* (default: this process's) re-resolved to its checkout's CURRENT environment.

    The door every child launch takes: a process started from a legacy ``.venv`` or an older ``.venvs/<name>``
    starts its children from the published one, so nothing new holds the environment it ran from. An interpreter
    of no checkout, or a current environment without the same interpreter, is returned unchanged.
    """
    python = Path(sys.executable if executable is None else executable).absolute()
    prefix = python.parent.parent
    root = env_checkout(prefix)
    if root is None or current(root).resolve() == prefix.resolve():
        return str(python)
    candidate = current(root) / python.parent.name / python.name
    return str(candidate) if candidate.is_file() else str(python)


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
