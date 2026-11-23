"""MSYS-PATH-REWRITE: Git Bash rewrites every POSIX-absolute argument into its own install root before Python runs.

Measured 2026-11-23: ``sshhold run ops@<host> sudo -n /opt/x/.venv/bin/python ...`` typed in Git Bash on Windows
reached the host as ``D:/Program Files/Git/opt/x/...``, so sudo matched no row and asked for a password (and
``sudo -n -l`` answered "D:/Program: command not found"). The door that sends a REMOTE command refuses such argv
before anything is sent (:func:`refusal`), naming the cause and the doors: prefix ``MSYS_NO_PATHCONV=1``, or pass
the command as data -- a ``planrun`` steps file carries its argv in JSON, which no shell rewrites.

Detected only where it can happen: Windows, inside an MSYS shell (``MSYSTEM`` set), against the Git install root
derived from where ``git`` resolves (``<root>/cmd/git.exe`` or ``<root>/bin/git.exe``).
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import PureWindowsPath

__all__ = ['DOORS', 'git_root', 'refusal', 'rewritten']

#: The doors a refusal names.
DOORS = (
    'prefix the line with MSYS_NO_PATHCONV=1 (Git Bash then passes POSIX paths through untouched), or run the '
    'command as a planrun step (its argv is JSON data no shell rewrites)'
)


def git_root(
    *, env: Mapping[str, str] | None = None, which: Callable[[str], str | None] = shutil.which,
    windows: bool = sys.platform == 'win32',
) -> str:  # fmt: skip
    """The Git for Windows install root an MSYS shell rewrites into; ``''`` outside such a shell."""
    if not windows or not (os.environ if env is None else env).get('MSYSTEM'):
        return ''
    found = which('git')
    if not found:
        return ''
    path = PureWindowsPath(found)
    return path.parent.parent.as_posix() if path.parent.name.lower() in {'cmd', 'bin', 'mingw64'} else ''


def _norm(text: str) -> str:
    return text.replace('\\', '/').rstrip('/').lower()


def rewritten(words: Sequence[str], *, root: str) -> list[str]:
    """The words of *words* that are a path under *root*: what an MSYS shell made of a POSIX path."""
    if not root:
        return []
    base = _norm(root) + '/'
    return [word for word in words if any(_norm(part).startswith(base) for part in word.split('='))]


def refusal(words: Sequence[str], *, root: str | None = None) -> str:
    """Why sending *words* to a remote host is refused (``''`` when it is not), naming the rewritten words."""
    found = rewritten(words, root=git_root() if root is None else root)
    if not found:
        return ''
    return (f'MSYS-PATH-REWRITE: Git Bash rewrote POSIX paths into its install root before this door saw them '
            f'({found}); the remote host would not find them and nothing was sent -- {DOORS}')  # fmt: skip
