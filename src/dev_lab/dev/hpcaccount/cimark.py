"""The CI-PAUSED marker of a verification account: written by ``ci-pause``, deleted by ``ci-resume``.

While it exists the account's CI cron lines are deliberately absent, so ``deploy`` (which would rewrite them) and
``deploy-fleet`` (whose kit refresh runs a tick) refuse that account naming ``ci-resume-fleet`` as the door.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Final

__all__ = ['MARKER', 'RESUME_DOOR', 'marker', 'paused_guard', 'paused_refusal']

#: The marker, relative to the account's declared root (:mod:`lab_commons.hpc.layout`: a serving role's ``serve``).
MARKER: Final = 'serve/paused'
RESUME_DOOR: Final = 'python -m dev_lab.dev.hpcaccount ci-resume-fleet --account <user>'


def marker(root: str) -> Path:
    """The marker file under the account's declared *root*."""
    return Path(root) / MARKER


def paused_refusal(root: str) -> str:
    """Why a deploy is refused on this account (``''``: not paused)."""
    path = marker(root)
    if not path.is_file():
        return ''
    held = path.read_text(encoding='utf-8', errors='replace').strip()
    return f'this account is CI-PAUSED ({path}: {held}); its CI cron returns only through {RESUME_DOOR}'


def paused_guard(root: str) -> str:
    """The shell line a fleet command starts with: exit 2 naming the door while the account is CI-PAUSED."""
    path = PurePosixPath(root, MARKER)
    return f'{{ [ ! -e {path} ] || {{ echo "refused: CI-PAUSED ({path}); the door is {RESUME_DOOR}"; exit 2; }}; }}'
