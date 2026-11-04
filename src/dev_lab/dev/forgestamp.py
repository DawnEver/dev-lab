"""THE PROVENANCE STAMP: which machine, agent and branch wrote a forge comment or issue, as one line.

Split out of :mod:`dev_lab.dev.forgework` by concept: the client SENDS a body, and this module says who the body
is from (:class:`~dev_lab.dev.forgework.Client` appends it to what it creates).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

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
