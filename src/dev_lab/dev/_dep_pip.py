"""Whether a target interpreter can install with ``-m pip``: the one fact :func:`dev_lab.dev.dep.pip_argv` branches on.

A uv-created venv has no pip (uv seeds none), so the door's install goes through ``uv pip install --python`` there;
this module answers which of the two spellings a given interpreter can take.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import lab_commons.launch as _door

__all__ = ['has_pip']


def has_pip(python: str) -> bool:
    """Whether *python* can run ``-m pip``. A uv-created venv cannot: uv seeds no pip into it.

    The invoking interpreter is answered in-process; any other is asked, because a venv's packages
    are a fact about THAT interpreter and not about this one.
    """
    if python == sys.executable:
        return importlib.util.find_spec('pip') is not None
    try:
        done = _door.run([python, '-c', 'import pip'], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0
