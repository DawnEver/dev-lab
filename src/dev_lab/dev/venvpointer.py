"""WHICH ENVIRONMENT A NEW LAUNCH TAKES: the one reader of ``ROOT/.venv`` (dev-lab #632; user ruling 2026-11-20).

``.venv`` IS THE POINTER -- the name every tool (uv, VS Code, IDEs, docs) already expects. It is a link (a Windows
junction, a POSIX symlink) to the published environment ``ROOT/.venvs/<name>``, swapped by
:func:`dev_lab.dev.venvcurrent.publish`; a plain ``.venv`` directory (a checkout never published) is its own
environment. The retired pointer file ``.venv-current`` (:data:`RETIRED_POINTER`) is removed once by the migration.

THE RULE is authored once, in the shipped ``venv_resolver.js`` (dev-lab #641): every JS door requires it, its
``--shell`` rendering is the block ``githooks/with-venv.sh`` carries (:func:`shell_function` reads it there for the
git hook shims and the remote deploy lines), and this module is its Python twin -- tests hold all three to one answer.
Each answers the RESOLVED environment, so a launch holds the published directory, never the link, and a later swap
leaves it running where it started. Dependency-free so :mod:`dev_lab.dev.venvpath` can resolve through it.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Final

__all__ = [
    'HOME',
    'POINTER',
    'RETIRED_POINTER',
    'current',
    'current_interpreter',
    'env_checkout',
    'is_link',
    'named',
    'shell_function',
    'shell_interpreter',
    'superseded',
]

#: THE POINTER: a link to the current environment, or (never published) the environment itself.
POINTER: Final = '.venv'
#: Where every published environment lives, side by side.
HOME: Final = '.venvs'
#: The retired pointer file (2026-11-16 .. 2026-11-20): the migration removes it once, the guard refuses its spelling.
RETIRED_POINTER: Final = '.venv-current'


def is_link(path: Path) -> bool:
    """Whether *path* is a symlink or a Windows junction (not a plain directory)."""
    return path.is_symlink() or os.path.isjunction(path)


#: How often a reader re-reads a MISSING pointer before believing it, and how long it waits between reads. A rename
#: over a link is atomic to the link's state, not to every concurrent lookup: macOS (APFS) was measured
#: (dev-lab CI run 44895307619) letting a reader find no ``.venv`` mid ``os.replace``, and the Windows swap has its
#: measured 5-8 ms gap (:mod:`dev_lab.dev.venvcurrent`). A miss that outlives the rereads is real.
REREADS: Final = 10
REREAD_WAIT_S: Final = 0.002


def named(root: Path) -> Path | None:
    """The published environment :data:`POINTER` links to: a directory under :data:`HOME`; else ``None``.

    A miss is re-read up to :data:`REREADS` times, so a swap in flight reads as the old env or the new one.
    """
    for attempt in range(REREADS + 1):
        if (env := _named_once(Path(root) / POINTER)) is not None or attempt == REREADS:
            return env
        time.sleep(REREAD_WAIT_S)
    return None


def _named_once(link: Path) -> Path | None:
    if not is_link(link):
        return None
    try:
        env = link.resolve(strict=True)
    except OSError:
        return None
    return env if env.parent.name == HOME and env.is_dir() else None


def current(root: Path) -> Path:
    """The environment a NEW launch in checkout *root* runs from: :data:`POINTER` resolved.

    A missing or dangling ``.venv`` (re-read like :func:`named`) answers ``ROOT/.venv`` itself, so every miss names
    it (the door: ``dev_lab.dev.dep --bootstrap``).
    """
    link = Path(root) / POINTER
    for attempt in range(REREADS + 1):
        try:
            return link.resolve(strict=True)
        except OSError:
            if attempt == REREADS:
                return link
            time.sleep(REREAD_WAIT_S)
    return link


def env_checkout(prefix: str | Path) -> Path | None:
    """The checkout whose environment *prefix* is (a ``ROOT/.venvs/<name>`` or a ``ROOT/.venv``), else ``None``."""
    prefix = Path(prefix)
    if prefix.parent.name == HOME:
        return prefix.parent.parent
    return prefix.parent if prefix.name == POINTER else None


def superseded(prefix: str | Path) -> bool:
    """Whether another environment than *prefix* (a checkout's ``.venvs/<name>`` or ``.venv``) is now current.

    A plain ``.venv`` directory is superseded once ``.venv`` links to a published environment, so what runs from it
    yields and the directory drains; the environment ``.venv`` links to is not.
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
