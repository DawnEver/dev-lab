"""The dispatcher's ``once`` ledger: a ``once`` row runs at most once per session.

Split from :mod:`dev_lab.dev.hookdispatch` (module-size band). The ledger is one JSON file in the git dir of the
payload's ``cwd`` -- session id to the ``once`` rows it ran -- keeping the last :data:`ONCE_KEPT` sessions. A torn or
foreign ledger is read as empty, so a killed write costs at most one repeated notice, never a crash.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dev_lab.dev.agent_wiring import Wire

__all__ = ['LEDGER_NAME', 'ONCE_KEPT', 'first_runs']

#: The ledger's file name in the git dir.
LEDGER_NAME: Final = 'dev-lab-hook-once.json'
#: The sessions a ledger keeps; older ones are forgotten.
ONCE_KEPT: Final = 64


def first_runs(wires: Sequence[Wire], payload: dict[str, Any], git_dir: Path | None) -> tuple[Wire, ...]:
    """*wires* without the ``once`` rows *payload*'s session already ran; records the ones it runs now.

    *git_dir* holds the ledger; ``None`` (outside a checkout) keeps every row.
    """
    session = str(payload.get('session_id') or '')
    if git_dir is None or not session or not any(wire.once for wire in wires):
        return tuple(wires)
    ledger = git_dir / LEDGER_NAME
    try:
        seen = json.loads(ledger.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        seen = {}
    seen = seen if isinstance(seen, dict) else {}
    ran = set(seen.get(session) or ()) if isinstance(seen.get(session), list) else set()
    keep = tuple(wire for wire in wires if not (wire.once and wire.name in ran))
    seen[session] = sorted(ran | {wire.name for wire in keep if wire.once})
    with contextlib.suppress(OSError):
        ledger.write_text(json.dumps(dict(list(seen.items())[-ONCE_KEPT:])), encoding='utf-8')
    return keep
