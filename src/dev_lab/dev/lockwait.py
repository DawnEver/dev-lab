"""``--lock-wait``: the box wait of :mod:`dev_lab.dev.verify`, a DURATION whose unit lives in the value.

User ruling 2026-10-19: a unit lives in the VALUE, never the NAME, so the wait is a pint quantity
(``"30 s"``, ``"2 min"``) and a bare number is refused, by the family's one duration parser
(:func:`lab_commons.quantity.parse`), whose refusal names the flag.
"""

from __future__ import annotations

import argparse
import re

from lab_commons.quantity import QuantityRefused, parse

__all__ = ['lock_wait', 'lock_wait_arg']

#: A number in ``m``: pint's METER, typed by a hand that meant minutes ("60m"). Still refused, but naming ``min``.
_METERS = re.compile(r'\s*(\d+(?:\.\d+)?)\s*m\s*')


def lock_wait(text: str) -> float:
    """``--lock-wait`` in seconds. The unit lives in the VALUE: a bare number, or a non-duration, is refused."""
    try:
        return parse('--lock-wait', text, 'duration')
    except QuantityRefused as exc:
        meters = _METERS.fullmatch(text)
        if meters is None:
            raise
        msg = (
            f'--lock-wait = "{text}" is {meters[1]} meters (pint reads m as the meter), not a duration: '
            f'write the minutes as "{meters[1]} min"'
        )
        raise QuantityRefused(msg) from exc


def lock_wait_arg(text: str) -> float:
    """:func:`lock_wait` as an argparse ``type``: a refusal is an argparse error naming the duration."""
    try:
        return lock_wait(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
