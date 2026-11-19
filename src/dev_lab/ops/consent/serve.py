"""THE ISSUER'S SSH FORCECOMMAND: one JSON line in, the answer out (``python -m dev_lab.ops --config X consent serve``).

A line is ``{"verb": "issue", "request": {...}, "code": "..."}``, ``{"verb": "issue-plan", "plan": {...}, "code":
"..."}``, ``{"verb": "register", "credential": {...}, "amount": n}``, ``{"verb": "spent", "ids": [...]}`` or
``{"verb": "fetch-unspent", "plan": "<digest>"}``, ``{"verb": "hello"}`` or ``{"verb": "subject", "action": A,
"argv": [...]}``.
``subject`` is a READ, no code: this host derives *A*'s subject by running its ops verb with ``--subject``
(:func:`~dev_lab.ops.consent.door.read_argv` admits only the registry's read form; an acting flag is refused) and
answers the digest.
``hello`` answers the field set and registry actions this issuer speaks (:func:`~dev_lab.ops.consent.door.hello`):
the version handshake a client runs before it asks the user for a code.
``issue`` answers the credential's JSON, ``issue-plan`` the JSON list of one credential per grant; ``register`` the
campaign's remaining cap (empty for a single credential); ``spent`` the JSON list of those ids whose use the ledger
records; ``fetch-unspent`` the JSON list of the plan's granted, never-used, live credentials, as issued
(:meth:`~dev_lab.ops.consent.issuer.Issuer.unspent`: no code, never a new grant). A refusal raises
:class:`~dev_lab.ops.consent.credential.ConsentRefused`; its message never carries the code.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import hello, read_argv
from dev_lab.ops.consent.issuer import Issuer

__all__ = ['Derive', 'handle']

#: Runs this host's ``dev_lab.ops`` with argv words, read-only (the ``subject`` verb's); ``(exit status, output)``.
type Derive = Callable[[Sequence[str]], tuple[int, str]]


def _subject(data: dict, derive: Derive | None) -> str:
    argv = read_argv(str(data.get('action')), data.get('argv'))
    if derive is None:
        msg = 'this issuer derives no subjects'
        raise ConsentRefused(msg)
    status, said = derive(argv)
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    if status or not lines:
        msg = f'the subject could not be derived here ({status}): {lines[-1] if lines else "no output"}'
        raise ConsentRefused(msg)
    return lines[-1]


def handle(issuer: Issuer, line: str, *, derive: Derive | None = None) -> str:
    """Answer one request *line* (see the module docstring); *derive* runs a ``subject`` read on this host."""
    try:
        data = json.loads(line)
    except ValueError as bad:
        msg = 'not one JSON line'
        raise ConsentRefused(msg) from bad
    verb = data.get('verb') if isinstance(data, dict) else None
    if verb in {'hello', 'subject'}:  # the two reads: no code, no state changed
        return json.dumps(hello(), sort_keys=True) if verb == 'hello' else _subject(data, derive)
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
    if verb == 'fetch-unspent':
        return json.dumps(issuer.unspent(data.get('plan')), sort_keys=True)
    if verb == 'spent':
        return json.dumps(issuer.spent(data.get('ids')))
    msg = 'verb must be hello, subject, issue, issue-plan, register, spent or fetch-unspent'
    raise ConsentRefused(msg)
