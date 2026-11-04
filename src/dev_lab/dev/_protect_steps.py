"""What both protection backends share: a :class:`Step` and how two fact tables differ (:mod:`forgeprotect`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

from dev_lab.dev.forgefailure import ForgeCallFailed

__all__ = ['ABSENT', 'UNREADABLE', 'Step', 'absent', 'created', 'differences']

#: The forge's answer lacks the key: a fact about its API or the credential's reach, never a ``False``.
UNREADABLE: Final = 'unreadable'

#: The HTTP status a forge answers for a rule that does not exist.
ABSENT: Final = 404


@dataclass(frozen=True)
class Step:
    """One difference between the forge and the declaration: what is said, and the write that removes it."""

    subject: str
    lines: tuple[str, ...]
    write: Callable[[], object] = field(compare=False, repr=False)


def differences(live: Mapping[str, object], wanted: Mapping[str, object]) -> tuple[str, ...]:
    """One line per fact of *wanted* that *live* does not hold; an unanswered fact is said as such, never as false."""
    out = []
    for key, value in wanted.items():
        found = live.get(key, UNREADABLE)
        if found == UNREADABLE:
            out.append(f'{key}: the forge did not answer (declared {value!r})')
        elif found != value:
            out.append(f'{key}: live={found!r} declared={value!r}')
    return tuple(out)


def created(wanted: Mapping[str, object]) -> tuple[str, ...]:
    """The facts a rule that does not exist yet will be created with; a fact the rule has no clause for is not said."""
    return tuple(f'{key}: {value!r}' for key, value in wanted.items() if value is not None)


def absent(failed: ForgeCallFailed) -> bool:
    """Whether *failed* is the forge saying the rule does not exist (a final 404), not that it could not answer."""
    return failed.final == ABSENT
