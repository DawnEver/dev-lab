"""A POSIX-shell path in this platform's spelling: git bash on Windows prints ``/c/...``.

``cygpath`` is the shell's own program, so the SHELL finds it. It is not a sibling of whichever ``sh`` the PATH
names: Git for Windows ships a wrapper ``<git>/bin/sh.exe`` beside no ``cygpath`` (that lives in ``usr/bin``), and
a hosted Windows runner's PATH names the wrapper (dev-lab tests/base@windows, 2026-11-22: ``FileNotFoundError``).
"""

from __future__ import annotations

import os
import subprocess


def native(answer: str, sh: str, *, windows: bool = os.name == 'nt') -> str:
    """*answer*, a path the POSIX shell *sh* printed, as this platform spells it (unchanged off Windows)."""
    if not (windows and answer.startswith('/')):
        return answer
    done = subprocess.run(
        [sh, '-c', 'cygpath -w "$1"', 'sh', answer],
        capture_output=True, text=True, encoding='utf-8', check=False, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()
