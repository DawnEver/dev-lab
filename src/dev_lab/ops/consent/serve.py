"""THE ISSUER'S SSH FORCECOMMAND: one JSON line in, the answer out (``python -m dev_lab.ops --config X consent serve``).

A line is ``{"verb": "issue", "request": {...}, "code": "..."}``, ``{"verb": "issue-plan", "plan": {...}, "code":
"..."}`` or ``{"verb": "register", "credential": {...}, "amount": n}``. ``issue`` answers the credential's JSON,
``issue-plan`` the JSON list of one credential per grant; ``register`` the campaign's remaining cap (empty for a
single credential). A refusal raises :class:`~dev_lab.ops.consent.credential.ConsentRefused`; its message never
carries the code.
"""

from __future__ import annotations

import json

from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.issuer import Issuer

__all__ = ['handle']


def handle(issuer: Issuer, line: str) -> str:
    """Answer one request *line* (see the module docstring)."""
    try:
        data = json.loads(line)
    except ValueError as bad:
        msg = 'not one JSON line'
        raise ConsentRefused(msg) from bad
    verb = data.get('verb') if isinstance(data, dict) else None
    if verb in {'issue', 'issue-plan'}:
        code = data.get('code')
        if not isinstance(code, str):
            msg = f'{verb} carries the code as a string'
            raise ConsentRefused(msg)
        if verb == 'issue-plan':
            return json.dumps(issuer.issue_plan(data.get('plan'), code), sort_keys=True)
        return json.dumps(issuer.issue(data.get('request'), code), sort_keys=True)
    if verb == 'register':
        amount = data.get('amount', 1)
        left = issuer.register(data.get('credential'), amount)
        return '' if left is None else str(left)
    msg = 'verb must be issue, issue-plan or register'
    raise ConsentRefused(msg)
