"""The provenance stamp a created issue, PR body or comment opens with: ``[<machine> · <agent> · <branch>]``.

Read from the ``HARNESS_*`` variables and the checkout's branch; :func:`dev_lab.dev.forgework.client_for` stamps it.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S

__all__ = ['provenance']

#: The separator in the provenance line, spelled once.
_DOT: Final = ' · '


def provenance(cwd: Path, env: Mapping[str, str]) -> str | None:
    """``[<machine> · <agent> · <branch>]`` when both HARNESS vars are set, else ``None``."""
    machine, agent = env.get('HARNESS_MACHINE', ''), env.get('HARNESS_AGENT', '')
    if not machine or not agent:
        return None
    done = _door.run(
        [_GIT, 'symbolic-ref', '--short', '-q', 'HEAD'],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    branch = done.stdout.strip() if done.returncode == 0 else ''
    return '[' + _DOT.join(part for part in (machine, agent, branch) if part) + ']'
