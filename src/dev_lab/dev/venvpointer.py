"""WHICH ENVIRONMENT A NEW LAUNCH TAKES: the one reader of ``ROOT/.venv-current`` (dev-lab #632).

Dependency-free so :mod:`dev_lab.dev.venvpath` can resolve through it; :mod:`dev_lab.dev.venvcurrent` builds,
publishes and reclaims. The JS twin is ``agent_launcher.js``'s ``currentEnv``, the shell one ``with-venv.sh``'s.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

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
    if not name or Path(name).name != name or name in {'.', '..'}:
        return None
    env = Path(root) / HOME / name
    return env if env.is_dir() else None


def _read(pointer: Path) -> str:
    """The pointer's content, ``''`` when absent; a sharing violation mid-swap is retried, never read as absent."""
    for _ in range(READ_TRIES):
        try:
            return pointer.read_text(encoding='utf-8').strip()
        except PermissionError:
            time.sleep(0.01)
        except OSError:
            return ''
    return ''


def current(root: Path) -> Path:
    """The environment a NEW launch in checkout *root* runs from: the pointer's, else the legacy ``.venv``."""
    return named(root) or Path(root) / ALIAS
