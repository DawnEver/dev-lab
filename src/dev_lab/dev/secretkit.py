"""TYPED-VALUES-ARE-SHOWN, the kit half: a kit that is not current never prompts a person for a secret or a code.

MEASURED 2026-11-24. D94 (2026-11-20) made :mod:`dev_lab.dev.ask` the one visible intake; four days later
``python -m dev_lab.dev.forge auth login`` still asked for the token behind a hidden prompt. The venv held what
its checkout's ``uv.lock`` pinned -- but the checkout lagged its integration branch, so the lock pinned a dev-lab
from before the intake. A fixed intake does not reach a kit that never installed it, and an old kit cannot be
patched after the fact; the guard can only make every kit from here on refuse before it asks.

THE JUDGMENT, local and read only, on the checkout that holds THIS interpreter (:func:`checkout_of`):

* the venv holds what the checkout's ``uv.lock`` pins (:func:`dev_lab.dev.lockpins.lock_freshness`);
* the checkout's ``HEAD`` lags its last-fetched ``origin/<integration>`` by no more than
  :data:`~dev_lab.dev.locklag.LAG_WINDOW`, the family's one "current enough".

An interpreter outside any checkout (a tool dir, a forge runtime) and a checkout whose integration cannot be read
are not judged: nothing here may invent a third answer. :func:`dev_lab.dev.ask.value` and
:func:`dev_lab.dev.ask.code` call :func:`refusal_here` before they PROMPT a person, so every verb that asks is
covered by construction; a value handed over (``--code``, ``--token-stdin``) is not a prompt.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.ask import RULE_ID
from dev_lab.dev.checkoutfollow import integration as declared_integration
from dev_lab.dev.locklag import LAG_WINDOW, Lag, hours, lag_of
from dev_lab.dev.lockpins import Installed, installed_git, locked_git, mismatches, sync_door
from dev_lab.dev.lockpins import refusal as pin_refusal

__all__ = ['RULE_ID', 'checkout_lag', 'checkout_of', 'refusal', 'refusal_here']

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 30


def checkout_of(prefix: Path) -> Path | None:
    """The nearest directory at or above *prefix* holding both ``uv.lock`` and ``.git``; ``None`` outside any."""
    for place in (prefix, *prefix.parents):
        if (place / 'uv.lock').is_file() and (place / '.git').exists():
            return place
    return None


def checkout_lag(root: Path, *, integration: Callable[[Path], str | None] = declared_integration) -> Lag | None:
    """How far *root*'s ``HEAD`` lags its last-fetched ``origin/<integration>``; ``None`` when it cannot be read."""
    branch = integration(root)
    if not branch:
        return None

    def git(*argv: str) -> subprocess.CompletedProcess[str]:
        return _door.run(
            [_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
            check=False, timeout=_GIT_TIMEOUT_S,
        )  # fmt: skip

    try:
        return lag_of(git, 'HEAD', f'refs/remotes/origin/{branch}')
    except (RuntimeError, OSError, ValueError):
        return None


def refusal(
    root: Path,
    *,
    installed: Callable[[], Iterable[Installed]] = installed_git,
    lag: Callable[[Path], Lag | None] = checkout_lag,
) -> str | None:
    """Why the kit at *root* may not prompt for a secret, naming its door; ``None`` when it is current."""
    door = sync_door(root)
    stale = pin_refusal(mismatches(installed(), locked_git(root / 'uv.lock')), door=door)
    if stale is not None:
        return f'{RULE_ID}: nothing was asked -- {stale}'
    behind = lag(root)
    if behind is None or not behind.past(LAG_WINDOW):
        return None
    python = sys.executable
    return (
        f'{RULE_ID}: nothing was asked -- {root} is {behind} behind its integration branch (window '
        f'{hours(LAG_WINDOW)}), so this kit may predate the intake it should ask through. In {root}: on the '
        f'integration branch `{python} -m dev_lab.dev.netverb -- git pull --ff-only`, on a lane '
        f'`{python} -m dev_lab.dev.forge sync`; then {door}; then run this verb again.'
    )


def refusal_here() -> str | None:
    """:func:`refusal` for the checkout holding THIS interpreter; ``None`` outside any checkout."""
    root = checkout_of(Path(sys.prefix))
    return None if root is None else refusal(root)
