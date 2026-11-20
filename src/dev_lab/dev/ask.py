"""THE ONE INTAKE OF WHAT A PERSON TYPES: shown as typed, checked against its declared shape before anything is spent.

User ruling D94 (2026-11-20): "it must be displayed -- who are you hiding it from? if the user's input is wrong nobody
can fix it." Measured that day: a hidden Windows prompt took Ctrl+V as a control character and an 83-character
access key was placed and a consent code spent on it. So every value a person types -- a secret for a storage
remote, a forge token, a one-time code -- comes through :func:`value`:

* the prompt is VISIBLE (``input``), and says first what the value is and where the person finds it (the HINT
  declared beside the thing asked, never restated here);
* the answer is stripped of the newline only, then CHECKED: empty, control characters or spaces are refused with the
  paste note, and a value not matching its DECLARED shape is refused naming the shape -- all before the caller spends
  a code, writes a file or opens a connection;
* the check line (length, character class, shape verdict) is said back, never the value.

A code is a value whose shape is :data:`CODE_SHAPE`; :func:`code` takes it from an agent's argument as well (the
code the user gave in chat), through the same check.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

__all__ = ['CODE_SHAPE', 'PASTE_NOTE', 'AskRefused', 'code', 'judged', 'value']

#: A one-time consent / cluster / TOTP code: six digits.
CODE_SHAPE: Final = r'[0-9]{6}'
#: Said before a value: on Windows a console prompt does not take Ctrl+V (it inserts a control character).
PASTE_NOTE: Final = 'paste with a right-click (Ctrl+V does not paste in this prompt on Windows); the value is shown'


class AskRefused(ValueError):
    """A typed value refused before anything was spent; the message names the cause and what to do."""


def judged(name: str, given: str, shape: str) -> tuple[str, str]:
    """A check line for one value (length, characters, declared shape), and why it is refused (``''`` if it is not)."""
    kind = 'hex' if given and all(c in '0123456789abcdefABCDEF' for c in given) else (
        'printable' if given.isprintable() else 'CONTROL CHARACTERS')  # fmt: skip
    matches = re.fullmatch(shape, given) is not None if shape else None
    line = f'  {name}: {len(given)} characters, {kind}' + (
        '' if matches is None else f', {"matches" if matches else "does NOT match"} the declared shape {shape}'
    )
    if not given:
        return line, f'{name} is empty'
    if not given.isprintable() or any(c.isspace() for c in given):
        return line, f'{name} holds control characters or spaces: {PASTE_NOTE}'
    if matches is False:
        return line, f'{name} does not match the declared shape {shape}: check you copied the whole value'
    return line, ''


def value(
    name: str, *, hint: str = '', shape: str = '', ask: Callable[[str], str] = input,
    say: Callable[[str], None] = lambda _line: None,
) -> str:  # fmt: skip
    """Ask *name* shown as typed (with its declared *hint*), check it against *shape*, say the check line.

    Raises:
        AskRefused: empty, control characters or spaces, or not the declared shape -- before anything is spent.

    """
    asked = ask(f'{name}{f" -- {hint}" if hint else ""}\n{name}: ')
    given = asked.strip('\r\n')
    line, why = judged(name, given, shape)
    say(line)
    if why:
        raise AskRefused(why)
    return given


def code(
    given: str | None,
    *,
    what: str,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = lambda _l: None,
) -> str:
    """The user's one-time code for *what*: *given* (the code the user gave an agent) or asked shown as typed.

    Raises:
        AskRefused: not six digits -- before the code is sent anywhere.

    """
    if given is None:
        given = ask(f'cluster code -- the six-digit code your authenticator shows now, for {what}\ncode: ')
    stripped = given.strip()
    line, _why = judged('code', stripped, CODE_SHAPE)
    say(line)
    if re.fullmatch(CODE_SHAPE, stripped) is None:
        kind = line.split(', ', 2)[1] if ', ' in line else 'empty'
        hint = f'; {PASTE_NOTE}' if stripped and not stripped.isprintable() else ''
        msg = f'must be six digits (got {len(stripped)} characters, {kind}){hint}'
        raise AskRefused(msg)
    return stripped
