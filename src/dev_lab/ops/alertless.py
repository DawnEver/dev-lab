"""The ops verbs that send no alert, declared once.

A declared ``[ops] environment_file`` that did not arrive refuses a verb because its alerts would run silently off
(:func:`dev_lab.ops.config.load`). A verb that never alerts has no alerts to lose: these are what a planrun preflight
runs unprivileged on each host -- ``consent ready`` reads the consent tables and keys, and the ``--subject`` forms of
``config apply`` and ``secret place`` print a digest and change nothing. Every other verb keeps the refusal.
"""

from __future__ import annotations

import argparse
from typing import Final

__all__ = ['ALERTLESS', 'sends_no_alert']

#: ``(verb, action, needs --subject)``: each verb form that raises no alert.
ALERTLESS: Final = frozenset({('consent', 'ready', False), ('config', 'apply', True), ('secret', 'place', True)})


def sends_no_alert(args: argparse.Namespace) -> bool:
    """True when the parsed *args* name a verb form of :data:`ALERTLESS`."""
    action = getattr(args, 'action', None)
    subject = bool(getattr(args, 'subject', False))
    return any((args.verb, action) == (verb, act) and (subject or not needs) for verb, act, needs in ALERTLESS)
