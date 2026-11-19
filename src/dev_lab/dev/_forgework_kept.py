"""Each thread's kept READ connections for :class:`dev_lab.dev.forgework.Client`, by target host.

A connect and a TLS handshake are paid once per thread and host, not per GET. A write never rides a kept
connection (a lost answer there reads as never sent), and a thread never shares one. Carved out of ``forgework``
to keep it inside the module-size band.
"""

from __future__ import annotations

import http.client
import threading
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['KeptReads']

_A = TypeVar('_A')


class KeptReads(threading.local):
    """Each thread's kept read connections, by target."""

    def __init__(self) -> None:
        self.conns: dict[str, http.client.HTTPConnection] = {}

    def read(
        self,
        target: str,
        fresh: Callable[[], http.client.HTTPConnection],
        exchange: Callable[[http.client.HTTPConnection], tuple[_A, bool]],
    ) -> _A:
        """One GET via *exchange* on the kept connection to *target*, else on a *fresh* one.

        *exchange* answers ``(answer, whether the forge closes the connection after it)``. A kept connection the
        forge closed while idle is not a failure: the read is retried once on a fresh one.
        """
        if (conn := self.conns.pop(target, None)) is not None:
            try:
                return self._on(target, conn, exchange)
            except (ConnectionError, http.client.HTTPException):
                conn.close()
        return self._on(target, fresh(), exchange)

    def _on(
        self,
        target: str,
        conn: http.client.HTTPConnection,
        exchange: Callable[[http.client.HTTPConnection], tuple[_A, bool]],
    ) -> _A:
        """One read on *conn*, kept for the next read unless it failed or the forge said it closes."""
        try:
            answer, closing = exchange(conn)
        except BaseException:
            conn.close()
            raise
        if closing:
            conn.close()
        else:
            self.conns[target] = conn
        return answer
