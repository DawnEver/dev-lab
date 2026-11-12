"""THE SHAPE OF ONE AGENT-POLICY ROW: the actors and :class:`Door`; the table itself is :mod:`dev_lab.dev.agentpolicy`.

Split from the table by responsibility at the module-size band (2026-11-12): this module says what a row may hold
and refuses a malformed one; the table says which doors exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dev_lab.dev.doorrows import allow_rows

__all__ = ['ACTORS', 'MAIN', 'SUBAGENT', 'USER', 'Door']

#: The main session: it publishes (MAIN-SESSION-PUBLISHES) and changes forge state.
MAIN: Final = 'main'
#: Any agent, the main session's subagents included.
SUBAGENT: Final = 'subagent'
#: The user alone: no agent is allowed it, whatever mode the client runs in.
USER: Final = 'user'
ACTORS: Final = (MAIN, SUBAGENT, USER)

_RUNNERS: Final = ('python', 'git', 'sh', 'gh')


@dataclass(frozen=True, slots=True)
class Door:
    """One door: its argv prefix, who may run it, what it is for (one string), and the deny row it answers."""

    argv: tuple[str, ...]
    actor: str
    intent: str
    deny: str | None = None

    def __post_init__(self) -> None:
        """Refuse an unknown actor or runner, an empty intent, and an allowed door with no argv."""
        if self.actor not in ACTORS:
            msg = f'{self.argv}: actor {self.actor!r} is none of {ACTORS}'
            raise ValueError(msg)
        if self.argv and self.argv[0] not in _RUNNERS:
            msg = f'{self.argv}: runner {self.argv[0]!r} is none of {_RUNNERS}'
            raise ValueError(msg)
        if not self.intent.strip():
            msg = f'{self.argv}: no intent -- say what the door is for, once'
            raise ValueError(msg)

    @property
    def allow_lines(self) -> tuple[str, ...]:
        """The ``permissions.allow`` rows: none for the user's doors or a door-less intent; git also as ``-C``."""
        return () if self.actor == USER or not self.argv else allow_rows(self.argv)
