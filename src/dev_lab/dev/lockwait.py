"""``--lock-wait``: the box wait of :mod:`dev_lab.dev.verify`, a DURATION whose unit lives in the value.

User ruling 2026-10-19: a unit lives in the VALUE, never the NAME, so the wait is a pint quantity
(``"30 s"``, ``"2 min"``) and a bare number is refused, by the family's one duration parser
(:func:`lab_commons.quantity.parse`), whose refusal names the flag.
"""

from __future__ import annotations

import argparse

from lab_commons.quantity import parse

__all__ = ['lock_wait', 'lock_wait_arg']


def lock_wait(text: str) -> float:
    """``--lock-wait`` in seconds. The unit lives in the VALUE: a bare number, or a non-duration, is refused."""
    return parse('--lock-wait', text, 'duration')


def lock_wait_arg(text: str) -> float:
    """:func:`lock_wait` as an argparse ``type``: a refusal is an argparse error naming the duration."""
    try:
        return lock_wait(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
