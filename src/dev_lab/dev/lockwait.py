"""``--lock-wait``: the box wait of :mod:`dev_lab.dev.verify`, a DURATION whose unit lives in the value.

User ruling 2026-10-19: a unit lives in the VALUE, never the NAME, so the wait is a pint quantity
(``"30 s"``, ``"2 min"``) and a bare number is refused. The ``dev`` extra carries ``units``, so pint is
imported here at module level like every other dev door that reads a quantity.
"""

from __future__ import annotations

import argparse

from lab_commons.units import Q_

__all__ = ['lock_wait', 'lock_wait_arg']


def lock_wait(text: str) -> float:
    """``--lock-wait`` in seconds. The unit lives in the VALUE: a bare number, or a non-duration, is refused."""
    try:
        quantity = Q_(text)
    except Exception as exc:
        msg = f'--lock-wait {text!r} is not a duration; write one such as "30 s" or "2 min"'
        raise ValueError(msg) from exc
    if not isinstance(quantity, Q_) or quantity.dimensionless:
        msg = f'--lock-wait {text!r} is a bare number, not a duration: it has no unit -- write e.g. "30 s"'
        raise ValueError(msg)
    if not quantity.check('[time]'):
        msg = f'--lock-wait {text!r} is {quantity.dimensionality}, not a duration; write e.g. "30 s"'
        raise ValueError(msg)
    return float(quantity.m_as('s'))


def lock_wait_arg(text: str) -> float:
    """:func:`lock_wait` as an argparse ``type``: a refusal is an argparse error naming the duration."""
    try:
        return lock_wait(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
