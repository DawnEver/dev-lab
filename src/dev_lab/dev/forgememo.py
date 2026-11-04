"""One pass's forge reads, answered once: :class:`ReadMemo` and :func:`remembering`, the client factory that shares it.

THE INCIDENT (2026-11-04): the poller's repo-wide steps -- the integration report, auto-sync, the head
gate, the security step -- each read every open PR head's statuses afresh, several reads of one
``statuses/<sha>`` per pass on a 2-core Gitea host. Gitea's API sends no ``ETag`` or ``Last-Modified``
on these listings (measured 2026-11-04), so a conditional request cannot answer it; a memo the pass
owns can. ANY WRITE through a memoed client empties it (:meth:`dev_lab.dev.forgework.Client._request`),
so a step reads what an earlier one wrote. A pass is a snapshot: what another host writes during it is
read by the next pass.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['ReadMemo', 'remembering']


class ReadMemo(dict[tuple[str, str], Any]):
    """The answers to one pass's reads, keyed by ``(host, path)``: a repeated read is answered from the first."""

    def read(self, key: tuple[str, str], attempt: Callable[[], Any]) -> Any:  # noqa: ANN401 -- JSON
        """A copy of *key*'s first answer, asking *attempt* only the first time."""
        if key not in self:
            self[key] = attempt()
        return copy.deepcopy(self[key])


def remembering(client: Callable[[Path], Client]) -> Callable[[Path], Client]:
    """*client*, each one it builds reading through ONE fresh :class:`ReadMemo`: one pass's."""
    memo = ReadMemo()

    def built(here: Path) -> Client:
        made = client(here)
        made.memo = memo
        return made

    return built
